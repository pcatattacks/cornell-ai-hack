"""Generic chat widget finder using DOM heuristics + Claude vision fallback.

Instead of hardcoded per-platform selectors, this module:
1. Scans the DOM for chat-widget-like patterns (floating elements, chat attributes)
2. If found, returns enough info to interact with it generically
3. If not found, takes a screenshot and asks Claude vision to locate the widget
"""

import asyncio
import base64
import json
from dataclasses import dataclass
from typing import Optional

import anthropic
from playwright.async_api import Page


@dataclass
class GenericWidgetInfo:
    """Describes a discovered chat widget with enough info to interact with it."""
    method: str  # "dom_heuristic" or "vision"
    chat_input_selector: str  # CSS selector for the message input
    chat_container_selector: str  # CSS selector for the message container
    open_action: Optional[str]  # JS to open the widget, or None if already open
    uses_shadow_dom: bool
    shadow_host_selector: Optional[str]
    description: str  # Human-readable description of what was found


# JS that scans the page for chat-widget-like elements
HEURISTIC_DETECTION_JS = """
(() => {
    const results = {
        launchers: [],
        inputs: [],
        containers: [],
        iframes: [],
        shadow_hosts: [],
    };

    // 1. Find floating elements in bottom-right (typical chat launcher position)
    const allElements = document.querySelectorAll('*');
    for (const el of allElements) {
        const style = window.getComputedStyle(el);
        if (style.position === 'fixed' && style.zIndex > 100) {
            const rect = el.getBoundingClientRect();
            // Bottom-right quadrant, reasonable size for a chat widget
            if (rect.bottom > window.innerHeight * 0.6 && rect.right > window.innerWidth * 0.5) {
                const attrs = {
                    tag: el.tagName,
                    id: el.id || '',
                    class: (el.className?.toString() || '').substring(0, 100),
                    ariaLabel: el.getAttribute('aria-label') || '',
                    role: el.getAttribute('role') || '',
                    rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) },
                    hasShadowRoot: !!el.shadowRoot,
                    childCount: el.children.length,
                };

                // Check for chat-related text/attributes
                const text = (el.id + ' ' + el.className + ' ' + (el.getAttribute('aria-label') || '')).toLowerCase();
                const isChatLike = /chat|messag|support|help|assist|bot|widget|intercom|tidio|zendesk|crisp|drift|livechat|hubspot/.test(text);

                if (isChatLike || rect.width > 40) {
                    attrs.isChatLike = isChatLike;
                    results.launchers.push(attrs);
                }

                // Check if this element has a shadow root with chat-like content
                if (el.shadowRoot) {
                    const shadowInputs = el.shadowRoot.querySelectorAll('textarea, input[type="text"], [contenteditable="true"]');
                    const shadowMessages = el.shadowRoot.querySelectorAll('[class*="message"], [data-testid*="message"], [class*="bubble"]');
                    if (shadowInputs.length > 0 || shadowMessages.length > 0) {
                        results.shadow_hosts.push({
                            selector: el.id ? '#' + el.id : el.tagName.toLowerCase() + '.' + el.className?.toString().split(' ')[0],
                            inputCount: shadowInputs.length,
                            messageCount: shadowMessages.length,
                            inputSelectors: [...shadowInputs].map(i => i.tagName.toLowerCase() + (i.getAttribute('data-testid') ? '[data-testid="' + i.getAttribute('data-testid') + '"]' : '')),
                        });
                    }
                }
            }
        }
    }

    // 2. Find visible textareas/inputs that look like chat inputs
    const inputs = document.querySelectorAll('textarea, input[type="text"], [contenteditable="true"]');
    for (const input of inputs) {
        if (input.offsetParent === null) continue; // skip hidden
        const rect = input.getBoundingClientRect();
        if (rect.width < 50 || rect.height < 20) continue; // skip tiny
        const placeholder = input.getAttribute('placeholder') || '';
        const ariaLabel = input.getAttribute('aria-label') || '';
        const text = (placeholder + ' ' + ariaLabel + ' ' + input.id + ' ' + input.className).toLowerCase();
        if (/message|chat|ask|type|write|send|question|help/.test(text)) {
            results.inputs.push({
                tag: input.tagName,
                id: input.id || '',
                class: (input.className?.toString() || '').substring(0, 80),
                placeholder: placeholder.substring(0, 60),
                rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) },
            });
        }
    }

    // 3. Find chat-related iframes
    const iframes = document.querySelectorAll('iframe');
    for (const iframe of iframes) {
        const src = iframe.src || '';
        const id = iframe.id || '';
        const name = iframe.name || '';
        const title = iframe.title || '';
        const text = (src + ' ' + id + ' ' + name + ' ' + title).toLowerCase();
        if (/chat|messag|support|widget|intercom|tidio|zendesk|crisp|drift|livechat|hubspot/.test(text)) {
            results.iframes.push({
                id: id,
                name: name,
                title: title,
                src: src.substring(0, 100),
                rect: iframe.getBoundingClientRect(),
            });
        }
    }

    return JSON.stringify(results);
})()
"""


async def find_widget_heuristic(page: Page) -> Optional[GenericWidgetInfo]:
    """Use DOM heuristics to find a chat widget."""
    try:
        raw = await page.evaluate(HEURISTIC_DETECTION_JS)
        results = json.loads(raw)
    except Exception:
        return None

    # Check shadow DOM hosts first (e.g., Tidio)
    if results["shadow_hosts"]:
        host = results["shadow_hosts"][0]
        input_sel = host["inputSelectors"][0] if host["inputSelectors"] else "textarea"
        return GenericWidgetInfo(
            method="dom_heuristic",
            chat_input_selector=input_sel,
            chat_container_selector='[class*="message"], [data-testid*="message"]',
            open_action=None,
            uses_shadow_dom=True,
            shadow_host_selector=host["selector"],
            description=f"Shadow DOM widget at {host['selector']} ({host['inputCount']} inputs, {host['messageCount']} messages)",
        )

    # Check chat-like inputs on the page
    if results["inputs"]:
        inp = results["inputs"][0]
        sel = f"#{inp['id']}" if inp["id"] else f"{inp['tag'].lower()}[placeholder*=\"{inp['placeholder'][:20]}\"]" if inp["placeholder"] else f"{inp['tag'].lower()}"
        return GenericWidgetInfo(
            method="dom_heuristic",
            chat_input_selector=sel,
            chat_container_selector='[class*="message"], [data-role="assistant"], [class*="bubble"], [class*="response"]',
            open_action=None,
            uses_shadow_dom=False,
            shadow_host_selector=None,
            description=f"Chat input found: {inp['tag']} placeholder='{inp['placeholder']}'",
        )

    # Check chat-related iframes
    if results["iframes"]:
        iframe = results["iframes"][0]
        iframe_sel = f"iframe#{iframe['id']}" if iframe["id"] else f"iframe[name='{iframe['name']}']" if iframe["name"] else f"iframe[title*='{iframe['title'][:20]}']"
        return GenericWidgetInfo(
            method="dom_heuristic",
            chat_input_selector="textarea, input[type='text'], [contenteditable='true']",
            chat_container_selector='[class*="message"], [class*="bubble"], [class*="response"]',
            open_action=None,
            uses_shadow_dom=False,
            shadow_host_selector=None,
            description=f"Chat iframe found: {iframe_sel} (src: {iframe['src'][:50]})",
        )

    # Check chat-like launchers (might need clicking to open)
    chat_launchers = [l for l in results["launchers"] if l.get("isChatLike")]
    if chat_launchers:
        launcher = chat_launchers[0]
        launcher_sel = f"#{launcher['id']}" if launcher["id"] else f"[aria-label='{launcher['ariaLabel']}']" if launcher["ariaLabel"] else None
        if launcher_sel:
            return GenericWidgetInfo(
                method="dom_heuristic",
                chat_input_selector="textarea, input[type='text'], [contenteditable='true']",
                chat_container_selector='[class*="message"], [class*="bubble"]',
                open_action=f"document.querySelector('{launcher_sel}')?.click()",
                uses_shadow_dom=launcher.get("hasShadowRoot", False),
                shadow_host_selector=launcher_sel if launcher.get("hasShadowRoot") else None,
                description=f"Chat launcher found: {launcher['tag']} {launcher_sel}",
            )

    return None


async def find_widget_vision(
    page: Page,
    anthropic_client: anthropic.AsyncAnthropic,
) -> Optional[GenericWidgetInfo]:
    """Use Claude vision to find a chat widget from a screenshot."""
    screenshot_bytes = await page.screenshot(type="png")
    screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")

    message = await anthropic_client.messages.create(
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
                {
                    "type": "text",
                    "text": """Look at this webpage screenshot. Is there a chat widget, chatbot, or support chat visible?

If yes, respond with JSON:
{"found": true, "description": "what you see", "location": "bottom-right corner" or similar, "is_open": true/false, "has_input_field": true/false}

If no chat widget is visible, respond with:
{"found": false, "description": "no chat widget visible"}

Respond with ONLY the JSON object.""",
                },
            ],
        }],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        result = json.loads(raw)
    except Exception:
        return None

    if not result.get("found"):
        return None

    # If widget found but not open, we need to click the launcher
    # Use a second vision call to get click coordinates
    if not result.get("is_open", False):
        click_msg = await anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
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
                    {
                        "type": "text",
                        "text": f"I see a chat widget that is {result['description']}. What pixel coordinates (x, y) should I click to open it? The image is the full browser viewport. Respond with ONLY JSON: {{\"x\": number, \"y\": number}}",
                    },
                ],
            }],
        )
        click_raw = click_msg.content[0].text.strip()
        if click_raw.startswith("```"):
            click_raw = click_raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        try:
            coords = json.loads(click_raw)
            await page.mouse.click(coords["x"], coords["y"])
            await asyncio.sleep(2)
        except Exception:
            pass

    # After potentially opening it, try DOM heuristics again
    heuristic_result = await find_widget_heuristic(page)
    if heuristic_result:
        heuristic_result.method = "vision+heuristic"
        return heuristic_result

    # Fallback: return a generic config and hope for the best
    return GenericWidgetInfo(
        method="vision",
        chat_input_selector="textarea, input[type='text'], [contenteditable='true']",
        chat_container_selector='[class*="message"], [class*="bubble"], [class*="response"]',
        open_action=None,
        uses_shadow_dom=False,
        shadow_host_selector=None,
        description=f"Vision detected: {result['description']}",
    )


async def find_widget(
    page: Page,
    anthropic_client: Optional[anthropic.AsyncAnthropic] = None,
) -> Optional[GenericWidgetInfo]:
    """Find a chat widget using heuristics first, then vision fallback."""
    # Try DOM heuristics first (instant, free)
    result = await find_widget_heuristic(page)
    if result:
        return result

    # Fall back to vision (slower, costs API call)
    if anthropic_client:
        return await find_widget_vision(page, anthropic_client)

    return None
