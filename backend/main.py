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
from scanner.prechat_handler import (
    dismiss_cookie_banner,
    fill_prechat_form,
    open_widget,
)
from scanner.attack_runner import run_attacks
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
            await websocket.send_json(
                {"type": "error", "message": "URL is required", "fatal": True}
            )
            return

        if not url.startswith("http"):
            url = f"https://{url}"

        await websocket.send_json(
            {
                "type": "scan_start",
                "url": url,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        anthropic_client = anthropic.AsyncAnthropic()

        async with async_playwright() as pw:
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
                        await websocket.send_json(
                            {
                                "type": "error",
                                "message": f"Browserbase session creation failed: {resp.status_code} {resp.text}",
                                "fatal": True,
                            }
                        )
                        return
                    session = resp.json()
                    session_id = session["id"]

                browser = await pw.chromium.connect_over_cdp(
                    f"wss://connect.browserbase.com?apiKey={browserbase_api_key}&sessionId={session_id}"
                )
            else:
                browser = await pw.chromium.launch(headless=True)

            page = await browser.new_page()
            page.set_default_timeout(30000)

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": f"Failed to load {url}: {str(e)}",
                        "fatal": True,
                    }
                )
                await browser.close()
                return

            cookie_dismissed = await dismiss_cookie_banner(page)
            if cookie_dismissed:
                await websocket.send_json(
                    {"type": "prechat_status", "action": "cookie_dismissed"}
                )

            await asyncio.sleep(3)

            detection_script = build_detection_script()
            try:
                raw_result = await page.evaluate(detection_script)
                results = json.loads(raw_result)
            except Exception:
                results = {"globals": {}, "dom": {}}

            platform = parse_detection_results(results)

            if not platform:
                await websocket.send_json(
                    {
                        "type": "widget_not_found",
                        "message": "No supported chat widget detected on this page.",
                    }
                )
                await websocket.send_json(
                    {
                        "type": "scan_complete",
                        "report": {
                            "url": url,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "platform": None,
                            "overall_grade": "Scan Incomplete",
                            "overall_score": None,
                            "categories": {},
                            "findings": [],
                            "message": "No supported chat widget detected.",
                        },
                    }
                )
                await browser.close()
                return

            await websocket.send_json(
                {
                    "type": "widget_detected",
                    "platform": platform,
                }
            )

            widget_opened = await open_widget(page, platform)
            if widget_opened:
                await websocket.send_json(
                    {"type": "prechat_status", "action": "widget_opened"}
                )

            config = PLATFORM_CONFIGS[platform]
            if config["uses_iframe"] and config.get("iframe_selector"):
                frame_el = await page.query_selector(config["iframe_selector"])
                if frame_el:
                    frame = await frame_el.content_frame()
                    if frame:
                        form_filled = await fill_prechat_form(frame, platform)
                        if form_filled:
                            await websocket.send_json(
                                {"type": "prechat_status", "action": "form_filled"}
                            )
            else:
                form_filled = await fill_prechat_form(page, platform)
                if form_filled:
                    await websocket.send_json(
                        {"type": "prechat_status", "action": "form_filled"}
                    )

            await asyncio.sleep(4)

            async def debug_cb(msg: str):
                await websocket.send_json({"type": "debug", "message": msg})

            findings: list[dict] = []
            async for event in run_attacks(
                page=page,
                platform=platform,
                anthropic_client=anthropic_client,
                delay_seconds=2.0,
                debug_cb=debug_cb,
            ):
                await websocket.send_json(event)

                if event["type"] == "attack_verdict":
                    findings.append(
                        {
                            "id": event["id"],
                            "category": event["category"],
                            "score": event["score"],
                            "verdict": event["verdict"],
                            "confidence": event["confidence"],
                            "evidence": event["evidence"],
                        }
                    )

            by_category: dict[str, list] = {}
            for f in findings:
                by_category.setdefault(f["category"], []).append(f)

            category_scores = {}
            category_details = {}
            for cat in [
                "system_prompt_extraction",
                "goal_hijacking",
                "data_leakage",
                "guardrail_bypass",
            ]:
                cat_findings = by_category.get(cat, [])
                score = calculate_category_score(cat_findings)
                category_scores[cat] = score
                category_details[cat] = {
                    "score": score,
                    "grade": score_to_grade(score) if score is not None else "N/A",
                    "findings_count": len(cat_findings),
                    "vulnerable_count": sum(
                        1 for f in cat_findings if f.get("verdict") == "VULNERABLE"
                    ),
                    "partial_count": sum(
                        1 for f in cat_findings if f.get("verdict") == "PARTIAL"
                    ),
                    "resistant_count": sum(
                        1 for f in cat_findings if f.get("verdict") == "RESISTANT"
                    ),
                    "remediation": REMEDIATION.get(cat, ""),
                }

            overall_score = calculate_overall_score(category_scores)

            report = {
                "url": url,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "platform": platform,
                "overall_grade": (
                    score_to_grade(overall_score)
                    if overall_score is not None
                    else "Scan Incomplete"
                ),
                "overall_score": overall_score,
                "categories": category_details,
                "findings": findings,
            }

            await websocket.send_json({"type": "scan_complete", "report": report})
            await browser.close()

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": str(e),
                    "fatal": True,
                }
            )
        except Exception:
            pass
