"""Standalone test script for Browserbase connection."""

import asyncio
import os
import httpx
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()


async def test():
    api_key = os.getenv("BROWSERBASE_API_KEY")
    project_id = os.getenv("BROWSERBASE_PROJECT_ID")

    if not api_key or not project_id:
        print("ERROR: BROWSERBASE_API_KEY or BROWSERBASE_PROJECT_ID not set in .env")
        return

    print(f"API Key: {api_key[:15]}...")
    print(f"Project ID: {project_id}")

    # Step 1: Create session
    print("\n--- Creating Browserbase session ---")
    async with httpx.AsyncClient() as http:
        resp = await http.post(
            "https://www.browserbase.com/v1/sessions",
            headers={"x-bb-api-key": api_key},
            json={"projectId": project_id},
        )
        print(f"Status: {resp.status_code}")
        if resp.status_code not in (200, 201):
            print(f"ERROR: {resp.text}")
            return
        session = resp.json()
        session_id = session["id"]
        print(f"Session ID: {session_id}")

    # Step 2: Connect via CDP
    print("\n--- Connecting via CDP ---")
    async with async_playwright() as pw:
        cdp_url = f"wss://connect.browserbase.com?apiKey={api_key}&sessionId={session_id}"
        print(f"CDP URL: {cdp_url[:60]}...")

        try:
            browser = await pw.chromium.connect_over_cdp(cdp_url)
        except Exception as e:
            print(f"ERROR connecting: {type(e).__name__}: {e}")
            return

        print(f"Connected! Contexts: {len(browser.contexts)}")
        for i, ctx in enumerate(browser.contexts):
            print(f"  Context {i}: {len(ctx.pages)} pages")
            for j, p in enumerate(ctx.pages):
                print(f"    Page {j}: {p.url}")

        # Step 3: Get or create a page
        if browser.contexts:
            context = browser.contexts[0]
            if context.pages:
                page = context.pages[0]
                print(f"\nUsing existing page: {page.url}")
            else:
                page = await context.new_page()
                print("\nCreated new page in existing context")
        else:
            try:
                page = await browser.new_page()
                print("\nCreated new page in new context")
            except Exception as e:
                print(f"\nERROR creating page: {type(e).__name__}: {e}")
                await browser.close()
                return

        page.set_default_timeout(30000)

        # Step 4: Navigate to a test URL
        print("\n--- Navigating to test URL ---")
        try:
            await page.goto("https://hackathon.cornell.edu/ai", wait_until="domcontentloaded", timeout=30000)
            print(f"Page loaded: {page.url}")
            title = await page.title()
            print(f"Title: {title}")
        except Exception as e:
            print(f"ERROR navigating: {type(e).__name__}: {e}")
            await browser.close()
            return

        # Step 5: Take a screenshot
        try:
            screenshot = await page.screenshot(type="png")
            with open("/tmp/browserbase_test.png", "wb") as f:
                f.write(screenshot)
            print(f"Screenshot saved: /tmp/browserbase_test.png ({len(screenshot)} bytes)")
        except Exception as e:
            print(f"ERROR screenshot: {type(e).__name__}: {e}")

        # Step 6: Test JS evaluation
        try:
            result = await page.evaluate("document.title")
            print(f"JS eval works: {result}")
        except Exception as e:
            print(f"ERROR JS eval: {type(e).__name__}: {e}")

        # Step 7: Test keyboard interaction
        try:
            await page.keyboard.press("Tab")
            print("Keyboard works: Tab pressed")
        except Exception as e:
            print(f"ERROR keyboard: {type(e).__name__}: {e}")

        await browser.close()
        print("\n--- SUCCESS: Browserbase connection works! ---")


asyncio.run(test())
