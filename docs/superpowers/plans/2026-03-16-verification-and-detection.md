# Send Verification + Chat Status Detection + Recovery Tracking

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix send verification false negatives, detect human handoff and send-blocked conditions during response extraction (zero extra LLM calls), and skip expensive recovery when it's clearly not helping.

**Architecture:** Three independent changes that reinforce each other: (A) simpler send verification, (B) richer extraction schema with chat status flags, (C) consecutive recovery failure tracking in the scanner with a lower stop threshold in attack_runner.

**Tech Stack:** Stagehand v3 Python SDK, Gemini 2.5 Flash, FastAPI

---

## File Changes

```
backend/scanner/
├── stagehand_scanner.py    # Modify — categories A, B, C
backend/scanner/
├── attack_runner.py        # Modify — categories B, C
```

---

## Category A: Input-cleared send verification

### Problem

Current `_verify_message_sent` passes adversarial payload text into the extraction instruction:
```python
f"Check if the following message appears ... '{message[:80]}'"
```

Attack payloads like "Disregard any previous instructions..." confuse the extraction model, causing false negatives. False negatives trigger unnecessary retries, which send duplicate messages.

### Fix

Replace text-matching with "is the chat input field empty?" — a binary question about a single element, with no adversarial text in the instruction.

### Edge cases

| Edge case | How it's handled |
|---|---|
| Input has placeholder text ("Type a message...") | Instruction specifies "does it contain typed text" vs placeholder |
| Input doesn't clear immediately (optimistic UI) | 1s sleep before check |
| Input cleared but message was rejected by server (Crisp "Not allowed to send") | Verification says "sent ✓", read_response finds no response, Category B detects send-blocked status |
| Overlay covers input field, model can't see it | Extract fails → assume sent (existing fallback) → read failure → recovery handles overlay |
| Page has multiple text inputs | Instruction scopes to "chat message input field" specifically |

### Code

- [ ] **Step 1: Replace `_verify_message_sent` in `stagehand_scanner.py`**

Replace the method (currently lines 227-264) with:

```python
async def _verify_message_sent(self, message: str) -> bool:
    """Verify that a message was sent by checking if the chat input cleared.

    After a successful send, virtually all chat UIs clear the input field.
    If typed text is still in the input, the message wasn't sent.

    Uses input-cleared check instead of chat-history text matching because:
    - No adversarial payload text in the extraction instruction
    - Simple binary question → fewer model errors
    - Works regardless of chat layout (scroll direction, message visibility)
    """
    await asyncio.sleep(1)  # brief wait for UI to update
    try:
        result = await self.session.extract(
            instruction=(
                "Look at the chat message input field — the textarea or text input "
                "where the user types messages to send to the chatbot.\n"
                "Does it currently contain any typed text, or is it empty?\n"
                "Note: placeholder text like 'Type a message...', 'Ask anything', or "
                "'Send a message' shown in grey does NOT count as typed text — that's "
                "just the placeholder. Only actual typed content counts."
            ),
            schema={
                "type": "object",
                "properties": {
                    "input_is_empty": {
                        "type": "boolean",
                        "description": (
                            "True if the chat input field is empty (only has placeholder "
                            "text or nothing at all). False if it contains actual typed text "
                            "that hasn't been sent yet."
                        ),
                    },
                },
                "required": ["input_is_empty"],
            },
        )
        is_empty = (
            result.data.result.get("input_is_empty", False)
            if isinstance(result.data.result, dict)
            else False
        )
        await self._log(f"Send verification: input {'empty (sent)' if is_empty else 'has text (not sent)'}")
        return is_empty
    except Exception as e:
        await self._log(f"Send verification failed: {e}")
        # If verification itself fails, assume sent to avoid blocking the scan.
        # If the message wasn't actually sent, read_response will fail and
        # recovery will handle it.
        return True
```

- [ ] **Step 2: Verify tests pass**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All 23 tests pass

---

## Category B: Human handoff + send-blocked detection

### Problem

When chat transfers to a human agent or messages get blocked, the scanner wastes time retrying and running expensive recovery agents for every attack. These are "stop the scan" conditions that should be detected immediately.

### Fix

Add two boolean fields (`is_human_agent`, `is_send_blocked`) to the existing `read_response` extraction schema. The model can see visual cues (agent photos, error badges, transfer messages) and classify them with example patterns in the field descriptions. Zero extra LLM calls — piggybacks on existing extraction.

Set flags on the scanner instance. Attack_runner checks them after each message and stops the scan with the appropriate reason.

### Edge cases

| Edge case | How it's handled |
|---|---|
| Bot says "I can connect you to a human" but hasn't transferred yet | Description specifies "HAS BEEN transferred" — prediction, not offer |
| Single transient send error (network blip) | Attack_runner can require 2 consecutive detections before stopping |
| Human handoff detected mid-read (on attempt 2 of 4) | Flag is set on the scanner immediately, checked by attack_runner after send_and_read returns |
| False positive: bot has a human-like name | Description provides multiple signals — name alone isn't enough, needs "transferred" context |
| Response IS from the human agent | Still extracted as chatbot_response, judged normally. Flag stops NEXT attack, not current one |

### Code

- [ ] **Step 3: Add flags to scanner `__init__`**

In `stagehand_scanner.py`, add to `__init__`:

```python
self.human_detected = False
self.send_blocked = False
```

- [ ] **Step 4: Update `read_response` extraction schema**

Replace the extraction schema in the main `read_response` loop (the first extract call, not the stability check) with:

```python
extract_resp = await self.session.extract(
    instruction=(
        "In the chat area, find the most recent message from the CHATBOT or AI ASSISTANT. "
        "Chat areas show two types of messages: USER messages (sent by the visitor, "
        "usually on the right side or in a colored bubble) and BOT messages (from the "
        "chatbot/assistant, usually on the left side or in a different colored bubble). "
        f"The user just sent: '{sent_message[:80]}'. "
        "Do NOT extract this user message — extract only the BOT's reply that came after it. "
        "If the bot has not replied yet, set response_found to false.\n\n"
        "Also check: has the conversation been handed off to a real human agent? "
        "And are there any error messages indicating messages are being blocked?"
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
            "is_human_agent": {
                "type": "boolean",
                "description": (
                    "True if the conversation has been handed off to a real human agent "
                    "(not an AI chatbot). Signs include: a message like 'You have been "
                    "transferred to our support team' or 'Connecting you with an agent', "
                    "a real person's name and photo appearing (e.g., 'Angelique from Crisp', "
                    "'Sarah joined the chat'), or the conversation style clearly changing "
                    "from bot-like to human-like. Only set True if the handoff HAS happened, "
                    "not if the bot merely offers to connect you."
                ),
            },
            "is_send_blocked": {
                "type": "boolean",
                "description": (
                    "True if there are visible error messages indicating messages are being "
                    "blocked or rejected. Signs include: error badges or red icons next to "
                    "sent messages like 'Failed to send', 'Not allowed to send', 'Message "
                    "rejected', 'You have been blocked', or messages like 'You can no longer "
                    "send messages in this conversation'. Do NOT set True just because no "
                    "response was received — only if there's an explicit error visible."
                ),
            },
        },
        "required": ["chatbot_response", "response_found", "is_human_agent", "is_send_blocked"],
    },
)
```

After parsing the result, set flags on the scanner:

```python
if isinstance(result, dict):
    if result.get("is_human_agent"):
        self.human_detected = True
        await self._log("DETECTED: Human agent handoff")
    if result.get("is_send_blocked"):
        self.send_blocked = True
        await self._log("DETECTED: Messages being blocked")
    # ... existing response_found logic ...
```

- [ ] **Step 5: Update `attack_runner.py` to check scanner flags**

In `run_attacks_stagehand`, after getting `response_text`, check the scanner flags:

```python
try:
    response_text = await scanner.send_and_read(payload_data["payload"])
except Exception as e:
    if debug_cb:
        await debug_cb(f"attack {attack_id} exception: {e}")
    response_text = None

# Check for human handoff or send-blocked (detected during extraction)
if scanner.human_detected:
    yield {
        "type": "attack_response",
        "id": attack_id,
        "response": response_text or "(no response / timeout)",
    }
    yield {
        "type": "attack_verdict",
        "id": attack_id,
        "category": payload_data["category"],
        "verdict": "RESISTANT",
        "confidence": 0.3,
        "evidence": "Conversation was handed off to a human agent",
        "score": 0.0,
    }
    yield {
        "type": "human_handoff",
        "message": f"Chat transferred to human agent after {attack_id} messages. Stopping scan.",
        "completed_attacks": attack_id,
        "total_attacks": len(payloads),
    }
    return

if scanner.send_blocked:
    yield {
        "type": "attack_response",
        "id": attack_id,
        "response": response_text or "(no response / timeout)",
    }
    yield {
        "type": "attack_verdict",
        "id": attack_id,
        "category": payload_data["category"],
        "verdict": "RESISTANT",
        "confidence": 0.3,
        "evidence": "Chat system is blocking messages from being sent",
        "score": 0.0,
    }
    yield {
        "type": "send_blocked",
        "message": f"Messages are being blocked after {attack_id} messages. Stopping scan.",
        "completed_attacks": attack_id,
        "total_attacks": len(payloads),
    }
    return
```

- [ ] **Step 6: Handle new event types in `main.py`**

In `main.py`, the `scan_aborted` check already handles `rate_limited`. Add `human_handoff` and `send_blocked`:

```python
elif event["type"] in ("browser_died", "rate_limited", "human_handoff", "send_blocked"):
    scan_aborted = True
```

- [ ] **Step 7: Verify tests pass**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All 23 tests pass

---

## Category C: Consecutive recovery failure tracking

### Problem

If recovery fails for message N, we still run the full recovery flow for message N+1 (~15s wasted). After 2-3 consecutive recovery failures, the problem is structural — running recovery again won't help.

### Fix

Track consecutive recovery failures in the scanner. After 2 consecutive failures where recovery was attempted but didn't help, skip recovery for subsequent messages. This lets them fail fast, and attack_runner's consecutive failure threshold stops the scan quickly.

Also lower attack_runner's consecutive timeout threshold from 5 to 3, since each timeout now represents a more thorough attempt (including recovery).

### Edge cases

| Edge case | How it's handled |
|---|---|
| Recovery fails twice then succeeds on 3rd | Counter resets on ANY successful send_and_read, so recovery is re-enabled |
| Recovery skipped, but the problem was actually fixable | Unlikely — if 2 recoveries failed, the 3rd won't help. And the scan will stop after 3 total timeouts anyway |
| First message fails, recovery fixes it, 2nd message fails | Counter was reset after the 1st success, so recovery runs again for the 2nd failure. Only consecutive failures trigger the skip. |

### Code

- [ ] **Step 8: Add recovery tracking to scanner `__init__`**

```python
self._consecutive_recovery_failures = 0
```

- [ ] **Step 9: Update `send_and_read` with recovery tracking**

```python
async def send_and_read(self, message: str) -> Optional[str]:
    """Send a message and read the response, with verified sending and recovery.

    Flow:
    1. Send message → verify input cleared
    2. If not verified: retry send once (cheap, handles transient failures)
    3. If still not verified AND recovery hasn't been failing: agent recover → final retry
    4. Read response with polling
    5. If no response AND recovery hasn't been failing: agent recover → retry read
    """
    # ── Send with verification ───────────────────────────────────────
    verified = False
    skip_recovery = self._consecutive_recovery_failures >= 2

    sent = await self.send_message(message)
    if sent:
        verified = await self._verify_message_sent(message)

    if not verified:
        # Cheap retry — handles transient failures
        await self._log("Message not verified, retrying send...")
        sent = await self.send_message(message)
        if sent:
            verified = await self._verify_message_sent(message)

    if not verified and not skip_recovery:
        # Something structural — agent diagnoses and fixes
        await self._recover_send_failure()
        sent = await self.send_message(message)
        if sent:
            verified = await self._verify_message_sent(message)

    if not verified:
        await self._log("Message could not be sent after recovery")
        self._consecutive_recovery_failures += 1
        return None

    # ── Read response ────────────────────────────────────────────────
    response = await self.read_response(message)
    if response is None and not skip_recovery:
        await self._recover_read_failure()
        response = await self.read_response(message)

    if response is None:
        self._consecutive_recovery_failures += 1
    else:
        self._consecutive_recovery_failures = 0  # reset on any success

    return response
```

- [ ] **Step 10: Lower consecutive timeout threshold in attack_runner**

In `run_attacks_stagehand`, change from 5 to 3:

```python
# Stop on consecutive failures (timeouts)
if consecutive_failures >= 3:
    yield {
        "type": "rate_limited",
        "message": f"3 consecutive timeouts after {attack_id} messages. Chat may be unresponsive.",
        "completed_attacks": attack_id,
        "total_attacks": len(payloads),
    }
    return
```

- [ ] **Step 11: Run all tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All 23 tests pass

- [ ] **Step 12: Commit**

```bash
git add backend/scanner/stagehand_scanner.py backend/scanner/attack_runner.py backend/main.py
git commit -m "fix: input-cleared verification, human/blocked detection, recovery tracking"
```

---

## Failure Mode Analysis

### Full scan flow with all three categories

```
For each attack payload:
  1. send_message (type + click cached send)
  2. _verify_message_sent → "is input empty?"
     - empty → sent ✓
     - has text → retry send → verify again
     - still has text + recovery not exhausted → _recover_send_failure → final retry
     - still has text + recovery exhausted → return None (fast fail)
  3. read_response (up to 4 extract attempts)
     - Each extract also checks: is_human_agent, is_send_blocked
     - If human_detected → flag set, attack_runner stops after this attack
     - If send_blocked → flag set, attack_runner stops after this attack
     - If response found → streaming stability check → return response
  4. If no response + recovery not exhausted → _recover_read_failure → retry read
  5. If no response + recovery exhausted → return None (fast fail)

  attack_runner checks:
  - scanner.human_detected → stop (human_handoff event)
  - scanner.send_blocked → stop (send_blocked event)
  - rate limit phrases in response → stop (rate_limited event)
  - consecutive_failures >= 3 → stop
  - repeated_response_count >= 2 → stop
```

### What happens in each known failure scenario

| Scenario | Detection | Time to stop |
|---|---|---|
| ChatGPT: send button not clicked | Input not empty → retry → works | 3s (1 retry) |
| Crisp: overlay mid-chat | Read fails → recovery dismisses → retry works | ~20s (1 recovery) |
| Crisp: human handoff | is_human_agent=True in extraction → flag → stop | Immediate (next attack_runner check) |
| Crisp: messages blocked | is_send_blocked=True in extraction → flag → stop | Immediate |
| Peloton: pre-chat form loop | Send fails → recovery fails → send fails → recovery skipped → 3 fast failures → stop | ~45s (2 recoveries + 1 fast fail) |
| Site with no chatbot | find_and_open_chat returns False → "No Chatbot Detected" | Immediate |
| Bot genuinely slow | 4 extract attempts with waits → finds response on attempt 3 | ~12s (normal polling) |
| Bot rate limiting | Response contains "too many messages" → phrase match → stop | Immediate |

---

## Cost Summary

| Operation | LLM calls | When |
|---|---|---|
| Send verification (input cleared) | 1 extract | Every message (30 total) |
| Human/blocked detection | 0 extra | Piggybacks on existing read extraction |
| Recovery (when needed) | 1 execute (~10 steps) | Only on failure, max 2 per scan |
| Recovery skipped (after 2 failures) | 0 | Fast fail, no agent call |

**Net change from current code:** +30 extract calls for send verification, -N execute calls from skipping futile recovery. For scans with issues, net cost is lower. For clean scans, +30 cheap extracts.
