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
                """Look at this webpage screenshot carefully. I am looking for an AI chatbot or conversational assistant — a surface where a user can type natural language messages and get responses from an AI or live agent.

What I AM looking for:
- AI chatbot widgets (e.g., "Chat with us", "Ask AI", customer support bots)
- Floating chat bubbles/icons in corners (usually bottom-right) that open a conversational interface
- Embedded chat panels with a message input and conversation history
- AI assistants branded as Intercom Fin, Tidio Lyro, Zendesk AI, Drift, Crisp, HubSpot, LiveChat, or similar

What I am NOT looking for:
- Search bars or site search
- Contact forms (name/email/message forms that submit once, not conversational)
- Newsletter signup forms
- Feedback widgets ("Rate your experience")
- Social media links or share buttons
- Login forms

Is there a CONVERSATIONAL AI CHATBOT on this page?

1. If yes, is it OPEN (showing a conversation view with a message input where I can type and send messages back and forth) or CLOSED (just a launcher button/icon I need to click first)?
2. If closed, what are the exact pixel coordinates (x, y) of the center of the launcher button?
3. If open, is there a text input field where I can type a message?

Respond with ONLY this JSON:
{"found": true/false, "state": "open"|"closed"|"not_found", "click": {"x": <number>, "y": <number>} or null, "has_input": true/false, "widget_location": {"region": "bottom-right"|"bottom-left"|"right-panel"|"center"|"other", "bounding_box": {"x": <top-left-x>, "y": <top-left-y>, "width": <px>, "height": <px>}}, "description": "<what you see>"}""",
            )
            await _log(f"vision step 1 result: {json.dumps(result)}")

            if not result or not result.get("found"):
                await _log("vision: no chat widget found")
                return None

            if result.get("has_input"):
                # Widget is already open with input visible
                return await _locate_input(page, anthropic_client, screenshot_b64, _log)

            if result.get("state") == "closed" and result.get("click"):
                coords = result["click"]
                await _log(f"vision: clicking widget launcher at ({coords['x']}, {coords['y']})")
                await page.mouse.click(coords["x"], coords["y"])
                await asyncio.sleep(3)
                continue  # Re-screenshot after clicking

        else:
            # Subsequent steps: check what's on screen now
            result = await _ask_claude(
                anthropic_client,
                screenshot_b64,
                """Look at this webpage screenshot. I clicked on what I thought was an AI chatbot launcher. I need to get to a state where I can type natural language messages to the chatbot and receive responses.

What do you see now? Choose the BEST match:

A) A CONVERSATION VIEW with a text input field where I can type a message and send it to the chatbot. This looks like a chat interface with message bubbles or a conversation log, and a textarea/input at the bottom to type. THE CHAT IS READY TO USE.

B) A PRE-CHAT FORM asking for my email address, name, phone number, or other personal info BEFORE I can start chatting. There may be a consent checkbox and a "Send" or "Submit" button.

C) A MENU or HOME SCREEN inside the chat widget. This shows options like "Chat with Lyro", "Talk to an agent", "Help Center", "FAQs", etc. I need to click one of these options to navigate into the actual conversation. Tell me the pixel coordinates of the option that will start a CONVERSATION with the AI chatbot (not FAQs or help center).

D) The chat widget is still CLOSED or minimized. I see a button or icon I need to click to open it. Give me the coordinates.

E) NO CHATBOT visible anywhere on the page.

If B: list the form fields visible (email, name, checkbox, etc.)
If C: give the pixel coordinates of the button to click to START A CONVERSATION (prefer "Chat with..." or "Talk to..." options over "Help Center" or "FAQs")
If D: give the pixel coordinates of the launcher button

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
