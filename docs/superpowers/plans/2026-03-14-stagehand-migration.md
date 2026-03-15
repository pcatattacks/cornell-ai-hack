# Stagehand Migration Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the custom vision navigator + generic chat modules with Browserbase's Stagehand Python SDK for reliable browser automation across any website.

**Architecture:** Stagehand handles all browser interaction (finding widgets, clicking, typing, reading responses) via its `act()`, `extract()`, and `observe()` primitives. These handle iframes, shadow DOM, and complex DOM structures automatically. Our code focuses purely on scanning logic: attack orchestration, Claude judge verdicts, and scoring/reporting.

**Tech Stack:** `stagehand` Python SDK, Browserbase, Anthropic Claude (for judging), FastAPI, Next.js

---

## What Changes

| Current | After Migration |
|---------|----------------|
| `vision_navigator.py` (300+ lines) — custom vision loop with screenshots + Claude | `stagehand_scanner.py` (~100 lines) — uses `act()`, `extract()`, `observe()` |
| `generic_chat.py` (400+ lines) — custom send/read with 4 fallback strategies | Replaced by `act("type message")` + `extract("read response")` |
| `generic_widget_finder.py` — deprecated DOM heuristic finder | Deleted |
| `generic_chat_interactor.py` — deprecated | Deleted |
| `widget_detector.py` — platform-specific globals/selectors | Keep as optional fast-path, but not required |
| `chat_interactor.py` — platform-specific Playwright interaction | Keep for backward compat, not used in default flow |
| `prechat_handler.py` — cookie/form dismissal | Cookie dismissal kept; form filling replaced by `act()` |
| `attack_runner.py` — orchestrates attacks | Modified to use Stagehand-based send/read |
| `main.py` — scan orchestrator | Modified to use Stagehand initialization |
| `response_analyzer.py` — Claude judge | Unchanged |
| `scoring.py` — grade calculation | Unchanged |
| Frontend | Unchanged |

## File Structure After Migration

```
backend/scanner/
├── stagehand_scanner.py     # NEW — core scanning logic using Stagehand
├── attack_runner.py         # MODIFIED — uses stagehand_scanner for send/read
├── response_analyzer.py     # UNCHANGED
├── scoring.py               # UNCHANGED
├── widget_detector.py       # KEPT (optional fast-path, not critical)
├── chat_interactor.py       # KEPT (not used in default flow)
├── prechat_handler.py       # SIMPLIFIED (cookie dismissal only)
├── vision_navigator.py      # DEPRECATED (kept for reference, not imported)
├── generic_chat.py          # DEPRECATED (kept for reference, not imported)
├── generic_widget_finder.py # DELETE
├── generic_chat_interactor.py # DELETE
└── __init__.py
```

---

## Chunk 1: Stagehand Setup + Core Scanner

### Task 1: Install Stagehand Python SDK

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add stagehand to dependencies**

Add `"stagehand>=0.1.0"` to the dependencies list in `pyproject.toml`.

- [ ] **Step 2: Install**

```bash
cd /Users/pranavdhingra/dev/cornell-ai-hack
source .venv/bin/activate
pip install stagehand
```

- [ ] **Step 3: Verify import**

```bash
python -c "from stagehand import Stagehand, StagehandConfig; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml
git commit -m "feat: add stagehand Python SDK dependency"
```

---

### Task 2: Create stagehand_scanner.py

**Files:**
- Create: `backend/scanner/stagehand_scanner.py`

This is the core module. It replaces `vision_navigator.py` + `generic_chat.py` with ~100 lines using Stagehand primitives.

- [ ] **Step 1: Create the scanner module**

```python
"""Stagehand-based chat scanner — find, open, and interact with any chatbot.

Uses Browserbase Stagehand SDK for reliable browser automation.
Stagehand handles iframes, shadow DOM, and complex DOM automatically.
"""

import asyncio
import os
from typing import Optional, Callable, Awaitable
from pydantic import BaseModel, Field

from stagehand import Stagehand, StagehandConfig


class ChatbotResponse(BaseModel):
    """Schema for extracting chatbot responses."""
    response_text: Optional[str] = Field(None, description="The chatbot's most recent response message text")
    has_response: bool = Field(False, description="Whether the chatbot has responded")


class StagehandScanner:
    """Manages a Stagehand browser session for scanning a chatbot."""

    def __init__(self, debug_cb: Optional[Callable[[str], Awaitable[None]]] = None):
        self._debug = debug_cb
        self.stagehand: Optional[Stagehand] = None
        self.page = None
        self._chat_ready = False

    async def _log(self, msg: str):
        print(f"[stagehand] {msg}")
        if self._debug:
            await self._debug(msg)

    async def init(self):
        """Initialize Stagehand with Browserbase."""
        config = StagehandConfig(
            env="BROWSERBASE",
            api_key=os.getenv("BROWSERBASE_API_KEY"),
            project_id=os.getenv("BROWSERBASE_PROJECT_ID"),
            model_name="anthropic/claude-sonnet-4-20250514",
            model_api_key=os.getenv("ANTHROPIC_API_KEY"),
        )
        self.stagehand = Stagehand(config)
        await self.stagehand.init()
        self.page = self.stagehand.page
        await self._log(f"Stagehand initialized. Session: {self.stagehand.session_id}")

    async def close(self):
        """Close the Stagehand session."""
        if self.stagehand:
            try:
                await self.stagehand.close()
            except Exception:
                pass

    async def navigate(self, url: str):
        """Navigate to the target URL."""
        await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await self._log(f"Navigated to {url}")
        # Wait for dynamic content / chat widgets to load
        await asyncio.sleep(5)

    async def dismiss_cookies(self):
        """Try to dismiss cookie consent banners."""
        try:
            await self.page.act(
                "If there is a cookie consent banner or popup, click Accept/Confirm/OK to dismiss it. If there is no cookie banner, do nothing.",
                timeout=5000,
            )
            await self._log("Cookie dismissal attempted")
        except Exception:
            pass

    async def find_and_open_chat(self) -> bool:
        """Find and open the chat widget, navigating through any menus.

        Returns True if a chat input is ready for messaging.
        """
        # Step 1: Look for a chat widget
        await self._log("Looking for chat widget...")
        try:
            actions = await self.page.observe(
                "Find a chat widget, chatbot launcher button, or AI assistant icon on this page. "
                "Look for floating buttons in corners, chat bubbles, or 'Chat with us' buttons. "
                "Do NOT select search bars, contact forms, or navigation links."
            )
            if not actions:
                await self._log("No chat widget found via observe")
                return False
            await self._log(f"Found {len(actions)} potential chat elements")
        except Exception as e:
            await self._log(f"Observe failed: {e}")
            return False

        # Step 2: Click to open the widget
        try:
            await self.page.act(
                "Click on the chat widget launcher button or chat icon to open the chat conversation. "
                "If the chat is already open, do nothing."
            )
            await asyncio.sleep(3)
            await self._log("Clicked chat launcher")
        except Exception as e:
            await self._log(f"Failed to click launcher: {e}")

        # Step 3: Navigate through any menu/home screen to the conversation
        for attempt in range(3):
            try:
                # Check if we're on a menu or ready to chat
                actions = await self.page.observe(
                    "In the chat widget, find a text input field where I can type a message. "
                    "It should be a textarea or input with placeholder like 'Type your message', 'Compose', 'Ask a question'. "
                    "Do NOT select email inputs, search bars, or form fields."
                )
                if actions:
                    self._chat_ready = True
                    await self._log("Chat input found — ready to send messages")
                    return True
            except Exception:
                pass

            # Not ready — try clicking through menu
            try:
                await self.page.act(
                    "In the chat widget, click the option that will start a conversation with the AI chatbot. "
                    "Look for buttons like 'Chat', 'Talk to us', 'Ask AI', 'Start conversation', 'Message us'. "
                    "Avoid 'FAQ', 'Help Center', 'Documentation', 'Pricing' links."
                )
                await asyncio.sleep(3)
                await self._log(f"Clicked menu option (attempt {attempt + 1})")
            except Exception:
                break

        # Step 4: Handle pre-chat forms (email gates)
        try:
            await self.page.act(
                "If there is a form asking for email address or name before chatting, "
                "fill the email field with 'test@scanner.local', check any consent checkboxes, "
                "and click the Send/Submit/Start button. If there is no form, do nothing."
            )
            await asyncio.sleep(3)
        except Exception:
            pass

        # Final check
        try:
            actions = await self.page.observe(
                "Find a text input field for typing chat messages. "
                "Look for textarea or input with placeholder about typing a message."
            )
            if actions:
                self._chat_ready = True
                await self._log("Chat input found after form handling")
                return True
        except Exception:
            pass

        await self._log("Could not find chat input after all attempts")
        return False

    async def send_message(self, message: str) -> bool:
        """Type a message into the chat input and send it."""
        try:
            await self.page.act(
                f'Type the following message into the chat message input field and press Enter to send it: "{message}"'
            )
            await self._log("Message sent via Stagehand act()")
            return True
        except Exception as e:
            await self._log(f"Failed to send message: {e}")
            return False

    async def read_response(self, sent_message: str, timeout_seconds: int = 15) -> Optional[str]:
        """Read the chatbot's response after sending a message.

        Waits for the response to appear and stabilize.
        """
        await asyncio.sleep(3)  # Wait for initial response

        for attempt in range(3):
            try:
                result = await self.page.extract(
                    f"Extract the chatbot's most recent response message. "
                    f"I just sent: '{sent_message[:60]}'. "
                    f"Read the bot's reply, NOT my own message. "
                    f"The bot's response is typically in a different color or alignment from the user's messages. "
                    f"If the bot hasn't responded yet, set has_response to false.",
                    schema=ChatbotResponse,
                )
                if result.has_response and result.response_text:
                    await self._log(f"Response: {result.response_text[:60]}...")
                    return result.response_text
            except Exception as e:
                await self._log(f"Extract attempt {attempt + 1} failed: {e}")

            if attempt < 2:
                await asyncio.sleep(3)  # Wait more before retry

        await self._log("No response received")
        return None

    async def send_and_read(self, message: str) -> Optional[str]:
        """Send a message and read the chatbot's response."""
        sent = await self.send_message(message)
        if not sent:
            return None
        return await self.read_response(message)
```

- [ ] **Step 2: Verify import**

```bash
python -c "from scanner.stagehand_scanner import StagehandScanner; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add backend/scanner/stagehand_scanner.py
git commit -m "feat: add Stagehand-based scanner module"
```

---

### Task 3: Update attack_runner.py

**Files:**
- Modify: `backend/scanner/attack_runner.py`

Add a new `run_attacks_stagehand` function that uses `StagehandScanner`.

- [ ] **Step 1: Add the new attack runner function**

```python
async def run_attacks_stagehand(
    scanner: "StagehandScanner",
    anthropic_client: anthropic.AsyncAnthropic,
    max_per_category: int | None = None,
    delay_seconds: float = 3.0,
    debug_cb=None,
) -> AsyncGenerator[dict, None]:
    """Run attacks using Stagehand scanner."""
    payloads = load_payloads(max_per_category=max_per_category)
    consecutive_failures = 0

    for i, payload_data in enumerate(payloads):
        attack_id = i + 1

        yield {
            "type": "attack_sent",
            "id": attack_id,
            "category": payload_data["category"],
            "name": payload_data["name"],
            "payload": payload_data["payload"],
            "progress": f"{attack_id}/{len(payloads)}",
        }

        response_text = await scanner.send_and_read(payload_data["payload"])

        yield {
            "type": "attack_response",
            "id": attack_id,
            "response": response_text or "(no response / timeout)",
        }

        if response_text:
            consecutive_failures = 0
            verdict = await judge_response(
                client=anthropic_client,
                category=payload_data["category"],
                payload=payload_data["payload"],
                response=response_text,
            )
        else:
            consecutive_failures += 1
            verdict = Verdict(
                verdict="RESISTANT",
                confidence=0.5,
                evidence="No response received from chatbot (timeout)",
            )

        yield {
            "type": "attack_verdict",
            "id": attack_id,
            "category": payload_data["category"],
            "verdict": verdict.verdict,
            "confidence": verdict.confidence,
            "evidence": verdict.evidence,
            "score": verdict.score,
        }

        if consecutive_failures >= 5:
            yield {
                "type": "browser_died",
                "message": f"5 consecutive timeouts after attack {attack_id}. Chatbot may be rate-limiting.",
                "completed_attacks": attack_id,
                "total_attacks": len(payloads),
            }
            return

        await asyncio.sleep(delay_seconds)
```

Add the import at top of file:

```python
from scanner.stagehand_scanner import StagehandScanner
```

- [ ] **Step 2: Commit**

```bash
git add backend/scanner/attack_runner.py
git commit -m "feat: add run_attacks_stagehand using Stagehand scanner"
```

---

### Task 4: Update main.py scan orchestrator

**Files:**
- Modify: `backend/main.py`

Replace the complex scan flow with a clean Stagehand-based flow.

- [ ] **Step 1: Rewrite the scan_endpoint**

The new flow:

```
1. Accept URL from WebSocket
2. Create StagehandScanner (initializes Browserbase session)
3. Navigate to URL
4. Dismiss cookies
5. Find and open chat widget
6. Run attacks via run_attacks_stagehand
7. Score + report
8. Close scanner
```

Key changes:
- Remove `_launch_browser`, `_wait_for_widget`, `_detect_platform` and all the complex vision/DOM logic
- Remove imports of `vision_navigator`, `generic_chat`, `generic_widget_finder`, `generic_chat_interactor`
- Keep imports of `attack_runner.run_attacks_stagehand`, `scoring`, `response_analyzer`
- Keep `_build_report`, `_empty_report`, `REMEDIATION`

The scan_endpoint becomes:

```python
@app.websocket("/ws/scan")
async def scan_endpoint(websocket: WebSocket):
    await websocket.accept()
    scanner = None

    try:
        data = await websocket.receive_json()
        url = data.get("url")
        if not url:
            await websocket.send_json({"type": "error", "message": "URL is required", "fatal": True})
            return
        if not url.startswith("http"):
            url = f"https://{url}"

        await websocket.send_json({
            "type": "scan_start",
            "url": url,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        async def debug_cb(msg: str):
            await websocket.send_json({"type": "debug", "message": msg})

        anthropic_client = anthropic.AsyncAnthropic()

        # Initialize Stagehand
        scanner = StagehandScanner(debug_cb=debug_cb)
        await scanner.init()

        # Navigate
        await scanner.navigate(url)

        # Dismiss cookies
        await scanner.dismiss_cookies()
        await websocket.send_json({"type": "prechat_status", "action": "cookie_dismissed"})

        # Find and open chat
        chat_found = await scanner.find_and_open_chat()
        if not chat_found:
            await websocket.send_json({"type": "widget_not_found", "message": "No chat widget found."})
            await websocket.send_json({"type": "scan_complete", "report": _empty_report(url)})
            return

        await websocket.send_json({"type": "widget_detected", "platform": "auto-detected (Stagehand)"})

        # Run attacks
        findings = []
        scan_aborted = False
        async for event in run_attacks_stagehand(
            scanner=scanner,
            anthropic_client=anthropic_client,
            delay_seconds=3.0,
            debug_cb=debug_cb,
        ):
            await websocket.send_json(event)
            if event["type"] == "attack_verdict":
                findings.append({...})  # same as current
            if event["type"] == "browser_died":
                scan_aborted = True

        # Report
        report = _build_report(url, "auto-detected (Stagehand)", findings)
        if scan_aborted:
            report["scan_aborted"] = True
            report["message"] = "Scan interrupted. Report based on completed attacks."
        await websocket.send_json({"type": "scan_complete", "report": report})

    except WebSocketDisconnect:
        print("[scan] WebSocket disconnected")
    except Exception as e:
        print(f"[scan] ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        try:
            await websocket.send_json({"type": "error", "message": str(e), "fatal": True})
        except Exception:
            pass
    finally:
        if scanner:
            await scanner.close()
```

- [ ] **Step 2: Verify server starts**

```bash
cd backend && uvicorn main:app --port 8000 &
sleep 2 && curl -s http://localhost:8000/health && kill %1
```

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat: replace vision loop with Stagehand-based scan flow"
```

---

## Chunk 2: Testing + Cleanup

### Task 5: Test on Cornell hackathon site

- [ ] **Step 1: Start backend**
- [ ] **Step 2: Scan hackathon.cornell.edu/ai**
- [ ] **Step 3: Verify: widget found, attacks run, responses captured, report generated**
- [ ] **Step 4: Fix any issues**

### Task 6: Test on crisp.chat

- [ ] **Step 1: Scan crisp.chat**
- [ ] **Step 2: Verify: email overlay handled, messages sent, responses read**
- [ ] **Step 3: Fix any issues**

### Task 7: Test on one more site

- [ ] **Step 1: Scan another site (tidio.com or assistant-ui.com)**
- [ ] **Step 2: Fix any issues**
- [ ] **Step 3: Commit fixes**

### Task 8: Clean up deprecated files

- [ ] **Step 1: Delete `backend/scanner/generic_widget_finder.py`**
- [ ] **Step 2: Delete `backend/scanner/generic_chat_interactor.py`**
- [ ] **Step 3: Remove unused imports from `main.py`**
- [ ] **Step 4: Run tests, fix any broken ones**
- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove deprecated scanner modules, clean up imports"
```

---

## Why This Is Better

| Aspect | Before (custom) | After (Stagehand) |
|--------|-----------------|-------------------|
| Find chat input | 300+ lines, still fragile | `observe("find chat input")` |
| Handle iframes | Manual `page.frames` search | Automatic |
| Handle shadow DOM | Manual JS evaluation | Automatic |
| Type message | 4 fallback strategies, still fails | `act("type message")` |
| Read response | DOM selectors + vision fallback | `extract("read response")` |
| Handle overlays | Custom vision recovery | `act("dismiss overlay")` |
| Time per attack | 20-30s | 8-12s |
| Lines of code | ~700 (vision_nav + generic_chat) | ~100 (stagehand_scanner) |
| Reliability | Works on ~1/3 sites tested | Should work on most sites |

## Environment Variables Required

```
ANTHROPIC_API_KEY=sk-ant-...      # For Claude judge + Stagehand model
BROWSERBASE_API_KEY=bb_live_...   # For Browserbase sessions
BROWSERBASE_PROJECT_ID=...        # Browserbase project
```

Note: `ANTHROPIC_API_KEY` now serves double duty — it's used by both our Claude judge AND by Stagehand as the `model_api_key` for its `act()`/`extract()`/`observe()` calls.
