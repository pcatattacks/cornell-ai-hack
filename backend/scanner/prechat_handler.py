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


async def fill_prechat_form(page_or_frame, platform: str) -> bool:
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


async def open_widget(page: Page, platform: str) -> bool:
    config = PLATFORM_CONFIGS.get(platform)
    if not config:
        return False

    try:
        await page.evaluate(config["open_command"])
        await asyncio.sleep(1)
        if config.get("start_chat_command"):
            await page.evaluate(config["start_chat_command"])
            await asyncio.sleep(1)
        return True
    except Exception:
        return False
