"""Load payloads and run attacks against a detected chatbot."""

import asyncio
import json
from pathlib import Path
from dataclasses import dataclass
from typing import AsyncGenerator

from scanner.chat_interactor import ChatInteractor
from scanner.response_analyzer import Verdict, judge_response
from scanner.widget_detector import PLATFORM_CONFIGS
from scanner.vision_navigator import ChatTarget
from scanner import generic_chat
from scanner.stagehand_scanner import StagehandScanner

import anthropic
from playwright.async_api import Page


PAYLOADS_PATH = Path(__file__).parent.parent / "payloads" / "payloads.json"


def load_payloads(max_per_category: int | None = None) -> list[dict]:
    with open(PAYLOADS_PATH) as f:
        payloads = json.load(f)

    if max_per_category is not None:
        by_category: dict[str, list] = {}
        for p in payloads:
            by_category.setdefault(p["category"], []).append(p)
        payloads = []
        for cat_payloads in by_category.values():
            payloads.extend(cat_payloads[:max_per_category])

    return payloads


async def run_attacks(
    page: Page,
    platform: str,
    anthropic_client: anthropic.AsyncAnthropic,
    max_per_category: int | None = None,
    delay_seconds: float = 2.0,
    debug_cb=None,
) -> AsyncGenerator[dict, None]:
    config = PLATFORM_CONFIGS[platform]
    interactor = ChatInteractor(platform=platform, config=config, debug_cb=debug_cb)
    payloads = load_payloads(max_per_category=max_per_category)

    for i, payload_data in enumerate(payloads):
        attack_id = i + 1

        yield {
            "type": "attack_sent",
            "id": attack_id,
            "category": payload_data["category"],
            "name": payload_data["name"],
            "payload": payload_data["payload"],
            "progress": f"{attack_id}/{len(payloads)}",
        }

        response_text = await interactor.send_and_read(page, payload_data["payload"])

        yield {
            "type": "attack_response",
            "id": attack_id,
            "response": response_text or "(no response / timeout)",
        }

        if response_text:
            verdict = await judge_response(
                client=anthropic_client,
                category=payload_data["category"],
                payload=payload_data["payload"],
                response=response_text,
            )
        else:
            verdict = Verdict(
                verdict="RESISTANT",
                confidence=0.5,
                evidence="No response received from chatbot (timeout)",
            )

        yield {
            "type": "attack_verdict",
            "id": attack_id,
            "category": payload_data["category"],
            "verdict": verdict.verdict,
            "confidence": verdict.confidence,
            "evidence": verdict.evidence,
            "score": verdict.score,
        }

        await asyncio.sleep(delay_seconds)


async def _is_page_alive(page: Page) -> bool:
    """Check if the browser page is still usable."""
    try:
        await page.evaluate("1 + 1")
        return True
    except Exception:
        return False


async def run_attacks_generic(
    page: Page,
    chat_target: ChatTarget,
    anthropic_client: anthropic.AsyncAnthropic,
    max_per_category: int | None = None,
    delay_seconds: float = 3.0,
    debug_cb=None,
) -> AsyncGenerator[dict, None]:
    """Run attacks using the generic chat interface (vision-guided).

    If the browser dies mid-scan, stops immediately and yields a
    browser_died event so the orchestrator can generate a partial report.
    """
    payloads = load_payloads(max_per_category=max_per_category)
    consecutive_failures = 0

    for i, payload_data in enumerate(payloads):
        attack_id = i + 1

        # Check if browser is still alive before each attack
        if not await _is_page_alive(page):
            yield {
                "type": "browser_died",
                "message": f"Browser session ended after {attack_id - 1} attacks. Generating partial report.",
                "completed_attacks": attack_id - 1,
                "total_attacks": len(payloads),
            }
            return

        yield {
            "type": "attack_sent",
            "id": attack_id,
            "category": payload_data["category"],
            "name": payload_data["name"],
            "payload": payload_data["payload"],
            "progress": f"{attack_id}/{len(payloads)}",
        }

        try:
            response_text = await generic_chat.send_and_read(
                page, payload_data["payload"], chat_target,
                anthropic_client=anthropic_client, debug_cb=debug_cb,
            )
        except Exception as e:
            # Browser may have died during send/read
            if not await _is_page_alive(page):
                yield {
                    "type": "browser_died",
                    "message": f"Browser session ended during attack {attack_id}. Generating partial report.",
                    "completed_attacks": attack_id - 1,
                    "total_attacks": len(payloads),
                }
                return
            response_text = None

        yield {
            "type": "attack_response",
            "id": attack_id,
            "response": response_text or "(no response / timeout)",
        }

        if response_text:
            consecutive_failures = 0
            verdict = await judge_response(
                client=anthropic_client,
                category=payload_data["category"],
                payload=payload_data["payload"],
                response=response_text,
            )
        else:
            consecutive_failures += 1
            verdict = Verdict(
                verdict="RESISTANT",
                confidence=0.5,
                evidence="No response received from chatbot (timeout)",
            )

        yield {
            "type": "attack_verdict",
            "id": attack_id,
            "category": payload_data["category"],
            "verdict": verdict.verdict,
            "confidence": verdict.confidence,
            "evidence": verdict.evidence,
            "score": verdict.score,
        }

        # If 5 consecutive failures, the chatbot is likely rate-limiting or dead
        if consecutive_failures >= 5:
            yield {
                "type": "browser_died",
                "message": f"5 consecutive timeouts after attack {attack_id}. Chatbot may be rate-limiting. Generating partial report.",
                "completed_attacks": attack_id,
                "total_attacks": len(payloads),
            }
            return

        await asyncio.sleep(delay_seconds)


async def run_attacks_stagehand(
    scanner: StagehandScanner,
    anthropic_client: anthropic.AsyncAnthropic,
    max_per_category: int | None = None,
    delay_seconds: float = 3.0,
    debug_cb=None,
) -> AsyncGenerator[dict, None]:
    """Run attacks using Stagehand scanner."""
    payloads = load_payloads(max_per_category=max_per_category)
    consecutive_failures = 0

    for i, payload_data in enumerate(payloads):
        attack_id = i + 1

        yield {
            "type": "attack_sent",
            "id": attack_id,
            "category": payload_data["category"],
            "name": payload_data["name"],
            "payload": payload_data["payload"],
            "progress": f"{attack_id}/{len(payloads)}",
        }

        try:
            response_text = await scanner.send_and_read(payload_data["payload"])
        except Exception as e:
            if debug_cb:
                await debug_cb(f"attack {attack_id} exception: {e}")
            response_text = None

        yield {
            "type": "attack_response",
            "id": attack_id,
            "response": response_text or "(no response / timeout)",
        }

        if response_text:
            consecutive_failures = 0
            verdict = await judge_response(
                client=anthropic_client,
                category=payload_data["category"],
                payload=payload_data["payload"],
                response=response_text,
            )
        else:
            consecutive_failures += 1
            verdict = Verdict(
                verdict="RESISTANT",
                confidence=0.5,
                evidence="No response received from chatbot (timeout)",
            )

        yield {
            "type": "attack_verdict",
            "id": attack_id,
            "category": payload_data["category"],
            "verdict": verdict.verdict,
            "confidence": verdict.confidence,
            "evidence": verdict.evidence,
            "score": verdict.score,
        }

        if consecutive_failures >= 5:
            yield {
                "type": "browser_died",
                "message": f"5 consecutive timeouts. Chatbot may be rate-limiting.",
                "completed_attacks": attack_id,
                "total_attacks": len(payloads),
            }
            return

        await asyncio.sleep(delay_seconds)
