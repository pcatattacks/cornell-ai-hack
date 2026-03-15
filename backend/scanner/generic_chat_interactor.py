"""Generic chat interaction — works with any widget found by generic_widget_finder."""

import asyncio
import json
from typing import Optional, Callable, Awaitable

from playwright.async_api import Page
from scanner.generic_widget_finder import GenericWidgetInfo


class GenericChatInteractor:
    """Interact with any chat widget using the info from GenericWidgetInfo."""

    def __init__(self, widget: GenericWidgetInfo, debug_cb: Optional[Callable[[str], Awaitable[None]]] = None):
        self.widget = widget
        self._debug = debug_cb

    async def _log(self, msg: str):
        if self._debug:
            await self._debug(msg)

    def _build_read_script(self) -> str:
        selector = self.widget.chat_container_selector
        if self.widget.uses_shadow_dom and self.widget.shadow_host_selector:
            return f"""
            (() => {{
                const host = document.querySelector('{self.widget.shadow_host_selector}');
                const root = host?.shadowRoot;
                if (!root) return JSON.stringify({{text: null, count: 0}});
                const messages = root.querySelectorAll('{selector}');
                if (messages.length === 0) return JSON.stringify({{text: null, count: 0}});
                const last = messages[messages.length - 1];
                return JSON.stringify({{text: last.textContent.trim(), count: messages.length}});
            }})()
            """
        return f"""
        (() => {{
            const messages = document.querySelectorAll('{selector}');
            if (messages.length === 0) return JSON.stringify({{text: null, count: 0}});
            const last = messages[messages.length - 1];
            return JSON.stringify({{text: last.textContent.trim(), count: messages.length}});
        }})()
        """

    async def send_message(self, page: Page, message: str) -> bool:
        selector = self.widget.chat_input_selector

        if self.widget.uses_shadow_dom and self.widget.shadow_host_selector:
            safe_msg = message.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
            result = await page.evaluate(f"""
                (() => {{
                    const host = document.querySelector('{self.widget.shadow_host_selector}');
                    const root = host?.shadowRoot;
                    if (!root) return 'no_shadow_root';
                    const input = root.querySelector('{selector}');
                    if (!input) return 'no_input';
                    input.focus();
                    const setter = Object.getOwnPropertyDescriptor(
                        window.HTMLTextAreaElement.prototype, 'value'
                    )?.set || Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    )?.set;
                    if (setter) setter.call(input, `{safe_msg}`);
                    else input.value = `{safe_msg}`;
                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    input.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true }}));
                    input.dispatchEvent(new KeyboardEvent('keypress', {{ key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true }}));
                    input.dispatchEvent(new KeyboardEvent('keyup', {{ key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true }}));
                    return 'sent';
                }})()
            """)
            await self._log(f"send_message (shadow): {result}")
            return result == "sent"
        else:
            try:
                locator = page.locator(selector).first
                await locator.fill(message, timeout=10000)
                await locator.press("Enter")
                await self._log("send_message: sent via Playwright locator")
                return True
            except Exception as e:
                await self._log(f"send_message failed: {e}")
                return False

    async def send_and_read(self, page: Page, message: str, timeout_ms: int = 30000) -> Optional[str]:
        read_script = self._build_read_script()

        try:
            before_raw = await page.evaluate(read_script)
            before = json.loads(before_raw)
        except Exception as e:
            await self._log(f"read before send failed: {e}")
            return None

        count_before = before.get("count", 0)
        await self._log(f"{count_before} existing messages")

        sent = await self.send_message(page, message)
        if not sent:
            return None

        poll_interval_ms = 500
        max_polls = timeout_ms // poll_interval_ms
        last_text = None
        stable_count = 0

        for poll_num in range(max_polls):
            await asyncio.sleep(poll_interval_ms / 1000)
            try:
                result_raw = await page.evaluate(read_script)
                result = json.loads(result_raw)
            except Exception:
                continue

            current_count = result.get("count", 0)
            current_text = result.get("text")

            if poll_num % 10 == 0:
                await self._log(f"poll {poll_num}/{max_polls}: count={current_count}, text={repr(current_text[:50]) if current_text else None}")

            if current_count > count_before and current_text:
                if current_text == last_text:
                    stable_count += 1
                    if stable_count >= 2:
                        await self._log(f"response stable after {poll_num} polls")
                        return current_text
                else:
                    stable_count = 0
                    last_text = current_text

        await self._log(f"timed out. last_text={repr(last_text[:50]) if last_text else None}")
        return last_text
