"""Generic chat send/read — works with any widget located by vision_navigator."""

import asyncio
import json
from typing import Optional, Callable, Awaitable

from playwright.async_api import Page
from scanner.vision_navigator import ChatTarget


async def send_message(
    page: Page,
    message: str,
    chat_target: ChatTarget,
    debug_cb: Optional[Callable[[str], Awaitable[None]]] = None,
) -> bool:
    """Send a message to the chat widget."""
    async def _log(msg: str):
        if debug_cb:
            await debug_cb(msg)

    # Strategy 1: Use CSS selector if available
    if chat_target.method == "selector" and chat_target.input_selector:
        try:
            locator = page.locator(chat_target.input_selector).first
            await locator.click(timeout=5000)
            await locator.fill(message, timeout=5000)
            await locator.press("Enter")
            await _log(f"generic_chat: sent via selector '{chat_target.input_selector}'")
            return True
        except Exception as e:
            await _log(f"generic_chat: selector failed ({e}), falling back to coordinates")

    # Strategy 2: Click coordinates and type via keyboard
    if chat_target.input_coordinates:
        x, y = chat_target.input_coordinates
        try:
            await page.mouse.click(x, y)
            await asyncio.sleep(0.3)

            # Try to find and use the focused element
            focused_tag = await page.evaluate("document.activeElement?.tagName || 'none'")
            await _log(f"generic_chat: clicked ({x}, {y}), focused element: {focused_tag}")

            if focused_tag.lower() in ("textarea", "input"):
                # Good — we focused an input. Use fill on active element.
                await page.keyboard.type(message, delay=10)
                await page.keyboard.press("Enter")
                await _log("generic_chat: sent via keyboard.type on focused element")
                return True
            else:
                # Try typing anyway — some contenteditable elements don't report as input
                await page.keyboard.type(message, delay=10)
                await page.keyboard.press("Enter")
                await _log("generic_chat: sent via keyboard.type (non-input focused)")
                return True

        except Exception as e:
            await _log(f"generic_chat: coordinate click+type failed: {e}")
            return False

    await _log("generic_chat: no input method available")
    return False


async def read_latest_response(
    page: Page,
    debug_cb: Optional[Callable[[str], Awaitable[None]]] = None,
) -> tuple[Optional[str], int]:
    """Read the latest bot response from the chat widget.

    Returns (text, message_count).
    """
    read_script = """
        (() => {
            // Strategy: find message-like elements across regular DOM and shadow DOMs
            function findMessagesInRoot(root) {
                // Common selectors for chat message containers
                const selectors = [
                    '[class*="message"]', '[class*="bubble"]', '[class*="response"]',
                    '[data-role="assistant"]', '[class*="bot-"]', '[class*="agent-"]',
                    '[data-testid*="message"]', '[class*="chat-text"]',
                    '[class*="Message"]', '[class*="Bubble"]',
                ];

                let allMessages = [];
                for (const sel of selectors) {
                    const msgs = root.querySelectorAll(sel);
                    if (msgs.length > 0) {
                        allMessages = [...msgs];
                        break;  // Use the first selector that matches
                    }
                }

                return allMessages;
            }

            let messages = findMessagesInRoot(document);

            // Check shadow DOMs too
            if (messages.length === 0) {
                const allElements = document.querySelectorAll('*');
                for (const el of allElements) {
                    if (el.shadowRoot) {
                        messages = findMessagesInRoot(el.shadowRoot);
                        if (messages.length > 0) break;
                    }
                }
            }

            if (messages.length === 0) {
                return JSON.stringify({text: null, count: 0});
            }

            // Get the last message text
            const last = messages[messages.length - 1];
            return JSON.stringify({
                text: last.textContent?.trim() || null,
                count: messages.length,
            });
        })()
    """

    try:
        raw = await page.evaluate(read_script)
        result = json.loads(raw)
        return result.get("text"), result.get("count", 0)
    except Exception:
        return None, 0


async def send_and_read(
    page: Page,
    message: str,
    chat_target: ChatTarget,
    debug_cb: Optional[Callable[[str], Awaitable[None]]] = None,
    timeout_ms: int = 30000,
) -> Optional[str]:
    """Send a message and wait for the bot response."""
    async def _log(msg: str):
        if debug_cb:
            await debug_cb(msg)

    # Get baseline: both text and count
    text_before, count_before = await read_latest_response(page)
    await _log(f"generic_chat: {count_before} existing messages before send, text_before={repr(text_before[:40]) if text_before else None}")

    # Send
    sent = await send_message(page, message, chat_target, debug_cb)
    if not sent:
        return None

    # Poll for response — detect EITHER new message elements OR text content change
    poll_interval_ms = 500
    max_polls = timeout_ms // poll_interval_ms
    last_text = None
    stable_count = 0

    for poll_num in range(max_polls):
        await asyncio.sleep(poll_interval_ms / 1000)
        current_text, current_count = await read_latest_response(page)

        if poll_num % 10 == 0:
            await _log(f"generic_chat: poll {poll_num}/{max_polls} — count={current_count}, text={repr(current_text[:50]) if current_text else None}")

        # Detect a new response by EITHER:
        # 1. New message element appeared (count increased)
        # 2. Text content changed from what was there before we sent our message
        has_new_content = False
        if current_text:
            if current_count > count_before:
                has_new_content = True
            elif current_text != text_before:
                has_new_content = True

        if has_new_content:
            if current_text == last_text:
                stable_count += 1
                if stable_count >= 2:
                    await _log(f"generic_chat: response stable after {poll_num} polls")
                    return current_text
            else:
                stable_count = 0
                last_text = current_text

    await _log(f"generic_chat: timed out. last_text={repr(last_text[:50]) if last_text else None}")
    return last_text
