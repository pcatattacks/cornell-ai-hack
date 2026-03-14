"""Send messages to and read responses from chat widgets via Playwright."""

import asyncio
import json
from typing import Optional, Callable, Awaitable

from playwright.async_api import Page, Frame


class ChatInteractor:
    def __init__(self, platform: str, config: dict, debug_cb: Optional[Callable[[str], Awaitable[None]]] = None):
        self.platform = platform
        self.config = config
        self._debug = debug_cb  # async callback(msg: str) -> None

    async def _log(self, msg: str):
        if self._debug:
            await self._debug(msg)

    def needs_iframe(self) -> bool:
        return self.config.get("uses_iframe", False)

    def build_read_script(self) -> str:
        selector = self.config["response_selector"]
        shadow_host = self.config.get("shadow_host")
        if shadow_host:
            return f"""
            (() => {{
                const host = document.querySelector('{shadow_host}');
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

    async def send_message(self, target, message: str) -> bool:
        selector = self.config["input_selector"]
        shadow_host = self.config.get("shadow_host")
        try:
            if shadow_host:
                # Playwright CSS cannot pierce shadow DOM — use JS directly
                safe_message = message.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
                result = await target.evaluate(f"""
                    (() => {{
                        const host = document.querySelector('{shadow_host}');
                        const root = host?.shadowRoot;
                        if (!root) return 'no_shadow_root';
                        const input = root.querySelector('{selector}');
                        if (!input) {{
                            const allTestids = [...root.querySelectorAll('[data-testid]')].map(e => e.getAttribute('data-testid')).join(',');
                            const allInputs = [...root.querySelectorAll('input,textarea,[contenteditable]')].map(e => e.tagName + '.' + e.className.substring(0,30)).join(',');
                            return 'no_input|testids=' + allTestids + '|inputs=' + allInputs;
                        }}
                        input.focus();
                        const setter = Object.getOwnPropertyDescriptor(
                            window.HTMLTextAreaElement.prototype, 'value'
                        ).set;
                        setter.call(input, `{safe_message}`);
                        input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        input.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }}));
                        input.dispatchEvent(new KeyboardEvent('keypress', {{ key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }}));
                        input.dispatchEvent(new KeyboardEvent('keyup', {{ key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }}));
                        return 'sent';
                    }})()
                """)
                await self._log(f"send_message: JS result='{result}'")
                return result == "sent"
            else:
                input_locator = target.locator(selector)
                await self._log(f"send_message: filling '{selector}'")
                await input_locator.fill(message, timeout=10000)
                await input_locator.press("Enter")
                await self._log(f"send_message: sent successfully")
                return True
        except Exception as e:
            await self._log(f"send_message: failed '{selector}': {e}")
            return False

    async def send_and_read(self, page: Page, message: str, timeout_ms: int = 30000) -> Optional[str]:
        target = await self._get_target(page)
        if target is None:
            await self._log("send_and_read: _get_target returned None — iframe not found or not accessible")
            return None

        read_script = self.build_read_script()
        try:
            before_raw = await target.evaluate(read_script)
            before = json.loads(before_raw)
        except Exception as e:
            await self._log(f"send_and_read: failed to evaluate read script before send: {e}")
            return None
        count_before = before.get("count", 0)
        await self._log(f"send_and_read: {count_before} existing messages before send")

        sent = await self.send_message(target, message)
        if not sent:
            await self._log("send_and_read: message was NOT sent (send_message returned False)")
            return None

        await self._log("send_and_read: message sent, polling for response...")

        poll_interval_ms = 500
        max_polls = timeout_ms // poll_interval_ms
        last_text = None
        stable_count = 0

        for poll_num in range(max_polls):
            await asyncio.sleep(poll_interval_ms / 1000)
            try:
                result_raw = await target.evaluate(read_script)
                result = json.loads(result_raw)
            except Exception as e:
                await self._log(f"send_and_read: poll {poll_num} evaluate failed: {e}")
                continue
            current_count = result.get("count", 0)
            current_text = result.get("text")

            if poll_num % 10 == 0:  # log every 5 seconds
                await self._log(f"send_and_read: poll {poll_num}/{max_polls} — count={current_count}, text_preview={repr(current_text[:60]) if current_text else None}")

            if current_count > count_before and current_text:
                if current_text == last_text:
                    stable_count += 1
                    if stable_count >= 2:
                        await self._log(f"send_and_read: response stable after {poll_num} polls")
                        return current_text
                else:
                    stable_count = 0
                    last_text = current_text

        await self._log(f"send_and_read: timed out after {max_polls} polls. last_text={repr(last_text[:60]) if last_text else None}")
        return last_text

    async def _get_target(self, page: Page):
        if self.config.get("shadow_host"):
            await self._log(f"_get_target: shadow DOM platform, using page directly (host: {self.config['shadow_host']})")
            return page
        if not self.needs_iframe():
            await self._log("_get_target: no iframe needed, using page directly")
            return page
        iframe_selector = self.config.get("iframe_selector")
        if not iframe_selector:
            await self._log("_get_target: uses_iframe=True but no iframe_selector configured, using page")
            return page
        await self._log(f"_get_target: looking for iframe with selector '{iframe_selector}'")
        frame_element = await page.query_selector(iframe_selector)
        if frame_element is None:
            await self._log(f"_get_target: iframe '{iframe_selector}' NOT found in DOM")
            return None
        frame = await frame_element.content_frame()
        if frame is None:
            await self._log(f"_get_target: iframe element found but content_frame() returned None")
            return None
        await self._log(f"_get_target: iframe found and accessible")
        return frame
