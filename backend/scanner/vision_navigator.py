"""Vision-guided widget navigator — uses Claude screenshots to find and open chat widgets.

Instead of brittle platform-specific selectors, this module:
1. Takes screenshots at each step
2. Sends them to Claude Sonnet for analysis
3. Follows Claude's instructions to click, fill forms, and locate the chat input
4. Returns a ChatTarget with enough info to send messages
"""

import asyncio
import base64
import json
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable

import anthropic
from playwright.async_api import Page


@dataclass
class ChatTarget:
    """Describes a located chat input, ready for message sending."""
    input_selector: Optional[str]  # CSS selector if we found one
    input_coordinates: Optional[tuple[int, int]]  # (x, y) fallback
    description: str  # What Claude saw
    method: str  # "selector" or "coordinates"


async def navigate_to_chat(
    page: Page,
    anthropic_client: anthropic.AsyncAnthropic,
    debug_cb: Optional[Callable[[str], Awaitable[None]]] = None,
    max_steps: int = 5,
) -> Optional[ChatTarget]:
    """Use Claude vision to find, open, and prepare a chat widget for interaction.

    Returns a ChatTarget if successful, None if no widget found.
    """
    async def _log(msg: str):
        if debug_cb:
            await debug_cb(msg)

    for step in range(max_steps):
        await _log(f"vision step {step + 1}/{max_steps}: taking screenshot")
        screenshot_b64 = await _take_screenshot(page)

        if step == 0:
            # Step 1: Find the chat widget
            result = await _ask_claude(
                anthropic_client,
                screenshot_b64,
                """CONTEXT: I am scanning websites for AI chatbot widgets to test their security. I need to find and interact with conversational AI chatbots — surfaces where a user types natural language messages and gets AI/agent responses.

TASK: Analyze this screenshot and determine if there is an AI chatbot widget on the page and what state it is in.

WHAT COUNTS as a chatbot: floating chat bubbles/icons, embedded chat panels, AI assistant widgets, customer support chat, live chat with AI.
WHAT DOES NOT COUNT: search bars, contact forms, newsletter signups, feedback ratings, social links, login forms.

The widget can be in one of four states:

1. "not_found" — No chatbot widget visible anywhere on the page.

2. "closed" — A small launcher button or icon is visible (typically a chat bubble in a corner), but the chat panel is NOT open. I need to click this button to open it.

3. "menu" — The chat panel is open and visible, but it is showing a HOME SCREEN, MENU, or LIST OF OPTIONS (clickable buttons/cards like "Chat with us", "Help Center", "Talk to agent", FAQ links, etc.). There is NO free-text input field visible. I need to click one of these menu items to navigate to the actual conversation view.

4. "open" — The chat panel is open AND showing a CONVERSATION VIEW with a visible TEXT INPUT FIELD. The input field is a textarea or text box with a placeholder like "Type your message...", "Type here...", "Ask a question...". This is where I can type free-form messages. ONLY use this state if you can clearly see a text input field for typing messages.

CRITICAL: A panel showing clickable buttons, cards, or navigation options is state "menu", NOT "open". Only set state="open" and has_input=true when you see an actual text input field for typing messages.

ACTION: If state is "closed", provide click coordinates to open the launcher. If state is "menu", provide click coordinates of the option most likely to start a conversation (look for words like "Chat", "Talk", "Ask", "Message", "Conversation", "Support" — avoid "FAQ", "Help Center", "Documentation", "Pricing").

Respond with ONLY this JSON:
{"found": true/false, "state": "open"|"closed"|"menu"|"not_found", "click": {"x": <number>, "y": <number>} or null, "has_input": true/false, "widget_location": {"region": "bottom-right"|"bottom-left"|"right-panel"|"center"|"other", "bounding_box": {"x": <top-left-x>, "y": <top-left-y>, "width": <px>, "height": <px>}}, "description": "<what you see>"}""",
            )
            await _log(f"vision step 1 result: {json.dumps(result)}")

            if not result or not result.get("found"):
                await _log("vision: no chat widget found")
                return None

            state = result.get("state", "not_found")

            if state == "open" and result.get("has_input"):
                # Widget is open with input visible — locate it
                return await _locate_input(page, anthropic_client, screenshot_b64, _log)

            if state in ("closed", "menu") and result.get("click"):
                action = "launcher" if state == "closed" else "menu item"
                coords = result["click"]
                await _log(f"vision: clicking {action} at ({coords['x']}, {coords['y']})")
                await page.mouse.click(coords["x"], coords["y"])
                await asyncio.sleep(3)
                continue  # Re-screenshot after clicking

            if state == "not_found":
                await _log("vision: no chat widget found")
                return None

        else:
            # Subsequent steps: check what's on screen now
            result = await _ask_claude(
                anthropic_client,
                screenshot_b64,
                """CONTEXT: I am navigating an AI chatbot widget on a website. I just clicked something and need to determine the current state.

TASK: Analyze this screenshot and tell me what I see in the chat widget area.

Choose the BEST match:

A) CONVERSATION VIEW READY — I can see a TEXT INPUT FIELD (textarea/input box) where I can type free-form messages. The input has a placeholder like "Type your message...", "Ask a question...", or similar. There may be message bubbles above it. THE CHAT IS READY TO USE.

B) PRE-CHAT FORM — Before I can chat, I need to fill out a form (email, name, phone, etc.). There may be a consent/GDPR checkbox and a "Send" or "Submit" button. This is NOT a text input for chatting — it's a data collection form.

C) MENU / HOME SCREEN — The chat panel shows a list of clickable options, buttons, or cards (e.g., topics, FAQs, department selection, "Chat with support", "Ask AI"). There is NO free-text input field visible. I need to click one of these to proceed to the conversation.

D) CLOSED / NEEDS CLICK — The widget is still closed/minimized, or I need to click something else to proceed.

E) NO CHATBOT — No chat widget visible on the page.

CRITICAL DISTINCTION between A and C:
- If you see BUTTONS/CARDS to click → that's C (menu), even if the panel looks like a chat widget
- If you see a TEXT FIELD where I can TYPE characters → that's A (ready)
- A text input field typically has a blinking cursor, placeholder text, and sits at the bottom of the widget

ACTION:
- If B: list the form fields visible
- If C: give pixel coordinates of the option most likely to start a CONVERSATION (prefer "Chat", "Talk", "Ask", "Message" — avoid "FAQ", "Help Center", "Docs")
- If D: give pixel coordinates to click

Respond with ONLY this JSON:
{"status": "A"|"B"|"C"|"D"|"E", "click": {"x": <number>, "y": <number>} or null, "form_fields": ["email", "name", "checkbox", etc.] or null, "widget_bounds": {"x": <top-left-x>, "y": <top-left-y>, "width": <px>, "height": <px>}, "description": "<what you see>"}""",
            )
            await _log(f"vision step {step + 1} result: {json.dumps(result)}")

            if not result:
                continue

            status = result.get("status", "E")

            if status == "A":
                # Chat input found
                return await _locate_input(page, anthropic_client, screenshot_b64, _log)

            elif status == "B":
                # Pre-chat form — fill it
                await _log("vision: filling pre-chat form")
                await _fill_form_generic(page, result.get("form_fields", []), _log)
                await asyncio.sleep(3)
                continue

            elif status in ("C", "D"):
                # Need to click something
                if result.get("click"):
                    coords = result["click"]
                    await _log(f"vision: clicking at ({coords['x']}, {coords['y']})")
                    await page.mouse.click(coords["x"], coords["y"])
                    await asyncio.sleep(3)
                    continue

            elif status == "E":
                await _log("vision: no chat widget visible")
                return None

    await _log(f"vision: exhausted {max_steps} steps without finding chat input")
    return None


async def _locate_input(
    page: Page,
    anthropic_client: anthropic.AsyncAnthropic,
    screenshot_b64: str,
    _log: Callable,
) -> Optional[ChatTarget]:
    """Once we know a chat input is visible, find it precisely."""

    # First try DOM inspection — look for visible textareas/inputs
    dom_result = await page.evaluate("""
        (() => {
            // Check regular DOM
            const candidates = document.querySelectorAll('textarea, input[type="text"], [contenteditable="true"]');
            const visible = [...candidates].filter(el => {
                const rect = el.getBoundingClientRect();
                return rect.width > 30 && rect.height > 15 && el.offsetParent !== null;
            });

            // Also check shadow DOMs
            const shadowHosts = document.querySelectorAll('*');
            for (const host of shadowHosts) {
                if (host.shadowRoot) {
                    const shadowCandidates = host.shadowRoot.querySelectorAll('textarea, input[type="text"], [contenteditable="true"]');
                    const shadowVisible = [...shadowCandidates].filter(el => {
                        const rect = el.getBoundingClientRect();
                        return rect.width > 30 && rect.height > 15;
                    });
                    for (const el of shadowVisible) {
                        visible.push(el);
                    }
                }
            }

            if (visible.length === 0) return JSON.stringify({found: false});

            // Pick the best candidate — prefer ones with chat-related placeholders
            let best = visible[0];
            for (const el of visible) {
                const placeholder = (el.placeholder || el.getAttribute('aria-label') || '').toLowerCase();
                if (/message|chat|type|ask|write/.test(placeholder)) {
                    best = el;
                    break;
                }
            }

            const rect = best.getBoundingClientRect();
            return JSON.stringify({
                found: true,
                tag: best.tagName,
                id: best.id || null,
                placeholder: best.placeholder || best.getAttribute('aria-label') || '',
                rect: {x: Math.round(rect.x + rect.width/2), y: Math.round(rect.y + rect.height/2), w: Math.round(rect.width), h: Math.round(rect.height)},
                inShadowDom: best.getRootNode() !== document,
            });
        })()
    """)

    try:
        info = json.loads(dom_result)
    except Exception:
        info = {"found": False}

    if info.get("found"):
        await _log(f"vision: found input via DOM — {info['tag']} placeholder='{info.get('placeholder', '')}' at ({info['rect']['x']}, {info['rect']['y']})")

        # Build a selector if possible
        selector = None
        if info.get("id"):
            selector = f"#{info['id']}"
        elif info.get("placeholder"):
            selector = f"{info['tag'].lower()}[placeholder*=\"{info['placeholder'][:20]}\"]"

        if info.get("inShadowDom"):
            # Can't use CSS selectors for shadow DOM — use coordinates
            return ChatTarget(
                input_selector=None,
                input_coordinates=(info["rect"]["x"], info["rect"]["y"]),
                description=f"Shadow DOM {info['tag']} with placeholder '{info.get('placeholder', '')}'",
                method="coordinates",
            )

        return ChatTarget(
            input_selector=selector,
            input_coordinates=(info["rect"]["x"], info["rect"]["y"]),
            description=f"{info['tag']} with placeholder '{info.get('placeholder', '')}'",
            method="selector" if selector else "coordinates",
        )

    # DOM inspection failed — ask Claude for coordinates
    await _log("vision: DOM inspection found no input, asking Claude for coordinates")
    result = await _ask_claude(
        anthropic_client,
        screenshot_b64,
        """I need to find the exact position of the chat message input field.
Look at the chat widget and find the text input area where I would type a message.

What are the pixel coordinates of the CENTER of the input field?

Respond with ONLY this JSON:
{"found": true/false, "x": <number>, "y": <number>, "description": "<what the input looks like>"}""",
    )

    if result and result.get("found"):
        await _log(f"vision: Claude located input at ({result['x']}, {result['y']})")
        return ChatTarget(
            input_selector=None,
            input_coordinates=(result["x"], result["y"]),
            description=result.get("description", ""),
            method="coordinates",
        )

    await _log("vision: could not locate chat input")
    return None


async def _fill_form_generic(page: Page, fields: list[str], _log: Callable):
    """Fill a pre-chat form using common patterns."""
    await _log(f"vision: filling form fields: {fields}")

    fill_script = """
        (() => {
            const results = [];

            // Helper to fill in both regular DOM and shadow DOMs
            function fillInRoot(root) {
                // Email fields
                const emails = root.querySelectorAll('input[type="email"], input[name*="email"], input[placeholder*="email"], input[placeholder*="Email"]');
                for (const input of emails) {
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
                    if (setter) setter.call(input, 'test@scanner.local');
                    else input.value = 'test@scanner.local';
                    input.dispatchEvent(new Event('input', {bubbles: true}));
                    input.dispatchEvent(new Event('change', {bubbles: true}));
                    results.push('filled_email');
                }

                // Name fields
                const names = root.querySelectorAll('input[name*="name"], input[placeholder*="name"], input[placeholder*="Name"]');
                for (const input of names) {
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
                    if (setter) setter.call(input, 'Security Tester');
                    else input.value = 'Security Tester';
                    input.dispatchEvent(new Event('input', {bubbles: true}));
                    input.dispatchEvent(new Event('change', {bubbles: true}));
                    results.push('filled_name');
                }

                // Checkboxes — check them all
                const checkboxes = root.querySelectorAll('input[type="checkbox"]');
                for (const cb of checkboxes) {
                    if (!cb.checked) cb.click();
                    results.push('checked_checkbox');
                }

                // Click submit/send button
                const buttons = [...root.querySelectorAll('button, input[type="submit"]')];
                const submitBtn = buttons.find(b => /send|submit|start|continue|begin|next/i.test(b.textContent?.trim() || b.value?.trim() || ''));
                if (submitBtn) {
                    submitBtn.click();
                    results.push('clicked_submit:' + (submitBtn.textContent?.trim().substring(0, 20) || 'button'));
                }
            }

            // Fill in regular DOM
            fillInRoot(document);

            // Fill in shadow DOMs
            const allElements = document.querySelectorAll('*');
            for (const el of allElements) {
                if (el.shadowRoot) {
                    fillInRoot(el.shadowRoot);
                }
            }

            return JSON.stringify(results);
        })()
    """

    try:
        result = await page.evaluate(fill_script)
        await _log(f"vision: form fill result: {result}")
    except Exception as e:
        await _log(f"vision: form fill failed: {e}")


async def _take_screenshot(page: Page) -> str:
    """Take a screenshot and return as base64."""
    screenshot_bytes = await page.screenshot(type="png")
    return base64.b64encode(screenshot_bytes).decode("utf-8")


async def _ask_claude(
    client: anthropic.AsyncAnthropic,
    screenshot_b64: str,
    prompt: str,
) -> Optional[dict]:
    """Send a screenshot to Claude and get structured JSON back."""
    try:
        message = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": screenshot_b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )

        raw = message.content[0].text.strip()
        # Strip markdown code blocks if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            raw = raw.rsplit("```", 1)[0]
            raw = raw.strip()

        return json.loads(raw)
    except Exception:
        return None
