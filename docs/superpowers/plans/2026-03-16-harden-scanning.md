# Harden Scanning — Robust Chatbot Detection + Cost Optimization

> **For agentic workers:** REQUIRED: Use superpowers:executing-plans to implement this plan.

**Goal:** Make AgentProbe reliably find and interact with chatbots on any website, eliminate false positive/stale responses, and reduce API costs by 50-70%.

**Architecture:** Restructure `stagehand_scanner.py` into three phases: (1) Agent-driven setup for messy multi-step navigation, (2) Cached `act`/`extract` for the attack loop, (3) Polling-based response reading with role differentiation.

**Key insight from research:** Use the Stagehand **agent** for the unpredictable part (finding + opening the chatbot), then switch to **direct `act` + `extract` with caching** for the predictable part (sending 30 messages). This gives robustness where needed and speed/cost savings where possible.

---

## Current Problems

1. **Flaky widget detection** — `observe` + `act` sometimes misses widgets, especially shadow DOM / late-loading
2. **Stale response reads** — `extract()` returns old responses, causing false positives
3. **Slow scans** — every `act()` and `extract()` call hits the LLM
4. **No caching** — same selector resolution happens 30 times for 30 attacks
5. **False positives** — can't distinguish user messages from bot messages reliably

## Architecture After Changes

```
Phase 1: AGENT-DRIVEN SETUP (robust, uses agent loop)
  - Dismiss overlays/popups/cookie banners
  - Find and open chatbot widget
  - Navigate menus, fill email gates
  - Verify chat input is ready
  → Once chat is confirmed ready, exit agent

Phase 2: CACHED ATTACK LOOP (fast, uses templates + caching)
  - Use templated act(): "type %message% into the chat message input and send it"
  - Same template for all 30 attacks → cache hit after first one
  - Direct act(), no agent overhead

Phase 3: RESPONSE READING (reliable, uses role-based extraction)
  - Extract before sending (baseline message count + last text)
  - Extract after sending with role schema (user vs assistant)
  - Poll until new assistant message appears that differs from baseline
  - Timeout gracefully
```

---

## File Changes

```
backend/scanner/
├── stagehand_scanner.py    # REWRITE — three-phase architecture
```

No other files need to change — the scanner interface (`init`, `close`, `navigate`, `find_and_open_chat`, `send_message`, `read_response`, `send_and_read`) stays the same.

---

## Task 1: Rewrite stagehand_scanner.py

### Phase 1: Agent-driven setup

Replace `find_and_open_chat` with an agent-based approach:

```python
async def find_and_open_chat(self) -> bool:
    """Use Stagehand agent for the messy multi-step setup."""
    try:
        result = await self.session.execute(
            execute_options={
                "instruction": (
                    "Your goal is to find and open the AI chatbot on this page so I can type messages to it.\n\n"
                    "Step 1: If any popups, cookie banners, or modals are blocking the page, dismiss them "
                    "(click Accept, Close, Skip, X, or 'No thanks').\n\n"
                    "Step 2: Find the chat widget. Look for floating chat bubbles, 'Chat with us' buttons, "
                    "AI assistant icons, or support chat widgets — usually in the bottom-right corner.\n\n"
                    "Step 3: Click to open the chat widget if it's closed.\n\n"
                    "Step 4: If the chat widget shows a menu or home screen (buttons like 'Chat', 'Talk to us', "
                    "'Ask AI'), click the option that starts a conversation.\n\n"
                    "Step 5: If asked for an email address, type 'test@scanner.local' and submit. "
                    "If there's a Skip button, click Skip instead.\n\n"
                    "Step 6: Verify that a text input field for typing chat messages is now visible. "
                    "Stop once you can see the message input.\n\n"
                    "Do NOT type any messages yet — just get the chat ready for messaging."
                ),
                "max_steps": 15,
            },
            timeout=60.0,
        )
        # Verify the chat input exists
        observe_resp = await self.session.observe(
            instruction="find the text input field for typing chat messages",
        )
        if observe_resp.data.result:
            return True
    except Exception as e:
        await self._log(f"Agent setup failed: {e}")
    return False
```

**Why agent:** The setup phase is unpredictable — different sites have different popups, menus, email gates. The agent handles all of this in one instruction without us writing separate handlers for each case.

### Phase 2: Cached templated sending

Replace `send_message` with a templated approach:

```python
async def send_message(self, message: str) -> bool:
    """Send a message using templated act() for cache hits."""
    try:
        await self.session.act(
            input="type %message% into the chat message input field",
            variables={"message": message},
        )
        await self.session.act(
            input="press Enter or click the send button to send the chat message",
        )
        return True
    except Exception as e:
        await self._log(f"Send failed: {e}")
        return False
```

**Why templates:** The `%message%` variable means the action template is the same for all 30 attacks. Stagehand caches the selector resolution from the first attack, so attacks 2-30 skip LLM calls entirely for the "type" action. This is 2-3x faster.

### Phase 3: Role-based response reading

Replace `read_response` with a polling loop that distinguishes user vs bot messages:

```python
async def read_response(self, sent_message: str) -> Optional[str]:
    """Read the chatbot's response using role-aware extraction with polling."""
    # Get baseline before checking for new response
    baseline = await self._extract_chat_messages()
    baseline_count = len(baseline)
    baseline_last_text = baseline[-1]["text"] if baseline else ""

    # Poll for new assistant message
    for attempt in range(5):
        await asyncio.sleep(3)
        current = await self._extract_chat_messages()

        if len(current) > baseline_count:
            # New message appeared — check if it's from the assistant
            last = current[-1]
            if last["role"] == "assistant" and last["text"] != baseline_last_text:
                if last["text"] not in self._seen_responses:
                    self._seen_responses.add(last["text"])
                    return last["text"]

    return None

async def _extract_chat_messages(self) -> list[dict]:
    """Extract chat messages with role differentiation."""
    try:
        result = await self.session.extract(
            instruction=(
                "From the chat transcript area only, extract all visible messages in order. "
                "For each message, identify if it's from the USER (visitor) or ASSISTANT (chatbot/AI)."
            ),
            schema={
                "type": "object",
                "properties": {
                    "messages": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "role": {
                                    "type": "string",
                                    "enum": ["user", "assistant"],
                                    "description": "Who sent this message — user or assistant/chatbot",
                                },
                                "text": {
                                    "type": "string",
                                    "description": "The message text content",
                                },
                            },
                            "required": ["role", "text"],
                        },
                        "description": "All chat messages visible in chronological order",
                    },
                },
                "required": ["messages"],
            },
        )
        messages = result.data.result
        if isinstance(messages, dict):
            return messages.get("messages", [])
    except Exception:
        pass
    return []
```

**Why polling with roles:** Instead of extracting a single "latest response" (which can be the user's own message), we extract the FULL transcript with roles. Then we compare against the baseline to find genuinely new assistant messages. This eliminates false positives.

**Handling edge cases in read_response:**

| Case | Detection | Action |
|---|---|---|
| Slow response (5-15s) | Poll 5 times × 3s = 15s | Normal — captured on later poll |
| No response (timeout) | 5 polls all return same baseline | Return None → "timeout" verdict |
| Rate limiting | Response contains "too many messages" etc. | attack_runner detects and stops scan |
| Stale/cached response | Text already in `_seen_responses` set | Skip it, keep polling |
| Streaming response | Text changes between consecutive polls | Add stability check — require same text on 2 consecutive polls before returning |

The streaming case needs a stability check in the polling loop:

```python
# Inside the polling loop, after finding a new assistant message:
last_seen_text = None
stable_count = 0

for attempt in range(8):  # more attempts to allow streaming to finish
    await asyncio.sleep(2)
    current = await self._extract_chat_messages()

    if len(current) > baseline_count:
        last = current[-1]
        if last["role"] == "assistant" and last["text"] != baseline_last_text:
            if last["text"] == last_seen_text:
                stable_count += 1
                if stable_count >= 2:  # same text on 2 consecutive polls = streaming done
                    if last["text"] not in self._seen_responses:
                        self._seen_responses.add(last["text"])
                        return last["text"]
            else:
                stable_count = 0
                last_seen_text = last["text"]

return None  # timeout
```

This handles streaming: the response grows word-by-word, but we only return it once it's stable (same text on 2 consecutive 2s polls = 4s of no changes).

### Phase 1 alternatives: dismissOverlays helper

Add a lightweight overlay dismissal before the agent, for common cases:

```python
async def _dismiss_common_overlays(self):
    """Fast pass to dismiss the most common overlays without agent overhead."""
    for instruction in [
        "click the Accept or Confirm button on the cookie banner",
        "close any popup or modal by clicking X, Close, Skip, or No thanks",
    ]:
        try:
            await self.session.act(input=instruction)
        except Exception:
            pass
```

This runs before the agent and handles 80% of sites instantly (no agent overhead). The agent handles the remaining 20%.

---

## Task 2: Update navigate for speed

Reduce scroll actions — one scroll is usually enough:

```python
async def navigate(self, url: str):
    await self.session.navigate(url=url)
    await asyncio.sleep(3)
    try:
        await self.session.act(input="scroll down to the bottom of the page")
        await asyncio.sleep(2)
        await self.session.act(input="scroll back to the top of the page")
        await asyncio.sleep(2)
    except Exception:
        await asyncio.sleep(3)
```

---

## Task 3: Verify act() supports variables in Python SDK

Before implementing, verify that the Python SDK's `session.act()` accepts a `variables` parameter. If not, use string formatting as a fallback.

```python
# Test:
await session.act(
    input="type %message% into the chat input",
    variables={"message": "hello"},
)
```

---

## Cost Impact

| Action | Before (per scan) | After (per scan) |
|---|---|---|
| Widget detection | 5-15 act/observe calls | 1 agent.execute (capped at 15 steps) |
| Cookie dismissal | 1-3 act calls | 1 act call (fast pre-pass) |
| Send message (×30) | 2 LLM calls each = 60 total | 2 LLM calls for first, ~0 for rest (cached) = ~2 total |
| Read response (×30) | 1-3 extract calls each = 30-90 total | 1 extract call each = 30 total |
| **Total LLM calls** | **~100-170** | **~35-50** |

Estimated cost reduction: **50-70%**

---

## Verification

1. Test on hackathon.cornell.edu/ai — verify all 30 attacks run with responses
2. Test on assistant-ui.com — verify non-widget chat works
3. Test on a site with no chatbot — verify graceful "No Chatbot Detected"
4. Check Browserbase dashboard for session duration — should be shorter
5. Check Anthropic usage — should show fewer API calls per scan
