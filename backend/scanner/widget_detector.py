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
        "input_selector": 'textarea, input[data-testid="visitor-input"]',
        "response_selector": '[data-testid="message-text"]',
        "iframe_selector": "iframe#tidio-chat-code",
        "uses_iframe": True,
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
