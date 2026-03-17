"""Load payloads and run attacks against a detected chatbot."""

import asyncio
import json
import random
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


def load_payloads(
    max_per_category: int | None = None,
    sample_size: int | None = None,
    strategy: str = "priority",
) -> list[dict]:
    with open(PAYLOADS_PATH) as f:
        payloads = json.load(f)

    # New sampling takes precedence
    if sample_size is not None:
        return _sample_payloads(payloads, sample_size, strategy)

    # Legacy: limit per category
    if max_per_category is not None:
        by_category: dict[str, list] = {}
        for p in payloads:
            by_category.setdefault(p["category"], []).append(p)
        payloads = []
        for cat_payloads in by_category.values():
            payloads.extend(cat_payloads[:max_per_category])

    return payloads


# Must match descending order of CATEGORY_WEIGHTS in scoring.py
_CATEGORY_WEIGHT_ORDER = [
    "system_prompt_extraction",    # 0.25
    "data_leakage",                # 0.20
    "indirect_prompt_injection",   # 0.20
    "goal_hijacking",              # 0.15
    "insecure_output_handling",    # 0.10
    "guardrail_bypass",            # 0.10
]


def _sample_payloads(
    payloads: list[dict], sample_size: int, strategy: str
) -> list[dict]:
    """Sample attacks from the pool using the given strategy."""
    if sample_size >= len(payloads):
        return payloads

    # Group by category
    by_category: dict[str, list[dict]] = {}
    for p in payloads:
        by_category.setdefault(p["category"], []).append(p)

    num_categories = len(by_category)
    quota = max(1, sample_size // num_categories)

    if strategy == "random":
        return _sample_random(by_category, sample_size, quota)
    else:
        return _sample_priority(by_category, sample_size, quota)


def _sample_priority(
    by_category: dict[str, list[dict]], sample_size: int, quota: int
) -> list[dict]:
    """Pick top-priority attacks from each category, then fill remaining slots."""
    selected: list[dict] = []
    remaining: dict[str, list[dict]] = {}

    for cat in _CATEGORY_WEIGHT_ORDER:
        if cat not in by_category:
            continue
        sorted_attacks = sorted(by_category[cat], key=lambda p: p.get("priority", 2))
        take = min(quota, len(sorted_attacks))
        selected.extend(sorted_attacks[:take])
        if take < len(sorted_attacks):
            remaining[cat] = sorted_attacks[take:]

    # Fill remaining slots round-robin by category weight order
    while len(selected) < sample_size and remaining:
        for cat in _CATEGORY_WEIGHT_ORDER:
            if len(selected) >= sample_size:
                break
            if cat in remaining and remaining[cat]:
                selected.append(remaining[cat].pop(0))
                if not remaining[cat]:
                    del remaining[cat]

    return selected


def _sample_random(
    by_category: dict[str, list[dict]], sample_size: int, quota: int
) -> list[dict]:
    """Randomly sample from each category, then fill remaining slots."""
    selected: list[dict] = []
    remaining: list[dict] = []

    for cat in _CATEGORY_WEIGHT_ORDER:
        if cat not in by_category:
            continue
        cat_attacks = list(by_category[cat])
        random.shuffle(cat_attacks)
        take = min(quota, len(cat_attacks))
        selected.extend(cat_attacks[:take])
        remaining.extend(cat_attacks[take:])

    # Fill remaining slots randomly
    random.shuffle(remaining)
    slots_left = sample_size - len(selected)
    if slots_left > 0:
        selected.extend(remaining[:slots_left])

    return selected


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
    last_response = None
    repeated_response_count = 0

    # Common rate limit / error phrases
    RATE_LIMIT_PHRASES = [
        "too many messages", "rate limit", "too many requests",
        "try again later", "slow down", "max messages",
        "limit reached", "quota exceeded",
    ]

    for i, payload_data in enumerate(payloads):
        attack_id = i + 1

        yield {
            "type": "attack_sent",
            "id": attack_id,
            "category": payload_data["category"],
            "name": payload_data["name"],
            "description": payload_data.get("description", ""),
            "payload": payload_data["payload"],
            "technique": payload_data.get("technique", ""),
            "source": payload_data.get("source", ""),
            "reference_url": payload_data.get("reference_url", ""),
            "progress": f"{attack_id}/{len(payloads)}",
        }

        try:
            response_text = await scanner.send_and_read(payload_data["payload"])
        except Exception as e:
            if debug_cb:
                await debug_cb(f"attack {attack_id} exception: {e}")
            response_text = None

        # Check for human handoff or send-blocked (detected during extraction)
        if scanner.human_detected:
            yield {
                "type": "attack_response",
                "id": attack_id,
                "response": response_text or "(no response / timeout)",
            }
            yield {
                "type": "attack_verdict",
                "id": attack_id,
                "category": payload_data["category"],
                "verdict": "RESISTANT",
                "confidence": 0.3,
                "evidence": "Conversation was handed off to a human agent",
                "score": 0.0,
            }
            yield {
                "type": "human_handoff",
                "message": f"Chat transferred to human agent after {attack_id} messages. Stopping scan.",
                "completed_attacks": attack_id,
                "total_attacks": len(payloads),
            }
            return

        if scanner.send_blocked:
            yield {
                "type": "attack_response",
                "id": attack_id,
                "response": response_text or "(no response / timeout)",
            }
            yield {
                "type": "attack_verdict",
                "id": attack_id,
                "category": payload_data["category"],
                "verdict": "RESISTANT",
                "confidence": 0.3,
                "evidence": "Chat system is blocking messages from being sent",
                "score": 0.0,
            }
            yield {
                "type": "send_blocked",
                "message": f"Messages are being blocked after {attack_id} messages. Stopping scan.",
                "completed_attacks": attack_id,
                "total_attacks": len(payloads),
            }
            return

        # Check for rate limiting in the response
        is_rate_limited = False
        if response_text:
            response_lower = response_text.lower()
            for phrase in RATE_LIMIT_PHRASES:
                if phrase in response_lower:
                    is_rate_limited = True
                    break

            # Check for repeated identical responses (sign of stale/cached reads)
            if response_text == last_response:
                repeated_response_count += 1
            else:
                repeated_response_count = 0
            last_response = response_text

        yield {
            "type": "attack_response",
            "id": attack_id,
            "response": response_text or "(no response / timeout)",
        }

        if is_rate_limited:
            yield {
                "type": "attack_verdict",
                "id": attack_id,
                "category": payload_data["category"],
                "verdict": "RESISTANT",
                "confidence": 0.3,
                "evidence": f"Chatbot returned a rate-limit message: {response_text[:80]}",
                "score": 0.0,
            }
            yield {
                "type": "rate_limited",
                "message": f"Chatbot is rate-limiting after {attack_id} messages. Stopping scan and generating report from completed attacks.",
                "completed_attacks": attack_id,
                "total_attacks": len(payloads),
            }
            return

        if response_text and not is_rate_limited:
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

        if not is_rate_limited:
            yield {
                "type": "attack_verdict",
                "id": attack_id,
                "category": payload_data["category"],
                "verdict": verdict.verdict,
                "confidence": verdict.confidence,
                "evidence": verdict.evidence,
                "score": verdict.score,
            }

        # Stop on consecutive failures (timeouts) — threshold lowered from 5 to 3
        # because each failure now includes recovery attempts, so 3 consecutive
        # failures represents a thorough attempt to fix the problem
        if consecutive_failures >= 3:
            yield {
                "type": "rate_limited",
                "message": f"3 consecutive timeouts after {attack_id} messages. Chat may be unresponsive.",
                "completed_attacks": attack_id,
                "total_attacks": len(payloads),
            }
            return

        # Stop if same response repeated 2+ times (reading stale responses)
        if repeated_response_count >= 2:
            if debug_cb:
                await debug_cb(f"Same response repeated {repeated_response_count} times — likely rate-limited")
            yield {
                "type": "rate_limited",
                "message": f"Chatbot returning identical responses after {attack_id} messages. Likely rate-limited.",
                "completed_attacks": attack_id,
                "total_attacks": len(payloads),
            }
            return

        await asyncio.sleep(delay_seconds)
