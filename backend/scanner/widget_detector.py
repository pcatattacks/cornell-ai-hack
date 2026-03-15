"""Detect chat widget platforms on a web page via window globals and DOM selectors."""

import json
from typing import Optional

PLATFORM_CONFIGS = {
    "intercom": {
        "global_var": "Intercom",
        "dom_selector": 'iframe[name="intercom-messenger-frame"], #intercom-container',
        "open_command": 'Intercom("show")',
        "input_selector": 'div[contenteditable], textarea',
        "response_selector": '.intercom-block-paragraph',
        "iframe_selector": 'iframe[name="intercom-messenger-frame"]',
        "uses_iframe": True,
    },
    "tidio": {
        "global_var": "tidioChatApi",
        "dom_selector": "#tidio-chat, iframe#tidio-chat-code",
        "open_command": "tidioChatApi.open()",
        "input_selector": '[data-testid="newMessageTextarea"]',
        "response_selector": '[data-testid="messagesLog"] > *',
        "iframe_selector": None,
        "uses_iframe": False,
        "shadow_host": "#tidio-chat",
        "start_chat_command": """
            (() => {
                const root = document.querySelector('#tidio-chat')?.shadowRoot;
                if (!root) return 'no_shadow_root';

                // Strategy 1: Click "Chat with Lyro" or similar chat-start button
                const allText = [...root.querySelectorAll('*')].filter(el => {
                    const t = el.textContent?.trim().toLowerCase() || '';
                    return /chat with|start chat|ask|talk to/.test(t) && el.children.length < 3;
                });
                if (allText.length) { allText[0].click(); return 'clicked_chat_button:' + allText[0].textContent.trim().substring(0,30); }

                // Strategy 2: Click the operator element
                const operator = root.querySelector('[data-testid="operator"]');
                if (operator) { operator.click(); return 'clicked_operator'; }

                // Strategy 3: Click any button inside the home testid area
                const homeButtons = root.querySelectorAll('[data-testid="home"] button, [data-testid="home"] [role="button"]');
                if (homeButtons.length) { homeButtons[0].click(); return 'clicked_home_button'; }

                // Strategy 4: Click widgetButton
                const widgetBtn = root.querySelector('[data-testid="widgetButton"]');
                if (widgetBtn) { widgetBtn.click(); return 'clicked_widgetButton'; }

                return 'no_clickable_found';
            })()
        """,
    },
    "zendesk": {
        "global_var": "zE",
        "dom_selector": "iframe#webWidget",
        "open_command": 'zE("messenger", "open")',
        "input_selector": 'textarea[name="message"], textarea',
        "response_selector": '[data-garden-id="chat.message"]',
        "iframe_selector": "iframe#webWidget",
        "uses_iframe": True,
    },
    "crisp": {
        "global_var": "$crisp",
        "dom_selector": "#crisp-chatbox, .crisp-client",
        "open_command": '$crisp.push(["do", "chat:open"])',
        "input_selector": "span[contenteditable]",
        "response_selector": ".crisp-message-text",
        "iframe_selector": None,
        "uses_iframe": False,
    },
    "demo": {
        "global_var": "__DEMO_CHATBOT__",
        "dom_selector": "#demo-chat-widget",
        "open_command": "true",
        "input_selector": 'input[placeholder*="message"], textarea',
        "response_selector": '[data-role="assistant"]',
        "iframe_selector": None,
        "uses_iframe": False,
    },
}


def build_detection_script() -> str:
    checks_globals = {}
    checks_dom = {}
    for name, config in PLATFORM_CONFIGS.items():
        checks_globals[name] = f"typeof window.{config['global_var']} !== 'undefined'"
        checks_dom[name] = f"!!document.querySelector('{config['dom_selector']}')"

    js_globals = ", ".join(f'"{k}": {v}' for k, v in checks_globals.items())
    js_dom = ", ".join(f'"{k}": {v}' for k, v in checks_dom.items())

    return f"""
    (() => {{
        return JSON.stringify({{
            globals: {{ {js_globals} }},
            dom: {{ {js_dom} }}
        }});
    }})()
    """


def parse_detection_results(results: dict) -> Optional[str]:
    for platform, detected in results.get("globals", {}).items():
        if detected:
            return platform
    for platform, detected in results.get("dom", {}).items():
        if detected:
            return platform
    return None
