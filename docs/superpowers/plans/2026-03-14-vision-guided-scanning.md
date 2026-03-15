# Vision-Guided Generic Scanning — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace brittle platform-specific widget detection/interaction with a vision-guided approach that works on any website with a chat widget.

**Architecture:** The scan engine takes screenshots at each step and sends them to Claude Sonnet via the Anthropic SDK (`anthropic.AsyncAnthropic`). Claude analyzes the screenshot and returns structured JSON with what to do next (click coordinates, form fields to fill, etc.). Playwright executes the action. This loop repeats until the chat input is found or we give up.

**Tech Stack:** Anthropic Python SDK (already installed), Playwright screenshots, Claude Sonnet vision

---

## Architecture

```
Scan Flow (per scan):

1. Navigate to URL
2. Dismiss cookie banner (existing code — keep it, it's reliable)
3. Wait for page load
4. VISION LOOP — "Widget Navigator" (NEW):
   a. Screenshot → Claude: "Is there a chat widget? Describe what you see."
      → If no widget: report "no widget found", end scan
      → If widget found but closed: Claude returns click coordinates to open it
   b. Click to open → wait 2s → screenshot again
   c. Claude: "The chat widget is open. Is there a form (email/name) to fill before chatting?"
      → If form: Claude returns field descriptions → fill via JS → click submit → wait
      → If no form: proceed
   d. Screenshot → Claude: "Where is the message input field? Return its position."
      → Claude returns description of input location
   e. Use Playwright to find and verify the input element
5. ATTACK LOOP (existing code, modified):
   - Instead of platform-specific ChatInteractor, use a generic approach:
     - Type into the located input via Playwright .fill() + .press("Enter")
     - Wait for response (poll for new text elements, same as before)
     - Send response to Claude judge (existing code)
6. Score + report (existing code — unchanged)
```

### API Call Architecture

- **Client:** `anthropic.AsyncAnthropic()` — same client used for response judging
- **Model:** `claude-sonnet-4-20250514` — vision-capable, fast enough
- **Each vision call:** Fresh stateless call. Send screenshot as base64 image + structured prompt → get JSON back
- **No conversation history needed** — each screenshot is self-contained context
- **Cost:** ~$0.01-0.03 per vision call. ~5 navigation calls + ~30 judge calls = ~35 calls per scan

### Compatibility

- **Local Playwright:** `page.screenshot()` returns PNG bytes — works
- **Browserbase remote:** Same Playwright API over CDP — `page.screenshot()` works identically
- **Deployment:** No changes needed. Backend on Railway/Render, frontend on Vercel, Browserbase for remote browser

---

## File Structure

```
backend/scanner/
├── vision_navigator.py     # NEW — vision-guided widget finding + opening
├── generic_chat.py         # NEW — simplified generic chat send/read (replaces platform-specific interactor for generic path)
├── main.py                 # MODIFY — restructure scan flow: try vision-guided first
├── widget_detector.py      # KEEP — still useful as fast-path (no API cost)
├── chat_interactor.py      # KEEP — used when platform-specific path works
├── prechat_handler.py      # KEEP — cookie dismissal still used
├── attack_runner.py        # MODIFY — accept a generic send/read function instead of platform-specific interactor
├── response_analyzer.py    # UNCHANGED
├── scoring.py              # UNCHANGED
└── generic_widget_finder.py    # DEPRECATE — replaced by vision_navigator.py
    generic_chat_interactor.py  # DEPRECATE — replaced by generic_chat.py
```

---

## Task 1: Vision Navigator Module

**Files:**
- Create: `backend/scanner/vision_navigator.py`

This module handles the vision-guided loop: screenshot → Claude → act → repeat.

- [ ] **Step 1: Create the vision navigator**

The module exposes one main function:

```python
async def navigate_to_chat(
    page: Page,
    anthropic_client: AsyncAnthropic,
    debug_cb: Callable | None = None,
) -> ChatTarget | None
```

Returns a `ChatTarget` dataclass with:
- `input_method`: "locator" or "coordinates"
- `input_locator`: Playwright locator string (if found via DOM inspection after vision)
- `input_coordinates`: (x, y) tuple (if vision-only)
- `response_region`: description of where responses appear
- `notes`: any context from Claude about the widget

The function:
1. Takes a screenshot, sends to Claude with prompt:
   ```
   Look at this webpage screenshot.
   1. Is there a chat widget, chatbot button, or support chat icon visible?
   2. If yes, is it open (showing a conversation/input area) or closed (just a button/icon)?
   3. If closed, what are the pixel coordinates (x, y) I should click to open it?

   Respond with JSON only:
   {"found": true/false, "state": "open"|"closed"|"not_found", "click": {"x": N, "y": N} | null, "description": "..."}
   ```

2. If closed: click the coordinates, wait 2s, take another screenshot

3. Check for pre-chat forms:
   ```
   The chat widget is now open. Look at it carefully.
   1. Is there a form asking for email, name, or other info before chatting?
   2. Is there a message input/textarea where I can type a message?

   Respond with JSON only:
   {"has_prechat_form": true/false, "form_fields": [{"type": "email"|"name"|"checkbox"|"other", "description": "..."}] | null, "has_chat_input": true/false, "chat_input_description": "...", "needs_action": "fill_form"|"click_button"|"ready_to_chat"|"other", "action_description": "..."}
   ```

4. If form found: fill it using JS (email: test@scanner.local), click submit, wait, re-screenshot

5. Final check — locate the chat input:
   ```
   I need to find the chat message input field on this page.
   Look at the chat widget and find where I would type a message.

   Respond with JSON only:
   {"found": true/false, "input_type": "textarea"|"input"|"contenteditable", "approximate_position": {"x": N, "y": N}, "placeholder_text": "...", "description": "..."}
   ```

6. After getting the position, try to find the actual DOM element near those coordinates using `page.evaluate()` — check for textarea, input, or contenteditable elements in that region. This gives us a real selector for reliable typing.

- [ ] **Step 2: Commit**

```bash
git add backend/scanner/vision_navigator.py
git commit -m "feat: add vision-guided widget navigator using Claude screenshots"
```

---

## Task 2: Generic Chat Send/Read

**Files:**
- Create: `backend/scanner/generic_chat.py`

Simplified send/read that works with whatever input the vision navigator found.

- [ ] **Step 1: Create generic chat module**

```python
async def send_message(page: Page, message: str, chat_target: ChatTarget, debug_cb) -> bool
async def read_latest_response(page: Page, debug_cb) -> str | None
async def send_and_read(page: Page, message: str, chat_target: ChatTarget, debug_cb, timeout_ms=30000) -> str | None
```

`send_message`:
- Try Playwright locator-based approach first: find visible textarea/input/contenteditable near the target coordinates using `page.locator()` with `:visible` filter
- If that fails, fall back to clicking the coordinates and typing via `page.keyboard.type()`
- Press Enter to send

`read_latest_response`:
- Use `page.evaluate()` to scan for the most recently added text content near the chat widget area
- Look for common response patterns: elements with class containing "message", "response", "bubble", "bot", "assistant"
- Also try a generic approach: find the last block of text that appeared after we sent our message
- Return the text content

`send_and_read`:
- Get message count/text before sending
- Send message
- Poll for new text content (same 500ms interval, 2-stable check)
- Return response text

- [ ] **Step 2: Commit**

```bash
git add backend/scanner/generic_chat.py
git commit -m "feat: add generic chat send/read for vision-guided scanning"
```

---

## Task 3: Update Attack Runner for Generic Mode

**Files:**
- Modify: `backend/scanner/attack_runner.py`

- [ ] **Step 1: Add generic attack running function**

Add a new function alongside the existing `run_attacks`:

```python
async def run_attacks_generic(
    page: Page,
    chat_target: ChatTarget,
    anthropic_client: AsyncAnthropic,
    max_per_category: int | None = None,
    delay_seconds: float = 2.0,
    debug_cb = None,
) -> AsyncGenerator[dict, None]:
```

Same structure as `run_attacks` but uses `generic_chat.send_and_read()` instead of `ChatInteractor`.

- [ ] **Step 2: Commit**

```bash
git add backend/scanner/attack_runner.py
git commit -m "feat: add generic attack runner using vision-guided chat"
```

---

## Task 4: Restructure main.py Scan Flow

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Restructure the scan flow**

New flow:
1. Navigate + dismiss cookies (unchanged)
2. Try platform-specific detection (fast path, no API cost)
3. If platform found → try platform-specific open + interact
4. **If platform-specific fails OR no platform detected → vision-guided path:**
   a. Call `navigate_to_chat()` to find and open the widget
   b. Use `run_attacks_generic()` with the returned `ChatTarget`
5. Score + report (unchanged)

The key change: platform-specific is now a fast-path optimization, not the primary path. Vision-guided is the fallback that handles everything.

- [ ] **Step 2: Commit**

```bash
git add backend/main.py
git commit -m "feat: restructure scan flow — vision-guided as primary fallback"
```

---

## Task 5: Test on Real Sites

- [ ] **Step 1: Test on tidio.com**
- [ ] **Step 2: Test on one other site with a chat widget**
- [ ] **Step 3: Fix any issues found**
- [ ] **Step 4: Commit fixes**

---

## Task 6: Commit and Clean Up

- [ ] **Step 1: Remove deprecated generic_widget_finder.py and generic_chat_interactor.py**
- [ ] **Step 2: Run all tests, fix any broken ones**
- [ ] **Step 3: Final commit**
