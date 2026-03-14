"""Load payloads and run attacks against a detected chatbot."""

import asyncio
import json
from pathlib import Path
from dataclasses import dataclass
from typing import AsyncGenerator

from scanner.chat_interactor import ChatInteractor
from scanner.response_analyzer import Verdict, judge_response
from scanner.widget_detector import PLATFORM_CONFIGS

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
