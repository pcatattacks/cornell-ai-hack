"""Send messages to and read responses from chat widgets via Playwright."""

import asyncio
import json
from typing import Optional

from playwright.async_api import Page, Frame


class ChatInteractor:
    def __init__(self, platform: str, config: dict):
        self.platform = platform
        self.config = config

    def needs_iframe(self) -> bool:
        return self.config.get("uses_iframe", False)

    def build_read_script(self) -> str:
        selector = self.config["response_selector"]
        return f"""
        (() => {{
            const messages = document.querySelectorAll('{selector}');
            if (messages.length === 0) return JSON.stringify({{text: null, count: 0}});
            const last = messages[messages.length - 1];
            return JSON.stringify({{text: last.textContent.trim(), count: messages.length}});
        }})()
        """

    async def send_message(self, target, message: str) -> bool:
        selector = self.config["input_selector"]
        try:
            input_el = await target.wait_for_selector(selector, timeout=5000)
            if input_el is None:
                return False
            await input_el.click()
            await input_el.fill(message)
            await input_el.press("Enter")
            return True
        except Exception:
            return False

    async def send_and_read(self, page: Page, message: str, timeout_ms: int = 30000) -> Optional[str]:
        target = await self._get_target(page)
        if target is None:
            return None

        read_script = self.build_read_script()
        before_raw = await target.evaluate(read_script)
        before = json.loads(before_raw)
        count_before = before.get("count", 0)

        sent = await self.send_message(target, message)
        if not sent:
            return None

        poll_interval_ms = 500
        max_polls = timeout_ms // poll_interval_ms
        last_text = None
        stable_count = 0

        for _ in range(max_polls):
            await asyncio.sleep(poll_interval_ms / 1000)
            result_raw = await target.evaluate(read_script)
            result = json.loads(result_raw)
            current_count = result.get("count", 0)
            current_text = result.get("text")

            if current_count > count_before and current_text:
                if current_text == last_text:
                    stable_count += 1
                    if stable_count >= 2:
                        return current_text
                else:
                    stable_count = 0
                    last_text = current_text

        return last_text

    async def _get_target(self, page: Page):
        if not self.needs_iframe():
            return page
        iframe_selector = self.config.get("iframe_selector")
        if not iframe_selector:
            return page
        frame_element = await page.query_selector(iframe_selector)
        if frame_element is None:
            return None
        frame = await frame_element.content_frame()
        return frame
