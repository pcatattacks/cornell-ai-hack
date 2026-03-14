"""FastAPI backend for the AI Chatbot Vulnerability Scanner.

Uses Stagehand (Browserbase) for browser automation.
"""

import asyncio
import json
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

import anthropic

from scanner.stagehand_scanner import StagehandScanner
from scanner.attack_runner import run_attacks_stagehand
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
    scanner = None

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

        async def debug_cb(msg: str):
            print(f"[scan] {msg}")
            await websocket.send_json({"type": "debug", "message": msg})

        anthropic_client = anthropic.AsyncAnthropic()

        # --- Initialize Stagehand ---
        scanner = StagehandScanner(debug_cb=debug_cb)
        await scanner.init()

        # --- Navigate to target ---
        await scanner.navigate(url)

        # --- Dismiss cookies ---
        await scanner.dismiss_cookies()
        await websocket.send_json({"type": "prechat_status", "action": "cookie_dismissed"})

        # --- Find and open chat widget ---
        chat_found = await scanner.find_and_open_chat()
        if not chat_found:
            await websocket.send_json({
                "type": "widget_not_found",
                "message": "No chat widget found on this page.",
            })
            await websocket.send_json({
                "type": "scan_complete",
                "report": _empty_report(url),
            })
            return

        await websocket.send_json({
            "type": "widget_detected",
            "platform": "auto-detected (Stagehand)",
        })

        # --- Run attacks ---
        findings: list[dict] = []
        scan_aborted = False

        async for event in run_attacks_stagehand(
            scanner=scanner,
            anthropic_client=anthropic_client,
            delay_seconds=3.0,
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
            if event["type"] == "browser_died":
                scan_aborted = True

        # --- Score + Report ---
        report = _build_report(url, "auto-detected (Stagehand)", findings)
        if scan_aborted:
            report["scan_aborted"] = True
            report["message"] = "Scan interrupted. Report based on completed attacks."
        await websocket.send_json({"type": "scan_complete", "report": report})

    except WebSocketDisconnect:
        print("[scan] WebSocket disconnected")
    except Exception as e:
        print(f"[scan] ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        try:
            await websocket.send_json({"type": "error", "message": str(e), "fatal": True})
        except Exception:
            pass
    finally:
        if scanner:
            await scanner.close()


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
