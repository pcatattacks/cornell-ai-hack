"""FastAPI backend for the AI Chatbot Vulnerability Scanner.

Uses Stagehand (Browserbase) for browser automation.
"""

import asyncio
import ipaddress
import json
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

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

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


BLOCKED_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
]


def validate_scan_url(url: str) -> str:
    """Validate and sanitize the scan URL to prevent SSRF."""
    if not url.startswith("http"):
        url = f"https://{url}"
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http/https URLs are allowed")
    host = parsed.hostname or ""
    if host in BLOCKED_HOSTS:
        raise ValueError("Scanning internal addresses is not allowed")
    try:
        addr = ipaddress.ip_address(host)
        if any(addr in net for net in PRIVATE_RANGES):
            raise ValueError("Scanning private IP ranges is not allowed")
    except ValueError as e:
        if "not allowed" in str(e):
            raise
    return url

REMEDIATION = {
    "system_prompt_extraction": "Avoid storing sensitive information (API keys, internal URLs, business logic) in system prompts. Use instruction hierarchy to prevent prompt echo. Consider a separate retrieval layer for business rules.",
    "goal_hijacking": "Implement strong topic boundaries with explicit refusal instructions. Use output validators to check responses stay on-topic. Consider a classifier layer that flags off-topic responses before sending.",
    "data_leakage": "Audit what data your chatbot has access to via RAG or tool calls. Apply principle of least privilege. Never give chatbots access to customer PII. Sanitize markdown rendering to prevent injection.",
    "guardrail_bypass": "Test your topic restrictions with adversarial inputs. Use both input and output filtering. Consider a secondary classifier that validates the chatbot stayed within its approved topics.",
    "insecure_output_handling": "Sanitize all LLM outputs before rendering. Never render raw HTML or markdown from the model. Use Content Security Policy headers. Validate and escape outputs at every trust boundary.",
    "indirect_prompt_injection": "Treat all external content as untrusted. Implement input/output filters. Use instruction hierarchy to separate system instructions from user content. Monitor for unusual patterns in retrieved content.",
}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.websocket("/ws/scan")
async def scan_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("[scan] WebSocket connected")
    scanner = None

    try:
        data = await websocket.receive_json()
        url = data.get("url", "").strip()
        print(f"[scan] Scan requested for: {url[:100]}")

        if not url:
            await websocket.send_json({"type": "error", "message": "URL is required", "fatal": True})
            return

        try:
            url = validate_scan_url(url)
        except ValueError as e:
            await websocket.send_json({"type": "error", "message": str(e), "fatal": True})
            return

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

        # --- Send live view URL to frontend ---
        live_view_url = await scanner.get_live_view_url()
        if live_view_url:
            await websocket.send_json({
                "type": "session_live_view",
                "url": live_view_url,
            })

        # --- Navigate to target ---
        await scanner.navigate(url)

        # --- Find and open chat widget (handles overlays/cookies internally) ---
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
        # Track sent/response events to enrich findings
        pending_attacks: dict = {}

        async for event in run_attacks_stagehand(
            scanner=scanner,
            anthropic_client=anthropic_client,
            delay_seconds=3.0,
            debug_cb=debug_cb,
        ):
            await websocket.send_json(event)

            if event["type"] == "attack_sent":
                pending_attacks[event["id"]] = {
                    "name": event.get("name", ""),
                    "description": event.get("description", ""),
                    "payload": event.get("payload", ""),
                    "technique": event.get("technique", ""),
                    "source": event.get("source", ""),
                    "reference_url": event.get("reference_url", ""),
                }
            elif event["type"] == "attack_response":
                if event["id"] in pending_attacks:
                    pending_attacks[event["id"]]["response"] = event.get("response", "")
            elif event["type"] == "attack_verdict":
                attack_info = pending_attacks.get(event["id"], {})
                findings.append({
                    "id": event["id"],
                    "category": event["category"],
                    "name": attack_info.get("name", ""),
                    "description": attack_info.get("description", ""),
                    "payload": attack_info.get("payload", ""),
                    "response": attack_info.get("response", ""),
                    "technique": attack_info.get("technique", ""),
                    "source": attack_info.get("source", ""),
                    "reference_url": attack_info.get("reference_url", ""),
                    "score": event["score"],
                    "verdict": event["verdict"],
                    "confidence": event["confidence"],
                    "evidence": event["evidence"],
                })
            elif event["type"] in ("browser_died", "rate_limited", "human_handoff", "send_blocked"):
                scan_aborted = True
                abort_reason = event["type"]
                abort_message = event.get("message", "Scan interrupted.")
                abort_completed = event.get("completed_attacks")
                abort_total = event.get("total_attacks")

        # --- Score + Report ---
        report = _build_report(url, "auto-detected (Stagehand)", findings)
        if scan_aborted:
            report["scan_aborted"] = True
            report["abort_reason"] = abort_reason
            report["message"] = abort_message
            if abort_completed is not None:
                report["completed_attacks"] = abort_completed
            if abort_total is not None:
                report["total_attacks"] = abort_total
        await websocket.send_json({"type": "scan_complete", "report": report})

    except WebSocketDisconnect:
        print("[scan] WebSocket disconnected — will clean up session")
    except Exception as e:
        print(f"[scan] ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        try:
            await websocket.send_json({"type": "error", "message": "An internal error occurred. Please try again.", "fatal": True})
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
    for cat in ["system_prompt_extraction", "goal_hijacking", "data_leakage", "guardrail_bypass", "insecure_output_handling", "indirect_prompt_injection"]:
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
