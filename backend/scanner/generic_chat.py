"""Generic chat send/read — works with any widget located by vision_navigator.

When interaction fails (overlays, popups, form gates), takes a screenshot
and asks Claude to diagnose and fix the problem before retrying.
"""

import asyncio
import base64
import json
from typing import Optional, Callable, Awaitable

import anthropic
from playwright.async_api import Page
from scanner.vision_navigator import ChatTarget, _ask_claude, _take_screenshot


async def send_message(
    page: Page,
    message: str,
    chat_target: ChatTarget,
    anthropic_client: Optional[anthropic.AsyncAnthropic] = None,
    debug_cb: Optional[Callable[[str], Awaitable[None]]] = None,
    _retry_count: int = 0,
) -> bool:
    """Send a message to the chat widget. If blocked, use vision to diagnose and recover."""
    async def _log(msg: str):
        if debug_cb:
            await debug_cb(msg)

    # Strategy 1: Playwright locator (most reliable when it works)
    if chat_target.input_selector:
        try:
            locator = page.locator(chat_target.input_selector).first
            await locator.click(timeout=5000)
            await locator.fill(message, timeout=5000)
            await locator.press("Enter")
            await _log(f"generic_chat: sent via selector '{chat_target.input_selector}'")
            return True
        except Exception as e:
            error_msg = str(e)
            await _log(f"generic_chat: selector failed — {type(e).__name__}")

            # If overlay is intercepting, try force click
            if "intercepts pointer events" in error_msg:
                try:
                    locator = page.locator(chat_target.input_selector).first
                    await locator.click(timeout=5000, force=True)
                    await locator.fill(message, timeout=5000)
                    await locator.press("Enter")
                    await _log("generic_chat: sent via force click (bypassed overlay)")
                    return True
                except Exception as e2:
                    await _log(f"generic_chat: force click also failed — {type(e2).__name__}")

    # Strategy 2: JS direct focus + value set (bypasses all overlays and event interception)
    if chat_target.input_selector:
        try:
            safe_msg = message.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
            result = await page.evaluate(f"""
                (() => {{
                    const el = document.querySelector('{chat_target.input_selector}');
                    if (!el) return 'not_found';
                    el.focus();
                    el.value = `{safe_msg}`;
                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    // Try submitting via Enter key event
                    el.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true }}));
                    el.dispatchEvent(new KeyboardEvent('keyup', {{ key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true }}));
                    return 'sent';
                }})()
            """)
            if result == "sent":
                await _log("generic_chat: sent via JS direct focus + value set")
                return True
            await _log(f"generic_chat: JS focus result: {result}")
        except Exception as e:
            await _log(f"generic_chat: JS focus failed: {e}")

    # Strategy 3: Click coordinates + keyboard type
    if chat_target.input_coordinates:
        x, y = chat_target.input_coordinates
        try:
            await page.mouse.click(x, y)
            await asyncio.sleep(0.3)
            focused_tag = await page.evaluate("document.activeElement?.tagName || 'none'")
            await _log(f"generic_chat: clicked ({x}, {y}), focused: {focused_tag}")
            await page.keyboard.type(message, delay=10)
            await page.keyboard.press("Enter")
            await _log("generic_chat: sent via coordinate click + keyboard")
            return True
        except Exception as e:
            await _log(f"generic_chat: coordinate typing failed: {e}")

    # Strategy 4: Vision-guided recovery (take screenshot, ask Claude what's blocking us)
    if anthropic_client and _retry_count < 2:
        await _log("generic_chat: all strategies failed. Using vision to diagnose...")
        recovered_target = await _vision_recover(page, anthropic_client, _log)
        if recovered_target:
            await _log(f"generic_chat: vision recovery found new target: {recovered_target.description}")
            return await send_message(
                page, message, recovered_target,
                anthropic_client=anthropic_client,
                debug_cb=debug_cb,
                _retry_count=_retry_count + 1,
            )

    await _log("generic_chat: all send strategies exhausted")
    return False


async def _vision_recover(
    page: Page,
    anthropic_client: anthropic.AsyncAnthropic,
    _log: Callable,
) -> Optional[ChatTarget]:
    """Take a screenshot, ask Claude what's blocking interaction, and try to fix it."""
    screenshot_b64 = await _take_screenshot(page)

    result = await _ask_claude(
        anthropic_client,
        screenshot_b64,
        """CONTEXT: I am trying to send a message to a chatbot on this webpage, but my interaction failed. Something is blocking me from typing into the chat input.

TASK: Look at this screenshot and tell me what's wrong and how to fix it.

Common blockers:
1. An EMAIL/NAME FORM overlay is covering the chat input — I need to either fill it or dismiss it
2. A COOKIE CONSENT banner is blocking interaction
3. A POPUP or MODAL is covering the chat area
4. The chat widget CLOSED or NAVIGATED AWAY from the conversation view
5. The chat INPUT MOVED to a different position

What do you see? What action should I take to unblock the chat input?

If there's a form to fill or dismiss, provide the coordinates of:
- A close/dismiss/skip button (preferred)
- OR the form's submit button (if I need to fill it first)

If the chat input is visible but at a different position, provide its new coordinates.

Respond with ONLY this JSON:
{"diagnosis": "<what's blocking>", "action": "dismiss_overlay"|"fill_form"|"click_button"|"new_input_position"|"widget_closed"|"unknown", "click": {"x": <number>, "y": <number>} or null, "form_fields": ["email", "name"] or null}""",
    )

    if not result:
        await _log("generic_chat: vision recovery got no result")
        return None

    await _log(f"generic_chat: vision diagnosis: {result.get('diagnosis', 'unknown')}")
    action = result.get("action", "unknown")

    if action == "dismiss_overlay" and result.get("click"):
        coords = result["click"]
        await _log(f"generic_chat: dismissing overlay at ({coords['x']}, {coords['y']})")
        await page.mouse.click(coords["x"], coords["y"])
        await asyncio.sleep(2)

    elif action == "fill_form":
        await _log("generic_chat: filling blocking form via JS")
        await _fill_blocking_form(page, _log)
        await asyncio.sleep(2)

    elif action == "click_button" and result.get("click"):
        coords = result["click"]
        await _log(f"generic_chat: clicking button at ({coords['x']}, {coords['y']})")
        await page.mouse.click(coords["x"], coords["y"])
        await asyncio.sleep(2)

    elif action == "new_input_position" and result.get("click"):
        coords = result["click"]
        return ChatTarget(
            input_selector=None,
            input_coordinates=(coords["x"], coords["y"]),
            description=f"Relocated input at ({coords['x']}, {coords['y']})",
            method="coordinates",
        )

    else:
        await _log(f"generic_chat: vision recovery action '{action}' not actionable")
        return None

    # After taking the recovery action, re-locate the input
    from scanner.vision_navigator import _locate_input
    new_screenshot = await _take_screenshot(page)
    return await _locate_input(page, anthropic_client, new_screenshot, _log)


async def _fill_blocking_form(page: Page, _log: Callable):
    """Fill any visible form that might be blocking the chat input."""
    result = await page.evaluate("""
        (() => {
            const results = [];

            function fillInRoot(root) {
                // Email
                const emails = root.querySelectorAll('input[type="email"], input[name*="email"], input[placeholder*="email"], input[placeholder*="Email"]');
                for (const input of emails) {
                    input.value = 'test@scanner.local';
                    input.dispatchEvent(new Event('input', {bubbles: true}));
                    input.dispatchEvent(new Event('change', {bubbles: true}));
                    results.push('filled_email');
                }
                // Name
                const names = root.querySelectorAll('input[name*="name"], input[placeholder*="name"], input[placeholder*="Name"]');
                for (const input of names) {
                    input.value = 'Security Tester';
                    input.dispatchEvent(new Event('input', {bubbles: true}));
                    input.dispatchEvent(new Event('change', {bubbles: true}));
                    results.push('filled_name');
                }
                // Checkboxes
                const cbs = root.querySelectorAll('input[type="checkbox"]');
                for (const cb of cbs) { if (!cb.checked) cb.click(); results.push('checked'); }
                // Submit
                const buttons = [...root.querySelectorAll('button, input[type="submit"]')];
                const submitBtn = buttons.find(b => /send|submit|start|continue|begin|next|skip/i.test(b.textContent?.trim() || b.value?.trim() || ''));
                if (submitBtn) { submitBtn.click(); results.push('clicked_submit'); }
            }

            fillInRoot(document);
            document.querySelectorAll('*').forEach(el => {
                if (el.shadowRoot) fillInRoot(el.shadowRoot);
            });

            return JSON.stringify(results);
        })()
    """)
    await _log(f"generic_chat: form fill result: {result}")


async def read_latest_response(
    page: Page,
    debug_cb: Optional[Callable[[str], Awaitable[None]]] = None,
) -> tuple[Optional[str], int]:
    """Read the latest bot response from the chat widget.

    Returns (text, message_count).
    """
    read_script = """
        (() => {
            function findMessagesInRoot(root) {
                const selectors = [
                    '[class*="message"]', '[class*="bubble"]', '[class*="response"]',
                    '[data-role="assistant"]', '[class*="bot-"]', '[class*="agent-"]',
                    '[data-testid*="message"]', '[class*="chat-text"]',
                    '[class*="Message"]', '[class*="Bubble"]',
                    '[class*="reply"]', '[class*="Reply"]',
                    '[class*="answer"]', '[class*="Answer"]',
                ];

                let allMessages = [];
                for (const sel of selectors) {
                    const msgs = root.querySelectorAll(sel);
                    if (msgs.length > 0) {
                        allMessages = [...msgs];
                        break;
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


async def _read_response_via_vision(
    page: Page,
    anthropic_client: anthropic.AsyncAnthropic,
    sent_message: str,
    _log: Callable,
) -> Optional[str]:
    """Use Claude vision to read the chatbot's response from a screenshot."""
    screenshot_b64 = await _take_screenshot(page)
    result = await _ask_claude(
        anthropic_client,
        screenshot_b64,
        f"""CONTEXT: I just sent this message to a chatbot on this webpage: "{sent_message[:100]}"

TASK: Look at the chat widget in the screenshot. Read the chatbot's most recent response message.

The chatbot's response is typically:
- In a message bubble or text block ABOVE the input field
- Styled differently from the user's message (different color, alignment, or avatar)
- The LAST/MOST RECENT message from the bot, not older messages

If you can see the chatbot's response, extract the FULL TEXT of that response.
If the chatbot hasn't responded yet (still loading/typing), say so.
If there is no visible response, say so.

Respond with ONLY this JSON:
{{"response_text": "<the chatbot's full response text>" or null, "status": "responded"|"typing"|"no_response", "description": "<what you see>"}}""",
    )

    if not result:
        await _log("vision_read: got no result from Claude")
        return None

    status = result.get("status", "no_response")
    await _log(f"vision_read: status={status}, desc={result.get('description', '')[:60]}")

    if status == "responded" and result.get("response_text"):
        return result["response_text"]

    return None


async def send_and_read(
    page: Page,
    message: str,
    chat_target: ChatTarget,
    anthropic_client: Optional[anthropic.AsyncAnthropic] = None,
    debug_cb: Optional[Callable[[str], Awaitable[None]]] = None,
    timeout_ms: int = 15000,
) -> Optional[str]:
    """Send a message and wait for the bot response.

    Uses DOM polling first (fast, free). If DOM polling finds nothing after
    the timeout, falls back to vision-based reading (screenshot + Claude).
    """
    async def _log(msg: str):
        if debug_cb:
            await debug_cb(msg)

    # Get baseline
    text_before, count_before = await read_latest_response(page)
    await _log(f"generic_chat: {count_before} msgs before, text_before={repr(text_before[:40]) if text_before else None}")

    # Send
    sent = await send_message(page, message, chat_target, anthropic_client=anthropic_client, debug_cb=debug_cb)
    if not sent:
        return None

    # Phase 1: DOM polling (fast, free)
    poll_interval_ms = 500
    max_polls = timeout_ms // poll_interval_ms
    last_text = None
    stable_count = 0

    for poll_num in range(max_polls):
        await asyncio.sleep(poll_interval_ms / 1000)
        current_text, current_count = await read_latest_response(page)

        if poll_num % 10 == 0:
            await _log(f"generic_chat: poll {poll_num}/{max_polls} — count={current_count}, text={repr(current_text[:50]) if current_text else None}")

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
                    await _log(f"generic_chat: response stable after {poll_num} polls (DOM)")
                    return current_text
            else:
                stable_count = 0
                last_text = current_text

    # Phase 2: Vision fallback — DOM couldn't read the response, ask Claude to read the screenshot
    if anthropic_client:
        await _log("generic_chat: DOM polling found nothing. Trying vision-based reading...")
        # Wait a bit more for any slow responses to finish rendering
        await asyncio.sleep(3)
        vision_text = await _read_response_via_vision(page, anthropic_client, message, _log)
        if vision_text:
            await _log(f"generic_chat: vision read response: {repr(vision_text[:60])}")
            return vision_text

    await _log(f"generic_chat: no response found (DOM + vision). last_text={repr(last_text[:50]) if last_text else None}")
    return last_text
