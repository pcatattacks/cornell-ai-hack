"""Handle cookie banners, pre-chat forms, and widget opening."""

import asyncio
from playwright.async_api import Page
from scanner.widget_detector import PLATFORM_CONFIGS


async def dismiss_cookie_banner(page: Page) -> bool:
    strategies = [
        "typeof window.CookieConsent !== 'undefined' && typeof window.CookieConsent.acceptAll === 'function' && (window.CookieConsent.acceptAll(), true) || false",
        "typeof window.Cookiebot !== 'undefined' && typeof window.Cookiebot.submitCustomConsent === 'function' && (window.Cookiebot.submitCustomConsent(false, false, false), true) || false",
        """(() => {
            const selectors = [
                'button[id*="accept"]', 'button[id*="cookie"]',
                'button[class*="accept"]', 'button[class*="cookie"]',
                'button[data-action="accept"]',
                'a[id*="accept"]', 'a[class*="accept"]',
            ];
            for (const sel of selectors) {
                const btn = document.querySelector(sel);
                if (btn) { btn.click(); return true; }
            }
            const buttons = [...document.querySelectorAll('button, a')];
            const acceptBtn = buttons.find(b => /^(accept|confirm|agree|got it|ok)$/i.test(b.textContent.trim()));
            if (acceptBtn) { acceptBtn.click(); return true; }
            return false;
        })()""",
    ]

    for strategy in strategies:
        try:
            result = await page.evaluate(strategy)
            if result:
                await asyncio.sleep(0.5)
                return True
        except Exception:
            continue

    return False


async def fill_prechat_form(page_or_frame, platform: str, debug_cb=None) -> bool:
    async def _log(msg):
        if debug_cb:
            await debug_cb(msg)

    # Check if this platform uses shadow DOM — if so, search inside it
    config = PLATFORM_CONFIGS.get(platform, {})
    shadow_host = config.get("shadow_host")

    if shadow_host:
        return await _fill_shadow_prechat_form(page_or_frame, shadow_host, _log)

    try:
        email_script = """
        (() => {
            const inputs = document.querySelectorAll('input[type="email"], input[name*="email"], input[placeholder*="email"]');
            for (const input of inputs) {
                input.value = 'test@scanner.local';
                input.dispatchEvent(new Event('input', {bubbles: true}));
                input.dispatchEvent(new Event('change', {bubbles: true}));
            }
            const nameInputs = document.querySelectorAll('input[name*="name"], input[placeholder*="name"]');
            for (const input of nameInputs) {
                input.value = 'Security Scanner';
                input.dispatchEvent(new Event('input', {bubbles: true}));
                input.dispatchEvent(new Event('change', {bubbles: true}));
            }
            const checkboxes = document.querySelectorAll('input[type="checkbox"]');
            for (const cb of checkboxes) { cb.checked = true; cb.dispatchEvent(new Event('change', {bubbles: true})); }
            const buttons = [...document.querySelectorAll('button, input[type="submit"]')];
            const submitBtn = buttons.find(b => /^(send|submit|start|continue|begin)$/i.test(b.textContent?.trim() || b.value?.trim() || ''));
            if (submitBtn) { submitBtn.click(); return true; }
            return inputs.length > 0;
        })()
        """
        result = await page_or_frame.evaluate(email_script)
        if result:
            await asyncio.sleep(1)
        return bool(result)
    except Exception:
        return False


async def _fill_shadow_prechat_form(page, shadow_host: str, _log) -> bool:
    """Fill pre-chat forms inside a shadow DOM (e.g., Tidio email gate)."""
    try:
        result = await page.evaluate(f"""
            (() => {{
                const host = document.querySelector('{shadow_host}');
                const root = host?.shadowRoot;
                if (!root) return 'no_shadow_root';

                // Find email inputs inside shadow DOM
                const emailInputs = root.querySelectorAll('input[type="email"], input[name*="email"], input[placeholder*="email"], input[placeholder*="Email"]');
                let filled = false;
                for (const input of emailInputs) {{
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    setter.call(input, 'test@scanner.local');
                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    filled = true;
                }}

                // Check any checkboxes (GDPR consent etc.)
                const checkboxes = root.querySelectorAll('input[type="checkbox"]');
                for (const cb of checkboxes) {{
                    if (!cb.checked) {{
                        cb.click();
                    }}
                }}

                // Click send/submit button
                const buttons = [...root.querySelectorAll('button, input[type="submit"]')];
                const submitBtn = buttons.find(b => /^(send|submit|start|continue|begin)$/i.test(b.textContent?.trim() || b.value?.trim() || ''));
                if (submitBtn) {{
                    submitBtn.click();
                    return 'submitted';
                }}

                return filled ? 'filled_no_submit' : 'no_email_input';
            }})()
        """)
        await _log(f"fill_shadow_prechat_form: result={result}")

        if result in ('submitted', 'filled_no_submit'):
            await asyncio.sleep(3)  # Wait for form submission + chat view to load
            return True
        return False
    except Exception as e:
        await _log(f"fill_shadow_prechat_form: FAILED: {e}")
        return False


async def open_widget(page: Page, platform: str, debug_cb=None) -> bool:
    config = PLATFORM_CONFIGS.get(platform)
    if not config:
        return False

    async def _log(msg):
        if debug_cb:
            await debug_cb(msg)

    try:
        await page.evaluate(config["open_command"])
        await _log(f"open_widget: executed open_command for {platform}")
        await asyncio.sleep(2)

        if config.get("start_chat_command"):
            result = await page.evaluate(config["start_chat_command"])
            await _log(f"open_widget: start_chat_command result={result}")
            await asyncio.sleep(2)

        # Diagnostic: dump shadow DOM contents if shadow_host is configured
        if config.get("shadow_host"):
            diag = await page.evaluate(f"""
                (() => {{
                    const host = document.querySelector('{config["shadow_host"]}');
                    if (!host) return 'shadow_host not found';
                    const root = host.shadowRoot;
                    if (!root) return 'no shadowRoot';
                    const testids = [...root.querySelectorAll('[data-testid]')].map(e => e.getAttribute('data-testid')).slice(0, 20);
                    const inputs = [...root.querySelectorAll('input,textarea,[contenteditable]')].map(e => e.tagName + '#' + e.id + '.' + (e.className||'').toString().substring(0,30) + '[placeholder=' + (e.placeholder||'') + ']').slice(0, 10);
                    const buttons = [...root.querySelectorAll('button,[role="button"]')].map(e => (e.getAttribute('data-testid') || e.textContent.trim().substring(0,30))).slice(0, 10);
                    return JSON.stringify({{testids, inputs, buttons}});
                }})()
            """)
            await _log(f"open_widget: shadow DOM diagnostic: {diag}")

        return True
    except Exception as e:
        await _log(f"open_widget: FAILED: {e}")
        return False
