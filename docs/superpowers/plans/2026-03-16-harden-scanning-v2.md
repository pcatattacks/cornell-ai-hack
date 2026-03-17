# Harden Scanning v2 — Fix Regressions + Robust Architecture

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the regressions from the v1 hardening attempt (broken sending, broken extraction, confused discovery, slowness) while achieving the original goals of robust chatbot detection and reduced API costs.

**Architecture:** Keep the three-phase structure (agent setup → cached sending → polling extraction) but fix each phase based on real-world failures. Use observe-then-act caching for the send button, simple proven extraction schema, and mid-scan overlay recovery.

**Tech Stack:** Stagehand v3 Python SDK, Browserbase, AsyncIO

---

## What Broke in v1 and Why

| Issue | Root Cause | Fix in This Plan |
|---|---|---|
| Slowness | `_dismiss_common_overlays` makes 2 failing act() calls (~10s wasted on most sites) | Remove it — agent handles overlays |
| Tidio: typed but never sent | `"press Enter or click the send button"` too vague; many send buttons are icon-only (arrow/paper plane) | Observe send button once, cache it, click cached action for all 30 messages |
| Crisp: confused by demo elements | Agent instruction too broad — "chat bubbles, buttons" matches screenshots/demos on chatbot product pages | Strengthen instruction to distinguish real interactive widgets from page content |
| 3 sites: can't extract responses | Role-based full-transcript extraction (`{role, text}[]`) too complex for Haiku; old simple schema worked | Revert to proven simple schema (`chatbot_response` + `response_found`) |
| Streaming stability over-polling | 8 polls × 2s with stability check = up to 16s per response even when response is ready | Lighter polling: 3s initial wait, up to 3 retries, optional stability check |
| Mid-scan overlays | Not handled — overlay after message 10 breaks remaining 20 attacks | Retry-with-recovery: if send fails, dismiss overlay, retry once |

---

## File Changes

```
backend/scanner/
├── stagehand_scanner.py    # REWRITE — fix all three phases
backend/
├── main.py                 # MINOR — remove dismiss_cookies call (already done in v1)
```

No other files change. The scanner interface stays the same: `init`, `close`, `navigate`, `find_and_open_chat`, `send_message`, `read_response`, `send_and_read`.

---

## Task 1: Rewrite stagehand_scanner.py

### Overview

The scanner keeps the three-phase structure but fixes each phase:

- **Phase 1 (Discovery):** Agent with improved instruction — no pre-pass overlay dismissal
- **Phase 2 (Sending):** Observe-then-act for send button + template variables for typing + overlay recovery
- **Phase 3 (Reading):** Simple proven extraction schema + polling with stale detection

### State cached after setup

After `find_and_open_chat` succeeds, cache two action objects for the attack loop:

```python
self._cached_send_action = None  # observed send button action
```

The send button is observed on the first `send_message` call and reused for all subsequent sends. If it goes stale (element re-rendered), `self_heal=True` recovers it.

---

- [ ] **Step 1: Write the complete scanner file**

Replace the entire `backend/scanner/stagehand_scanner.py` with:

```python
"""Stagehand-based chat scanner — find, open, and interact with any chatbot.

Three-phase architecture:
  Phase 1: Agent-driven setup — dismiss overlays, find + open chatbot widget
  Phase 2: Observe-then-act sending — cached send button, template variables for typing
  Phase 3: Simple extraction reading — proven schema, polling with stale detection

Uses Browserbase Stagehand v3 SDK for reliable browser automation.
"""

import asyncio
import os
from typing import Optional, Callable, Awaitable

from dotenv import load_dotenv
from stagehand import AsyncStagehand

load_dotenv()


class StagehandScanner:
    """Manages a Stagehand browser session for scanning a chatbot."""

    def __init__(self, debug_cb: Optional[Callable[[str], Awaitable[None]]] = None):
        self._debug = debug_cb
        self.client: Optional[AsyncStagehand] = None
        self.session = None
        self.session_id: Optional[str] = None
        self._seen_responses: set[str] = set()
        self._cached_send_action = None  # observed send button, reused for all messages

    async def _log(self, msg: str):
        print(f"[stagehand] {msg}")
        if self._debug:
            try:
                await self._debug(msg)
            except Exception:
                pass

    async def init(self):
        """Initialize Stagehand client and start a session."""
        await self._log("Initializing Stagehand...")
        self.client = AsyncStagehand(
            browserbase_api_key=os.getenv("BROWSERBASE_API_KEY"),
            browserbase_project_id=os.getenv("BROWSERBASE_PROJECT_ID"),
            model_api_key=os.getenv("ANTHROPIC_API_KEY"),
        )
        self.session = await self.client.sessions.start(
            model_name="anthropic/claude-haiku-4-5-20251001",
            self_heal=True,
            wait_for_captcha_solves=True,
            dom_settle_timeout_ms=5000,
            browserbase_session_create_params={
                "browser_settings": {
                    "solve_captchas": True,
                    "block_ads": True,
                    "record_session": True,
                    "viewport": {"width": 1280, "height": 720},
                },
            },
        )
        self.session_id = self.session.id
        await self._log(f"Session started: {self.session_id}")
        await self._log(f"Live view: https://www.browserbase.com/sessions/{self.session_id}")

    async def close(self):
        """End the Stagehand session."""
        if self.session:
            try:
                await self.session.end()
                await self._log("Session ended")
            except Exception:
                pass

    # ── Phase 0: Navigation ──────────────────────────────────────────────

    async def navigate(self, url: str):
        """Navigate to the target URL and wait for page load."""
        await self.session.navigate(url=url)
        await self._log(f"Navigated to {url}")
        # Wait for time-based widget loaders (most fire within 3-5s)
        await asyncio.sleep(5)

    # ── Phase 1: Agent-driven setup ──────────────────────────────────────

    async def find_and_open_chat(self) -> bool:
        """Use Stagehand agent to find and open the chatbot.

        The agent handles the unpredictable setup: dismissing overlays/cookies,
        finding the widget, navigating menus, filling email gates. No pre-pass
        overlay dismissal — the agent handles everything in one execution.
        """
        try:
            await self._log("Starting agent-driven chatbot setup...")
            await self.session.execute(
                agent_config={
                    "model": "anthropic/claude-haiku-4-5-20251001",
                },
                execute_options={
                    "instruction": (
                        "Your goal is to find and open the AI chatbot on this page so I can type messages to it.\n\n"
                        "IMPORTANT: You are looking for a REAL, INTERACTIVE chat widget — NOT screenshots, "
                        "images, videos, or demos of chatbots that are part of the page's marketing content. "
                        "The real chat widget is typically a small floating element overlaid on the page, not "
                        "embedded in the main page layout.\n\n"
                        "Step 1: If any popups, cookie banners, or modals are blocking the page, dismiss them "
                        "(click Accept, Close, Skip, X, or 'No thanks').\n\n"
                        "Step 2: Look for the chat widget. It could appear as:\n"
                        "  - A floating bubble or icon in the bottom-right or bottom-left corner\n"
                        "  - A 'Chat with us' or 'Ask AI' button fixed to the screen edge\n"
                        "  - A chat bar or search-style input in the center of the page (like ChatGPT or assistant-ui)\n"
                        "  - A support/help widget icon\n"
                        "If you don't see one immediately, scroll down to the bottom of the page and back up "
                        "to trigger lazy-loaded widgets, then look again.\n\n"
                        "Step 3: Click to open the chat widget if it's collapsed or minimized.\n\n"
                        "Step 4: If the chat shows a menu, home screen, or conversation picker (buttons like "
                        "'Chat', 'Talk to us', 'Ask AI', 'New conversation', 'Send us a message'), click the "
                        "option that starts a new conversation.\n\n"
                        "Step 5: If asked for an email address or name, type 'test@scanner.local' for email "
                        "and 'Test' for name, then submit. If there's a Skip button, click Skip instead.\n\n"
                        "Step 6: Verify that a text input field for typing chat messages is now visible and ready. "
                        "Stop once you can see the message input.\n\n"
                        "Do NOT type any chat messages — just get the chat ready for messaging."
                    ),
                    "max_steps": 15,
                },
            )
            await self._log("Agent setup completed")

            # Verify the chat input exists
            observe_resp = await self.session.observe(
                instruction=(
                    "find the textarea or text input where a user types chat messages to send. "
                    "This input typically has a placeholder like 'Type your message', 'Ask a question', "
                    "'Type here', or 'Send a message'. Do NOT return email/name input fields."
                ),
            )
            if observe_resp and observe_resp.data and observe_resp.data.result:
                await self._log("Chat input verified — ready for messages")
                return True

            await self._log("Agent completed but chat input not found")
        except Exception as e:
            await self._log(f"Agent setup failed: {e}")

        return False

    # ── Phase 2: Sending with cached send button ─────────────────────────

    async def _observe_send_button(self):
        """Find and cache the send button action for reuse across all messages."""
        try:
            observe_resp = await self.session.observe(
                instruction=(
                    "find the send button or submit icon for the chat message input. "
                    "This is usually a button with a send icon (arrow, paper plane), "
                    "or a button labeled 'Send', right next to or inside the chat input field."
                ),
            )
            if observe_resp and observe_resp.data and observe_resp.data.result:
                action = observe_resp.data.result[0]
                self._cached_send_action = (
                    action.to_dict(exclude_none=True)
                    if hasattr(action, "to_dict")
                    else action
                )
                await self._log("Send button cached for reuse")
                return True
        except Exception as e:
            await self._log(f"Send button observe failed: {e}")
        return False

    async def _click_send(self) -> bool:
        """Click the send button using the cached action, or fall back to act()."""
        if self._cached_send_action:
            try:
                await self.session.act(input=self._cached_send_action)
                return True
            except Exception:
                # Cached action stale — clear it and fall back
                self._cached_send_action = None

        # Fallback: ask the LLM to find and click it
        try:
            await self.session.act(
                input="click the send button or submit icon next to the chat message input",
            )
            return True
        except Exception:
            pass

        # Last resort: try pressing Enter via act()
        try:
            await self.session.act(
                input="press the Enter key to send the chat message",
            )
            return True
        except Exception:
            return False

    async def send_message(self, message: str) -> bool:
        """Type a message and send it.

        Uses template variables for typing (cache-friendly across 30 attacks).
        Uses observe-then-act for the send button (0 LLM calls after first).
        """
        # Observe send button on first call
        if self._cached_send_action is None:
            await self._observe_send_button()

        try:
            # Type the message using template variables for caching
            await self.session.act(
                input="type %message% into the chat message input field",
                options={"variables": {"message": message}},
            )
            # Click the cached send button
            sent = await self._click_send()
            if sent:
                await self._log(f"Sent: {message[:50]}...")
                return True
        except Exception as e:
            await self._log(f"Send failed: {e}")

        return False

    async def _try_dismiss_overlay(self) -> bool:
        """Attempt to dismiss a mid-scan overlay blocking the chat."""
        try:
            await self.session.act(
                input=(
                    "click the Close, Dismiss, Skip, X, or 'No thanks' button on any "
                    "popup, modal, overlay, or survey that appeared over the chat"
                ),
            )
            await self._log("Mid-scan overlay dismissed")
            await asyncio.sleep(1)
            return True
        except Exception:
            return False

    # ── Phase 3: Response reading ────────────────────────────────────────

    async def read_response(self, sent_message: str) -> Optional[str]:
        """Read the chatbot's response with polling and stale detection.

        Uses the simple proven extraction schema (chatbot_response + response_found)
        that worked reliably across chatgpt.com, assistant-ui.com, hackathon.cornell.edu/ai.
        """
        await asyncio.sleep(3)  # initial wait for response to appear

        for attempt in range(4):
            try:
                extract_resp = await self.session.extract(
                    instruction=(
                        "In the chat area, find the most recent message from the CHATBOT or AI ASSISTANT. "
                        "Chat areas show two types of messages: USER messages (sent by the visitor, "
                        "usually on the right side or in a colored bubble) and BOT messages (from the "
                        "chatbot/assistant, usually on the left side or in a different colored bubble). "
                        f"The user just sent: '{sent_message[:80]}'. "
                        "Do NOT extract this user message — extract only the BOT's reply that came after it. "
                        "If the bot has not replied yet, set response_found to false."
                    ),
                    schema={
                        "type": "object",
                        "properties": {
                            "chatbot_response": {
                                "type": "string",
                                "description": "The full text of the chatbot/AI assistant's most recent reply, NOT the user's message",
                            },
                            "response_found": {
                                "type": "boolean",
                                "description": "True only if a new chatbot response was found after the user's message",
                            },
                        },
                        "required": ["chatbot_response", "response_found"],
                    },
                )
                result = extract_resp.data.result
                await self._log(f"Extract attempt {attempt + 1}: {result}")

                if isinstance(result, dict):
                    if result.get("response_found") and result.get("chatbot_response", "").strip():
                        text = result["chatbot_response"].strip()

                        # Stale response check
                        if text in self._seen_responses:
                            await self._log(f"Stale response (seen before): {text[:40]}...")
                            await asyncio.sleep(3)
                            continue

                        # Streaming stability check: wait briefly, re-extract,
                        # confirm text hasn't changed (i.e., streaming is done)
                        await asyncio.sleep(2)
                        stable_resp = await self.session.extract(
                            instruction=(
                                "Extract the most recent CHATBOT/AI ASSISTANT message in the chat area. "
                                "Only the bot's reply, not the user's message."
                            ),
                            schema={
                                "type": "object",
                                "properties": {
                                    "chatbot_response": {
                                        "type": "string",
                                        "description": "The chatbot's most recent reply text",
                                    },
                                },
                                "required": ["chatbot_response"],
                            },
                        )
                        stable_result = stable_resp.data.result
                        stable_text = (
                            stable_result.get("chatbot_response", "").strip()
                            if isinstance(stable_result, dict)
                            else ""
                        )

                        # If text matches, streaming is done — return it
                        # If text changed, use the newer (more complete) version
                        final_text = stable_text if stable_text else text
                        if final_text not in self._seen_responses:
                            self._seen_responses.add(final_text)
                            await self._log(f"Response: {final_text[:60]}...")
                            return final_text
            except Exception as e:
                await self._log(f"Extract attempt {attempt + 1} failed: {type(e).__name__}: {e}")

            if attempt < 3:
                await asyncio.sleep(3)

        await self._log("No response received (timeout)")
        return None

    # ── Convenience ──────────────────────────────────────────────────────

    async def send_and_read(self, message: str) -> Optional[str]:
        """Send a message and read the response, with overlay recovery."""
        sent = await self.send_message(message)
        if not sent:
            # Maybe an overlay appeared — try to dismiss and retry
            dismissed = await self._try_dismiss_overlay()
            if dismissed:
                sent = await self.send_message(message)
            if not sent:
                return None
        return await self.read_response(message)
```

- [ ] **Step 2: Verify import works**

Run: `cd backend && source ../.venv/bin/activate && python -c "from scanner.stagehand_scanner import StagehandScanner; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Run existing tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All 23 tests pass (scanner isn't unit-tested directly; tests cover scoring, analyzer, legacy modules)

- [ ] **Step 4: Commit**

```bash
git add backend/scanner/stagehand_scanner.py
git commit -m "fix: rewrite scanner — observe-then-act send, simple extraction, overlay recovery"
```

---

## Task 2: Verify main.py is correct

main.py was already updated in v1 to remove the `dismiss_cookies` call. Verify it's correct.

- [ ] **Step 1: Read main.py and confirm no dismiss_cookies reference**

Check that line ~124 reads:
```python
        # --- Find and open chat widget (handles overlays/cookies internally) ---
        chat_found = await scanner.find_and_open_chat()
```

No changes needed if this is already the case.

---

## Design Decisions Explained

### Why remove `_dismiss_common_overlays`?

It made 2 act() calls that **fail on most sites** (no cookie banner, no popup), each waiting for timeout. ~10s wasted. The agent handles overlays as step 1 of its instruction — it's smarter about whether overlays actually exist.

### Why observe-then-act for the send button?

The send button is the same element for all 30 messages. Observing it once and reusing the action object means:
- First message: 1 LLM call (observe) + 0 LLM calls (act with cached action)
- Messages 2-30: 0 LLM calls (reuse cached action)
- **Saves 29 LLM calls** vs. asking the LLM to "click send" each time

If the DOM re-renders and the cached selector goes stale, `self_heal=True` recovers, and we fall back to a fresh act() instruction.

### Why NOT observe-then-act for typing?

The observe pattern returns an action like `{selector: "textarea#input", method: "fill"}` — but we can't inject different message text into it each time. Template variables (`%message%`) are designed for this: the instruction template caches, only the variable changes. Best of both approaches.

### Why no f-string fallback for typing?

f-strings (`f'type "{message}" into...'`) embed the full attack payload into the LLM instruction. This means: (1) every call is a unique instruction → zero cache hits, (2) payload text with quotes, special characters, or adversarial instructions can confuse the LLM, (3) it's the slowest and most flaky option. Template variables substitute client-side *after* selector resolution, avoiding all three issues. If template variables fail, the whole send fails and overlay recovery kicks in — that's safer than silently degrading to f-strings.

### Why the simple extraction schema over role-based?

The role-based schema asked Haiku to extract an **array of {role, text} objects** from arbitrary chat UIs — classifying every message as user or assistant. This is a hard task that failed on 3 of 5 test sites.

The simple schema asks one question: "What's the latest bot response?" — a `{chatbot_response, response_found}` object. This worked reliably on all 5 test sites before v1 changes. It's less elegant but it works.

### Why retry-with-recovery for mid-scan overlays?

Some chatbots show feedback surveys, email capture, or "talk to human?" prompts after N messages. If we don't handle these, the remaining attacks all fail.

The recovery is in `send_and_read`: if `send_message` fails, try `_try_dismiss_overlay` once, then retry. This adds **0 overhead** in the normal case (overlay dismissal only runs on failure) and saves the remaining attacks when an overlay appears.

### Streaming stability check

Instead of polling 8 times looking for stability, we do one extra extraction 2s after finding a response. If the text is the same → streaming is done. If it changed → we use the newer (more complete) text. This adds only 1 extra extract call and 2s, versus the v1 approach of up to 16s.

---

## Cost Impact (Revised)

| Action | Before (old code) | After (this plan) |
|---|---|---|
| Navigate + scroll | 2 act() calls | 0 (just sleep) |
| Cookie dismissal | 1 act() call | 0 (agent handles it) |
| Agent setup | N/A | 1 execute() (5-15 steps) |
| Find + open widget | 5-15 act/observe calls | Included in agent |
| Send message (×30) | 2 act() calls each = 60 | 1st: 1 observe + 1 template act + 1 cached act = 3. Rest: 1 template act + 1 cached act ≈ 1 LLM call each = ~32 total |
| Read response (×30) | 1-3 extract each = 30-90 | 1-2 extract each = 30-60 total |
| **Total LLM calls** | **~100-170** | **~45-80** |

---

## Verification

Test on these sites (same as v1 plan):

1. **hackathon.cornell.edu/ai** — widget in bottom-right, verify all 30 attacks get responses
2. **assistant-ui.com** — center-page chat bar, verify messages send and responses extract
3. **crisp.chat** — product page with demo content AND real widget, verify agent finds the real one
4. **chatgpt.com** — streaming responses, verify stability check captures complete response
5. **A site with no chatbot** (e.g., example.com) — verify graceful "No Chatbot Detected"
6. **tidio.com** — verify send button is found and clicked (icon-only send button)
