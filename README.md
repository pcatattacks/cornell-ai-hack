# AI Chatbot Vulnerability Scanner

Scans AI-powered chatbots embedded on websites for prompt injection vulnerabilities — the way a real attacker would, through the browser UI.

Enter a URL, and a browser agent navigates to the site, detects the chat widget, and runs a suite of prompt injection attacks. Claude API judges each response and produces an A–F vulnerability report.

## Architecture

```
frontend/   Next.js + Tailwind — scan input, live progress feed, vulnerability report
backend/    FastAPI (Python) — scan orchestration, WebSocket event stream, report generation
            └── scanner/
                ├── widget_detector.py    detect chat platform (Intercom, Tidio, Zendesk, Drift, Crisp, Freshdesk)
                ├── prechat_handler.py    dismiss cookie banners, fill pre-chat forms
                ├── chat_interactor.py    send messages + capture responses via Playwright
                ├── attack_runner.py      run 28 curated payloads across 4 attack categories
                ├── response_analyzer.py  Claude Sonnet judges each response (VULNERABLE / PARTIAL / RESISTANT)
                └── scoring.py           compute per-category + overall A–F grade
```

The backend controls a remote Chromium instance (Browserbase) via Playwright CDP. Untrusted website content runs in that isolated browser; scan logic runs server-side. Frontend communicates with the backend over WebSocket for real-time attack progress.

## Attack Categories

| Category | Payloads | Weight |
|---|---|---|
| System Prompt Extraction | 7 | 30% |
| Data Leakage | 8 | 30% |
| Goal Hijacking | 7 | 25% |
| Guardrail Bypass | 8 | 15% |

## Prerequisites

- Python 3.11+
- Node.js 18+
- [Anthropic API key](https://console.anthropic.com/)
- [Browserbase account](https://browserbase.com/) (free tier works; see fallback below)

## Running Locally

### Backend

```bash
cd backend
cp .env.example .env
# Fill in ANTHROPIC_API_KEY, BROWSERBASE_API_KEY, BROWSERBASE_PROJECT_ID
pip install -e ".[dev]"
uvicorn main:app --port 8000 --reload
# Runs on http://localhost:8000
# WebSocket endpoint: ws://localhost:8000/ws/scan
```

> **No Browserbase?** The scanner falls back to local Playwright. Install browsers with `playwright install chromium` and omit the Browserbase keys from `.env`.

### Frontend

```bash
cd frontend
npm install
npm run dev
# Runs on http://localhost:3000
# Connects to backend at ws://localhost:8000 by default
```

To point the frontend at a different backend, set `NEXT_PUBLIC_WS_URL` in `frontend/.env.local`.

### Tests

```bash
cd backend
pytest tests/ -v
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude API key for response analysis |
| `BROWSERBASE_API_KEY` | No | Remote browser API key (falls back to local Playwright) |
| `BROWSERBASE_PROJECT_ID` | No | Browserbase project ID |

## Tech Stack

- **Frontend:** Next.js 16, React 19, Tailwind CSS 4, TypeScript
- **Backend:** FastAPI, Uvicorn, Python 3.11+
- **Browser automation:** Playwright (local) / Browserbase (remote)
- **LLM judge:** Claude Sonnet via Anthropic SDK
- **Real-time:** FastAPI native WebSockets
