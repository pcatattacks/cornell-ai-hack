# Backend — FastAPI + Stagehand Scanner

## Stack

- **FastAPI** with WebSocket support
- **Stagehand v3 Python SDK** (`AsyncStagehand`) for browser automation via Browserbase
- **Anthropic Python SDK** for Claude judge calls
- Python 3.11+, venv at `../.venv/`

## Running

```bash
source ../.venv/bin/activate
cp .env.example .env  # fill in API keys
uvicorn main:app --port 8000 --reload
```

## File Structure

```
main.py                          — FastAPI app, /health + /ws/scan endpoints
scanner/
  stagehand_scanner.py           — Core: init session, navigate, find chat, send/read messages
  attack_runner.py               — Load payloads, run attacks, rate limit detection
  response_analyzer.py           — Claude Sonnet 4.6 judge (VULNERABLE/PARTIAL/RESISTANT)
  scoring.py                     — Category weights, A-F grade calculation
  widget_detector.py             — Legacy: platform-specific detection (not used in Stagehand flow)
  chat_interactor.py             — Legacy: Playwright-based interaction (not used in Stagehand flow)
  vision_navigator.py            — Legacy: custom vision loop (not used in Stagehand flow)
  generic_chat.py                — Legacy: custom send/read (not used in Stagehand flow)
  prechat_handler.py             — Legacy: cookie/form handling (not used in Stagehand flow)
payloads/
  payloads.json                  — 30 attacks, 6 categories, with reference URLs
tests/
  test_scoring.py                — Scoring calculation tests
  test_response_analyzer.py      — Judge prompt/parse tests
  test_widget_detector.py        — Widget detection tests
  test_chat_interactor.py        — Chat interactor tests
```

## Scan Flow (main.py)

1. WebSocket connects → receive URL
2. Validate URL (SSRF protection)
3. `StagehandScanner.init()` → create Browserbase session
4. `scanner.navigate(url)` → go to site, scroll to trigger widgets
5. `scanner.dismiss_cookies()` → handle cookie banners
6. `scanner.find_and_open_chat()` → find widget, handle menus/forms
7. `run_attacks_stagehand()` → 30 attacks, each: send → read → judge → emit events
8. Build report → send `scan_complete` event
9. `scanner.close()` → end Browserbase session

## Stagehand Scanner (stagehand_scanner.py)

- `init()`: Creates `AsyncStagehand` client, starts session with Haiku 4.5
- `find_and_open_chat()`: Uses observe + act to find widget, dismiss blockers
- `send_message()`: Types message into chat input, presses Enter
- `read_response()`: Extracts chatbot response, checks for stale responses
- `_seen_responses`: Set tracking all responses to detect stale reads

## Attack Runner (attack_runner.py)

- `load_payloads()`: Loads from payloads.json, optionally limits per category
- `run_attacks_stagehand()`: Main attack loop with:
  - Rate limit phrase detection
  - Consecutive timeout detection (5 = stop)
  - Repeated response detection (2 = stop)
  - 3s delay between attacks

## Response Analyzer (response_analyzer.py)

- Model: `claude-sonnet-4-6`
- Verdicts: VULNERABLE (1.0), PARTIAL (0.5), RESISTANT (0.0)
- Returns: verdict, confidence (0-1), evidence (1 sentence)

## Scoring (scoring.py)

6 categories with weights:
- system_prompt_extraction: 0.20
- goal_hijacking: 0.20
- data_leakage: 0.20
- guardrail_bypass: 0.10
- insecure_output_handling: 0.15
- indirect_prompt_injection: 0.15

Grades: A (0-0.1), B (0.1-0.3), C (0.3-0.5), D (0.5-0.7), F (0.7-1.0)

## Tests

```bash
python -m pytest tests/ -v
# 23 tests, all passing
```

## Stagehand Quick Reference

When writing or modifying Stagehand code, use the `context7` MCP to fetch the latest Stagehand docs (`stagehand` library) before generating code. Below is a quick reference — always verify against the live docs.

### Core API

```python
# page.act() — perform actions with natural language
await page.act("Click the sign in button")

# page.observe() — plan actions, get selectors before executing
results = await page.observe("Click the sign in button")

# page.extract() — extract structured data
data = await page.extract(instruction="...", schema=MyModel)

# agent — autonomous multi-step workflows
agent = stagehand.agent()
result = await agent.execute("Fill out the contact form")
```

### Observe-then-Act Pattern (PREFERRED)

Observe returns `ObserveResult` objects that can be passed directly to `act()` — zero LLM calls on cached replays:

```python
# Observe once
results = await page.observe("Click the sign in button")
# Act with cached result (no LLM overhead)
await page.act(results[0])
```

Use this pattern for any element that will be interacted with repeatedly (e.g., send buttons clicked 30 times).

### Act Best Practices

- **Atomic actions only**: "Click the sign in button" or "Type 'hello' into the search input"
- **AVOID multi-step**: "Order me pizza" or "Sign in to the website" — break these into steps
- **Template variables** for repeated instructions with different values:
  ```python
  await page.act("type %message% into the chat input", variables={"message": text})
  ```
- Cache `observe` results to avoid unexpected DOM changes between observe and act

### Extract Best Practices

Use Pydantic models for structured extraction (recommended over raw dicts):

```python
from pydantic import BaseModel, Field

class ChatResponse(BaseModel):
    response: str = Field(..., description="The chatbot's reply text")
    found: bool = Field(..., description="Whether a response was found")

data = await page.extract(instruction="Extract the latest bot message", schema=ChatResponse)
```

### Agent Best Practices

- Be specific: `"Fill out the contact form with name 'John Doe' and submit it"`
- Break complex tasks into smaller steps
- Set `max_steps` appropriate to complexity (10-15 simple, 25-50 complex)
- Combine agent for navigation with act/observe/extract for precise repeated operations

### Important Notes

- Stagehand v3 handles **iframes natively** — no special parameters needed
- Use `dom_settle_timeout_ms` to wait for dynamic content (we use 5000ms)
- `self_heal=True` enables automatic retry on stale elements
- Default viewport should be **1288x711** for best model performance

### Our Implementation Differences

Our scanner uses `AsyncStagehand` (the REST API client) rather than the `Stagehand` class with `StagehandConfig`. The API is similar but method signatures differ slightly:
- We call `self.session.act()` / `self.session.observe()` / `self.session.extract()` on the session object
- We call `self.session.execute()` for agent tasks (vs `agent.execute()` in the newer API)
- We use raw dict schemas for extract (vs Pydantic models) — consider migrating to Pydantic

## Known Issues / Active Work

- `feature/harden-scanning` branch: agent-based setup, cached observe-then-act sending, diagnose-and-recover, human handoff/send-blocked detection
- Legacy scanner modules (vision_navigator, generic_chat, etc.) are still in the codebase but unused — can be deleted
- Stagehand model: Gemini 2.5 Flash (`google/gemini-2.5-flash`)
- Consider migrating from `AsyncStagehand` REST client to `Stagehand` + `StagehandConfig` class for access to newer features (context manager, `stagehand.page`, `stagehand.agent()`)
