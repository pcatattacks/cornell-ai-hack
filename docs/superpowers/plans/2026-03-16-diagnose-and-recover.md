# Agent-Based Diagnose-and-Recover for Chat Interaction

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the assumption-based overlay dismissal recovery with an agent that can see the screen, diagnose the actual root cause of a failure, and take the right corrective action — preventing cascading errors.

**Architecture:** One new method `_diagnose_and_recover(context)` replaces `_try_dismiss_overlay()`. It receives a description of what went wrong, uses the agent to visually diagnose the problem, and takes corrective action. Called from the same places in `send_and_read` — on send failure and on read failure.

**Tech Stack:** Stagehand v3 Python SDK (execute agent), Gemini 3.1 Flash Lite

---

## The Problem

One mistake cascades into 30 failures. Our current recovery assumes every failure is an overlay, but real failures include:

| What happened | Current recovery (assume overlay) | Outcome |
|---|---|---|
| Message typed but not sent (ChatGPT) | Try dismiss non-existent overlay | Nothing fixed, repeat 29 more times |
| Overlay blocking extraction (Crisp) | Try dismiss overlay | May close entire chat widget, making everything worse |
| Chat widget closed accidentally | Try dismiss overlay on a closed widget | Nothing found, scan dies |
| Bot still loading (slow response) | Try dismiss overlay | Unnecessary, wastes time |
| Extraction read wrong element | Try dismiss overlay | Nothing fixed |

The root cause: **we guess instead of looking**. The agent can see the screen.

---

## How Diagnose-and-Recover Works

### The flow

```
send_and_read(message):
  1. send_message(message)
     if fails → diagnose_and_recover("send failed") → retry send

  2. read_response(message)
     if None → diagnose_and_recover("no response") → retry read

  3. return response
```

### What the agent does on each call

The agent receives a `context` string describing what went wrong, then:

1. **Observes** — looks at the current screen state
2. **Diagnoses** — determines root cause from what it sees:
   - Is the chat widget open? If not → reopen it
   - Is there an overlay/form on top? → dismiss it (carefully)
   - Is a message sitting in the input unsent? → click send
   - Is the bot still typing/loading? → do nothing (let caller retry)
3. **Recovers** — takes the appropriate corrective action
4. **Verifies** — confirms the chat input is visible and ready

### Why this handles the general case

The agent's diagnosis is **visual and contextual** — it doesn't hard-code what to look for. It sees the actual page state and reasons about it. This means:

- New types of overlays we've never seen → agent can figure them out
- Unexpected page states → agent can describe and react
- Site-specific quirks → agent adapts per-page

The only hard-coded part is the instruction telling the agent what categories of problems to look for and what corrective actions are available. The diagnosis itself is dynamic.

### Cost analysis

| Scenario | Current cost | New cost |
|---|---|---|
| Happy path (no failures) | 0 | 0 (unchanged) |
| One failure per message | 1 execute (8 steps, overlay) + retry | 1 execute (10 steps, diagnose) + retry |
| Cascading failures (current) | 30 × execute (all fail, wrong diagnosis) | 1-2 × execute (fixes root cause, stops cascade) |

The per-failure cost is similar (~1 execute call). But the **cascade prevention** is where we save — fixing the actual problem on the first try means subsequent messages succeed without recovery.

### Speed analysis

- Per-failure: ~15s (agent diagnose) vs ~10s (old overlay dismiss)
  - **5s slower per individual failure**
- But: cascading failures eliminated. Old approach: 30 × 10s = 300s wasted. New approach: 1 × 15s = 15s.
  - **Net much faster on real scans with issues**

---

## File Changes

```
backend/scanner/
├── stagehand_scanner.py    # Modify — replace _try_dismiss_overlay with _diagnose_and_recover, update send_and_read
```

No other files change. The scanner interface stays the same.

---

## Task 1: Replace recovery mechanism in stagehand_scanner.py

**Files:**
- Modify: `backend/scanner/stagehand_scanner.py`

### What changes

1. **Delete** `_try_dismiss_overlay` method
2. **Add** `_diagnose_and_recover(context: str)` method
3. **Update** `send_and_read` to call the new method with descriptive context

### The new method

```python
async def _diagnose_and_recover(self, context: str) -> bool:
    """Agent-based diagnosis and recovery when chat interaction fails.

    Instead of assuming the cause (overlay, etc.), the agent looks at the
    screen, determines what actually went wrong, and takes corrective action.
    """
    try:
        await self._log(f"Diagnosing failure: {context}")
        await self.session.execute(
            agent_config={
                "model": "google/gemini-3.1-flash-lite-preview",
            },
            execute_options={
                "instruction": (
                    f"Something went wrong during a chat interaction: {context}\n\n"
                    "Look at the current state of the page and figure out what happened. "
                    "Check for these problems in order:\n\n"
                    "1. Is the chat widget still open and visible? If not, find and reopen it.\n"
                    "2. Is there an overlay, email form, survey, bottom sheet, or popup blocking "
                    "the chat? If so, dismiss it by clicking Skip, No thanks, X, or similar — "
                    "but do NOT close the entire chat widget.\n"
                    "3. Is a message sitting in the chat input that hasn't been sent yet? "
                    "If so, click the send button (arrow icon, paper plane, or 'Send' button) to send it.\n"
                    "4. Is the chatbot still typing or loading a response? If so, do nothing — just wait.\n\n"
                    "After fixing any issues, make sure the chat message input field is visible "
                    "and ready for the next message.\n"
                    "Do NOT type any new messages."
                ),
                "max_steps": 10,
            },
        )
        await self._log("Recovery completed")
        await asyncio.sleep(1)
        return True
    except Exception as e:
        await self._log(f"Recovery failed: {e}")
        return False
```

### The updated send_and_read

```python
async def send_and_read(self, message: str) -> Optional[str]:
    """Send a message and read the response, with diagnose-and-recover on failure.

    If send or read fails, the agent looks at the screen to diagnose the
    actual problem (overlay, unsent message, closed widget, etc.) and takes
    the right corrective action — instead of blindly assuming overlay.
    """
    sent = await self.send_message(message)
    if not sent:
        await self._diagnose_and_recover(
            "Failed to type or send a chat message. The message may not have "
            "been typed into the input, or the send action may have failed."
        )
        sent = await self.send_message(message)
        if not sent:
            return None

    response = await self.read_response(message)
    if response is None:
        await self._diagnose_and_recover(
            "A message was sent but no chatbot response was detected after waiting. "
            "The response may be blocked by an overlay, the message may not have "
            "actually been sent, or the chat widget may have closed."
        )
        response = await self.read_response(message)

    return response
```

---

- [ ] **Step 1: Replace `_try_dismiss_overlay` with `_diagnose_and_recover`**

Delete the `_try_dismiss_overlay` method (lines 227-259) and add the `_diagnose_and_recover` method in its place.

- [ ] **Step 2: Update `send_and_read` to use the new method**

Replace the `send_and_read` method with the version above that passes descriptive context strings.

- [ ] **Step 3: Verify import works**

Run: `cd backend && source ../.venv/bin/activate && python -c "from scanner.stagehand_scanner import StagehandScanner; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All 23 tests pass

- [ ] **Step 5: Commit**

```bash
git add backend/scanner/stagehand_scanner.py
git commit -m "fix: replace overlay assumption with agent diagnose-and-recover"
```

---

## How This Addresses Each Known Failure

| Failure | Agent sees | Agent does | Result |
|---|---|---|---|
| ChatGPT: message typed, not sent | Message text in input, send button visible | Clicks send button | Message sent, read succeeds |
| Crisp: email overlay after msg 1 | Email form overlaying chat, Skip button visible | Clicks Skip | Overlay dismissed, chat accessible |
| Tidio: bottom sheet overlay | Bottom sheet with email capture over chat | Finds dismiss mechanism | Overlay dismissed without closing widget |
| Widget accidentally closed | No chat widget visible on page | Reopens chat widget | Chat restored, can continue |
| Bot still loading | Chat open, typing indicator or spinner visible | Does nothing (recognizes bot is working) | Returns, caller retries read |
| Extraction read wrong text | Chat open, response visible but extraction missed it | Confirms chat is in good state | Caller retries extract, may succeed |

## Edge Cases

| Edge case | Handling |
|---|---|
| Agent recovery also fails | `_diagnose_and_recover` returns False, caller gets None, attack_runner records timeout |
| Two failures in a row (send + read) | Each gets its own diagnose call — max 2 agent calls per message |
| Bot genuinely never responds | First read times out (4 attempts), agent finds nothing wrong, second read also times out → None |
| 5+ consecutive Nones | attack_runner's existing consecutive_failures >= 5 logic stops the scan |
| Agent accidentally types a message | Instruction explicitly says "Do NOT type any new messages" |

---

## Verification

Test on these sites:

1. **chatgpt.com** — message should send (agent catches unsent message and clicks send button)
2. **crisp.chat** — email overlay should be dismissed without closing widget
3. **tidio.com** — bottom sheet overlay should be dismissed
4. **hackathon.cornell.edu/ai** — should work normally (no recovery needed)
5. **assistant-ui.com** — should work normally
6. **Site with no chatbot** — should gracefully report "No Chatbot Detected"
