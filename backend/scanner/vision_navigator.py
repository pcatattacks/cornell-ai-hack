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
    input_selector: Optional[str]  # CSS selector within the target frame
    input_coordinates: Optional[tuple[int, int]]  # (x, y) fallback
    frame_index: Optional[int]  # index into page.frames (None or 0 = main frame)
    frame_url: Optional[str]  # iframe src for debugging
    description: str  # What Claude saw
    method: str  # "selector" | "coordinates" | "tab"


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
                bounds = result.get("widget_location", {}).get("bounding_box")
                return await _locate_input(page, anthropic_client, screenshot_b64, _log, widget_bounds=bounds)

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
                bounds = result.get("widget_bounds")
                return await _locate_input(page, anthropic_client, screenshot_b64, _log, widget_bounds=bounds)

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
    widget_bounds: Optional[dict] = None,
) -> Optional[ChatTarget]:
    """Find the chat input precisely using exhaustive DOM search across all frames.

    Strategy:
    1. Search ALL frames (main + iframes) and shadow roots for input elements
    2. Filter by widget bounds proximity
    3. If multiple candidates, ask Claude to pick the chat input
    4. If zero candidates, try Tab-cycling fallback
    """
    # Step 1: Exhaustive search across all frames
    candidates = await _find_all_inputs(page, _log)
    await _log(f"locate_input: found {len(candidates)} input candidates across {len(page.frames)} frames")

    if not candidates:
        # Tab-cycling fallback
        await _log("locate_input: no candidates found, trying Tab cycling")
        tab_result = await _tab_to_input(page, widget_bounds, _log)
        if tab_result:
            return tab_result
        await _log("locate_input: Tab cycling failed too")
        return None

    # Step 2: Filter by widget bounds if available
    if widget_bounds:
        filtered = _filter_by_bounds(candidates, widget_bounds)
        await _log(f"locate_input: {len(filtered)} candidates after bounds filter (from {len(candidates)})")
        if filtered:
            candidates = filtered

    # Step 3: Pick the right input
    if len(candidates) == 1:
        selected = candidates[0]
        await _log(f"locate_input: single candidate — {selected['tag']} placeholder='{selected['placeholder']}' frame={selected['frame_index']}")
    else:
        selected = await _pick_chat_input(candidates, anthropic_client, _log)
        if not selected:
            selected = candidates[0]  # fallback to first

    # Step 4: Build ChatTarget
    selector = _build_selector(selected)
    return ChatTarget(
        input_selector=selector,
        input_coordinates=(selected["cx"], selected["cy"]),
        frame_index=selected["frame_index"],
        frame_url=selected.get("frame_url"),
        description=f"{selected['tag']} placeholder='{selected['placeholder']}' in frame {selected['frame_index']}",
        method="selector" if selector else "coordinates",
    )


async def _find_all_inputs(page: Page, _log: Callable) -> list[dict]:
    """Search ALL frames (main + iframes) and shadow roots for text input elements."""
    candidates = []

    SEARCH_JS = """
        (() => {
            function searchRoot(root) {
                const found = [];
                const els = root.querySelectorAll('textarea, input[type="text"], input:not([type]), [contenteditable="true"]');
                for (const el of els) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width < 20 || rect.height < 10) continue;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;
                    // Skip inputs that are clearly not chat (password, hidden, etc.)
                    if (el.type && ['password', 'hidden', 'submit', 'button', 'checkbox', 'radio', 'file'].includes(el.type)) continue;
                    found.push({
                        tag: el.tagName,
                        id: el.id || null,
                        name: el.name || null,
                        placeholder: el.placeholder || el.getAttribute('aria-label') || '',
                        type: el.type || null,
                        rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) },
                        cx: Math.round(rect.x + rect.width / 2),
                        cy: Math.round(rect.y + rect.height / 2),
                    });
                }
                // Check shadow roots
                const allEls = root.querySelectorAll('*');
                for (const host of allEls) {
                    if (host.shadowRoot) {
                        found.push(...searchRoot(host.shadowRoot));
                    }
                }
                return found;
            }
            return JSON.stringify(searchRoot(document));
        })()
    """

    for frame_idx, frame in enumerate(page.frames):
        try:
            raw = await frame.evaluate(SEARCH_JS)
            frame_candidates = json.loads(raw)
            for c in frame_candidates:
                c["frame_index"] = frame_idx
                c["frame_url"] = frame.url
                c["frame_name"] = frame.name or None
            candidates.extend(frame_candidates)
        except Exception:
            continue  # Frame may be cross-origin or detached

    return candidates


def _filter_by_bounds(candidates: list[dict], widget_bounds: dict) -> list[dict]:
    """Filter candidates to those inside or near the widget bounding box."""
    bx = widget_bounds.get("x", 0)
    by = widget_bounds.get("y", 0)
    bw = widget_bounds.get("width", 9999)
    bh = widget_bounds.get("height", 9999)
    margin = 100  # generous tolerance

    filtered = []
    for c in candidates:
        if (bx - margin <= c["cx"] <= bx + bw + margin and
                by - margin <= c["cy"] <= by + bh + margin):
            filtered.append(c)
    return filtered


async def _pick_chat_input(
    candidates: list[dict],
    anthropic_client: anthropic.AsyncAnthropic,
    _log: Callable,
) -> Optional[dict]:
    """Ask Claude to pick which input is the chat message input."""
    desc_lines = []
    for i, c in enumerate(candidates):
        frame_label = f"iframe({c['frame_url'][:40]})" if c["frame_index"] > 0 else "main page"
        desc_lines.append(
            f"[{i}] {c['tag']} placeholder='{c['placeholder']}' id='{c['id']}' "
            f"name='{c['name']}' size={c['rect']['w']}x{c['rect']['h']} "
            f"at ({c['cx']},{c['cy']}) in {frame_label}"
        )
    desc = "\n".join(desc_lines)

    await _log(f"locate_input: asking Claude to pick from {len(candidates)} candidates")

    try:
        message = await anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=50,
            messages=[{
                "role": "user",
                "content": f"""Which of these input elements is the CHAT MESSAGE INPUT for typing messages to an AI chatbot?

{desc}

Consider: chat inputs typically have placeholders like "Type your message", "Compose", "Ask", etc.
Search bars have "Search". Email fields have "email". Login fields have "username/password".

Respond with ONLY the index number (e.g., "2").""",
            }],
        )
        raw = message.content[0].text.strip()
        idx = int(raw)
        if 0 <= idx < len(candidates):
            selected = candidates[idx]
            await _log(f"locate_input: Claude picked [{idx}] — {selected['tag']} placeholder='{selected['placeholder']}'")
            return selected
    except Exception as e:
        await _log(f"locate_input: Claude pick failed: {e}")

    return None


async def _tab_to_input(
    page: Page,
    widget_bounds: Optional[dict],
    _log: Callable,
    max_tabs: int = 20,
) -> Optional[ChatTarget]:
    """Click in widget area then Tab until we focus a text input."""
    # Click in the center of the widget bounds to start
    if widget_bounds:
        cx = widget_bounds.get("x", 640) + widget_bounds.get("width", 200) // 2
        cy = widget_bounds.get("y", 400) + widget_bounds.get("height", 200) // 2
        await page.mouse.click(cx, cy)
        await asyncio.sleep(0.3)

    for i in range(max_tabs):
        await page.keyboard.press("Tab")
        await asyncio.sleep(0.15)

        info = await page.evaluate("""
            (() => {
                const el = document.activeElement;
                if (!el) return null;
                const tag = el.tagName.toLowerCase();
                const isTextInput = (tag === 'textarea' || (tag === 'input' && (!el.type || el.type === 'text' || el.type === 'search')) || el.contentEditable === 'true');
                if (!isTextInput) return null;
                const rect = el.getBoundingClientRect();
                return {
                    tag: el.tagName,
                    id: el.id || null,
                    placeholder: el.placeholder || el.getAttribute('aria-label') || '',
                    cx: Math.round(rect.x + rect.width / 2),
                    cy: Math.round(rect.y + rect.height / 2),
                };
            })()
        """)

        if info:
            await _log(f"locate_input: Tab #{i} focused {info['tag']} placeholder='{info['placeholder']}'")
            selector = _build_selector(info)
            return ChatTarget(
                input_selector=selector,
                input_coordinates=(info["cx"], info["cy"]),
                frame_index=0,  # Tab focuses in the active frame context
                frame_url=None,
                description=f"Tab-focused {info['tag']} placeholder='{info['placeholder']}'",
                method="selector" if selector else "tab",
            )

    return None


def _build_selector(info: dict) -> Optional[str]:
    """Build a CSS selector from candidate info."""
    if info.get("id"):
        return f"#{info['id']}"
    if info.get("placeholder"):
        p = info["placeholder"][:20].replace('"', '\\"')
        tag = info.get("tag", "").lower() or "*"
        return f'{tag}[placeholder*="{p}"]'
    if info.get("name"):
        tag = info.get("tag", "").lower() or "*"
        return f'{tag}[name="{info["name"]}"]'
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
