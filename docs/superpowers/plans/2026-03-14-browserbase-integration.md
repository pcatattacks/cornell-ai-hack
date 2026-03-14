# Browserbase Integration Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan.

**Goal:** Wire up Browserbase as the production browser backend so the scanner works when deployed (not just locally) and is stable (no local Chromium crashes).

**Architecture:**
```
User (browser) → Frontend (Vercel) → Backend (Railway/Render) → Browserbase (remote Chromium)
                                                                    ↓
                                                              Target website
```

The backend connects OUT to Browserbase via WebSocket CDP. No inbound connections needed.

---

## Current State

- Browserbase API key and project ID are in `backend/.env`
- `main.py` has Browserbase code in `_launch_browser()` but it's never been tested
- Local Chromium crashes after ~20 attacks (SIGKILL/memory)
- The scanner works end-to-end on Cornell hackathon site with local Chromium

## What Needs to Happen

### Task 1: Verify Browserbase API Connection

- [ ] **Step 1: Test session creation**

Write a standalone test script `backend/test_browserbase.py`:

```python
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

        browser = await pw.chromium.connect_over_cdp(cdp_url)
        print(f"Connected! Contexts: {len(browser.contexts)}")

        # Step 3: Get or create a page
        # connect_over_cdp may have existing contexts/pages
        if browser.contexts:
            context = browser.contexts[0]
            if context.pages:
                page = context.pages[0]
                print(f"Using existing page: {page.url}")
            else:
                page = await context.new_page()
                print("Created new page in existing context")
        else:
            page = await browser.new_page()
            print("Created new page in new context")

        # Step 4: Navigate to a test URL
        print("\n--- Navigating to test URL ---")
        await page.goto("https://hackathon.cornell.edu/ai", wait_until="domcontentloaded", timeout=30000)
        print(f"Page loaded: {page.url}")
        print(f"Title: {await page.title()}")

        # Step 5: Take a screenshot
        screenshot = await page.screenshot(type="png")
        with open("/tmp/browserbase_test.png", "wb") as f:
            f.write(screenshot)
        print(f"Screenshot saved: /tmp/browserbase_test.png ({len(screenshot)} bytes)")

        # Step 6: Test JS evaluation
        result = await page.evaluate("document.title")
        print(f"JS eval works: {result}")

        await browser.close()
        print("\n--- SUCCESS: Browserbase connection works! ---")

asyncio.run(test())
```

- [ ] **Step 2: Run the test and fix any issues**

```bash
cd backend && python test_browserbase.py
```

Common issues to check:
- API key format (should start with `bb_live_` or similar)
- Project ID format (UUID)
- CDP WebSocket connection may need different URL format for newer Browserbase API
- `browser.new_page()` may fail on CDP connections — need to use existing context

- [ ] **Step 3: Fix `_launch_browser` in main.py based on test results**

Key things that may need to change:
- How we get the page after `connect_over_cdp` (existing context vs new page)
- The Browserbase API endpoint or headers
- Session creation parameters
- Error handling and logging

### Task 2: Fix Page Acquisition for CDP Connections

- [ ] **Step 1: Update `_launch_browser` to return both browser and page**

The current code does `browser = await _launch_browser(...)` then `page = await browser.new_page()`. But with CDP connections, `new_page()` may not work. Change `_launch_browser` to return the page directly:

```python
async def _launch_browser(pw, websocket, debug_cb) -> tuple[Browser, Page] | None:
    # ... existing session creation ...
    browser = await pw.chromium.connect_over_cdp(cdp_url)

    # For CDP connections, use existing context/page
    if browser.contexts:
        context = browser.contexts[0]
        if context.pages:
            page = context.pages[0]
        else:
            page = await context.new_page()
    else:
        page = await browser.new_page()

    return browser, page
```

- [ ] **Step 2: Update main.py scan_endpoint to use the new return type**

### Task 3: Add Logging to Backend

- [ ] **Step 1: Add print/logging statements to key points in main.py**

The backend currently has no server-side logging — errors are only sent via WebSocket. If the WebSocket dies, we see nothing. Add `print()` statements at:
- Browserbase session creation (success/failure)
- CDP connection (success/failure)
- Page navigation (success/failure)
- Any exception in the scan_endpoint

### Task 4: Test Full Scan via Browserbase

- [ ] **Step 1: Scan hackathon.cornell.edu/ai via Browserbase**
- [ ] **Step 2: Verify the Browserbase dashboard shows the session**
- [ ] **Step 3: Scan crisp.chat via Browserbase**
- [ ] **Step 4: Fix any issues**
- [ ] **Step 5: Commit**

### Task 5: Ensure Deployment Compatibility

- [ ] **Step 1: Verify the backend works when BROWSERBASE keys are set (production mode)**
- [ ] **Step 2: Verify the backend works when keys are NOT set (local fallback mode)**
- [ ] **Step 3: Document the environment variables needed for deployment**
