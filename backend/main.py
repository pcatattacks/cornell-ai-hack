"""FastAPI backend for the AI Chatbot Vulnerability Scanner."""

import asyncio
import json
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright

import anthropic

from scanner.widget_detector import (
    build_detection_script,
    parse_detection_results,
    PLATFORM_CONFIGS,
)
from scanner.prechat_handler import dismiss_cookie_banner, fill_prechat_form, open_widget
from scanner.attack_runner import run_attacks, run_attacks_generic
from scanner.vision_navigator import navigate_to_chat
from scanner.scoring import (
    calculate_category_score,
    calculate_overall_score,
    score_to_grade,
)

load_dotenv()

app = FastAPI(title="AI Chatbot Vulnerability Scanner")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

REMEDIATION = {
    "system_prompt_extraction": "Avoid storing sensitive information (API keys, internal URLs, business logic) in system prompts. Use instruction hierarchy to prevent prompt echo. Consider a separate retrieval layer for business rules.",
    "goal_hijacking": "Implement strong topic boundaries with explicit refusal instructions. Use output validators to check responses stay on-topic. Consider a classifier layer that flags off-topic responses before sending.",
    "data_leakage": "Audit what data your chatbot has access to via RAG or tool calls. Apply principle of least privilege. Never give chatbots access to customer PII. Sanitize markdown rendering to prevent injection.",
    "guardrail_bypass": "Test your topic restrictions with adversarial inputs. Use both input and output filtering. Consider a secondary classifier that validates the chatbot stayed within its approved topics.",
}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.websocket("/ws/scan")
async def scan_endpoint(websocket: WebSocket):
    await websocket.accept()

    try:
        data = await websocket.receive_json()
        url = data.get("url")
        if not url:
            await websocket.send_json({"type": "error", "message": "URL is required", "fatal": True})
            return

        if not url.startswith("http"):
            url = f"https://{url}"

        await websocket.send_json({
            "type": "scan_start",
            "url": url,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        anthropic_client = anthropic.AsyncAnthropic()

        async def debug_cb(msg: str):
            await websocket.send_json({"type": "debug", "message": msg})

        # --- Launch browser ---
        async with async_playwright() as pw:
            browser = await _launch_browser(pw, websocket)
            if not browser:
                return

            page = await browser.new_page()
            page.set_default_timeout(30000)

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                await websocket.send_json({"type": "error", "message": f"Failed to load {url}: {e}", "fatal": True})
                await browser.close()
                return

            # --- Dismiss cookie banners ---
            if await dismiss_cookie_banner(page):
                await websocket.send_json({"type": "prechat_status", "action": "cookie_dismissed"})

            await asyncio.sleep(3)

            # --- Detect widget ---
            # Try platform-specific detection first (fast, no API cost)
            platform = await _detect_platform(page, debug_cb)
            chat_target = None
            use_vision = False

            if platform:
                await websocket.send_json({"type": "widget_detected", "platform": platform})

                # Try platform-specific open + prechat
                if await open_widget(page, platform, debug_cb=debug_cb):
                    await websocket.send_json({"type": "prechat_status", "action": "widget_opened"})

                config = PLATFORM_CONFIGS[platform]
                if config["uses_iframe"] and config.get("iframe_selector"):
                    frame_el = await page.query_selector(config["iframe_selector"])
                    if frame_el:
                        frame = await frame_el.content_frame()
                        if frame and await fill_prechat_form(frame, platform, debug_cb=debug_cb):
                            await websocket.send_json({"type": "prechat_status", "action": "form_filled"})
                else:
                    if await fill_prechat_form(page, platform, debug_cb=debug_cb):
                        await websocket.send_json({"type": "prechat_status", "action": "form_filled"})

                await asyncio.sleep(4)

                # Quick check: can we actually send messages with platform-specific approach?
                # Try to find the input element
                input_selector = config.get("input_selector")
                shadow_host = config.get("shadow_host")
                input_found = False

                if shadow_host:
                    check = await page.evaluate(f"""
                        (() => {{
                            const host = document.querySelector('{shadow_host}');
                            const root = host?.shadowRoot;
                            if (!root) return false;
                            return !!root.querySelector('{input_selector}');
                        }})()
                    """)
                    input_found = bool(check)
                elif input_selector:
                    try:
                        el = await page.query_selector(input_selector)
                        input_found = el is not None
                    except Exception:
                        pass

                if not input_found:
                    await debug_cb(f"Platform-specific input '{input_selector}' not found. Falling back to vision-guided approach.")
                    use_vision = True

            if not platform or use_vision:
                # --- Vision-guided fallback ---
                await websocket.send_json({"type": "debug", "message": "Using vision-guided approach to find and open chat widget..."})

                chat_target = await navigate_to_chat(page, anthropic_client, debug_cb=debug_cb)

                if not chat_target:
                    await websocket.send_json({
                        "type": "widget_not_found",
                        "message": "No chat widget found (tried platform detection + vision-guided approach).",
                    })
                    await websocket.send_json({
                        "type": "scan_complete",
                        "report": _empty_report(url),
                    })
                    await browser.close()
                    return

                platform = f"generic (vision-guided)"
                await websocket.send_json({
                    "type": "widget_detected",
                    "platform": platform,
                    "description": chat_target.description,
                })

            # --- Run attacks ---
            findings: list[dict] = []

            if chat_target:
                # Vision-guided attack path
                async for event in run_attacks_generic(
                    page=page,
                    chat_target=chat_target,
                    anthropic_client=anthropic_client,
                    delay_seconds=2.0,
                    debug_cb=debug_cb,
                ):
                    await websocket.send_json(event)
                    if event["type"] == "attack_verdict":
                        findings.append({
                            "id": event["id"],
                            "category": event["category"],
                            "score": event["score"],
                            "verdict": event["verdict"],
                            "confidence": event["confidence"],
                            "evidence": event["evidence"],
                        })
            else:
                # Platform-specific attack path
                async for event in run_attacks(
                    page=page,
                    platform=platform,
                    anthropic_client=anthropic_client,
                    delay_seconds=2.0,
                    debug_cb=debug_cb,
                ):
                    await websocket.send_json(event)
                    if event["type"] == "attack_verdict":
                        findings.append({
                            "id": event["id"],
                            "category": event["category"],
                            "score": event["score"],
                            "verdict": event["verdict"],
                            "confidence": event["confidence"],
                            "evidence": event["evidence"],
                        })

            # --- Score + Report ---
            report = _build_report(url, platform, findings)
            await websocket.send_json({"type": "scan_complete", "report": report})
            await browser.close()

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e), "fatal": True})
        except Exception:
            pass


# --- Helper functions ---

async def _launch_browser(pw, websocket):
    """Launch browser — Browserbase remote or local fallback."""
    browserbase_api_key = os.getenv("BROWSERBASE_API_KEY")
    browserbase_project_id = os.getenv("BROWSERBASE_PROJECT_ID")

    if browserbase_api_key and browserbase_project_id:
        import httpx
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                "https://www.browserbase.com/v1/sessions",
                headers={"x-bb-api-key": browserbase_api_key},
                json={"projectId": browserbase_project_id},
            )
            if resp.status_code not in (200, 201):
                await websocket.send_json({
                    "type": "error",
                    "message": f"Browserbase session creation failed: {resp.status_code} {resp.text}",
                    "fatal": True,
                })
                return None
            session = resp.json()
            session_id = session["id"]

        return await pw.chromium.connect_over_cdp(
            f"wss://connect.browserbase.com?apiKey={browserbase_api_key}&sessionId={session_id}"
        )
    else:
        return await pw.chromium.launch(headless=True)


async def _detect_platform(page, debug_cb):
    """Try platform-specific detection."""
    detection_script = build_detection_script()
    try:
        raw_result = await page.evaluate(detection_script)
        results = json.loads(raw_result)
    except Exception:
        results = {"globals": {}, "dom": {}}

    platform = parse_detection_results(results)
    if platform:
        await debug_cb(f"Platform detected: {platform}")
    else:
        await debug_cb("No known platform detected via globals/DOM")
    return platform


def _empty_report(url):
    return {
        "url": url,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": None,
        "overall_grade": "Scan Incomplete",
        "overall_score": None,
        "categories": {},
        "findings": [],
        "message": "No chat widget detected.",
    }


def _build_report(url, platform, findings):
    by_category: dict[str, list] = {}
    for f in findings:
        by_category.setdefault(f["category"], []).append(f)

    category_scores = {}
    category_details = {}
    for cat in ["system_prompt_extraction", "goal_hijacking", "data_leakage", "guardrail_bypass"]:
        cat_findings = by_category.get(cat, [])
        score = calculate_category_score(cat_findings)
        category_scores[cat] = score
        category_details[cat] = {
            "score": score,
            "grade": score_to_grade(score) if score is not None else "N/A",
            "findings_count": len(cat_findings),
            "vulnerable_count": sum(1 for f in cat_findings if f.get("verdict") == "VULNERABLE"),
            "partial_count": sum(1 for f in cat_findings if f.get("verdict") == "PARTIAL"),
            "resistant_count": sum(1 for f in cat_findings if f.get("verdict") == "RESISTANT"),
            "remediation": REMEDIATION.get(cat, ""),
        }

    overall_score = calculate_overall_score(category_scores)

    return {
        "url": url,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": platform,
        "overall_grade": score_to_grade(overall_score) if overall_score is not None else "Scan Incomplete",
        "overall_score": overall_score,
        "categories": category_details,
        "findings": findings,
    }
