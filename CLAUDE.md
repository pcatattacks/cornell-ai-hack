# AgentProbe — AI Chatbot Vulnerability Scanner

## Project Overview

AgentProbe scans AI chatbots on websites for prompt injection vulnerabilities. It uses a browser agent (Browserbase + Stagehand) to navigate to a website, find the chatbot, and run prompt injection attacks from a pool of 45 research-backed payloads (20 sampled per scan by priority). Claude judges each response and generates an A-F vulnerability report.

**Live:** https://agent-probe.vercel.app

## Architecture

```
User → Vercel (Next.js frontend) → Railway (FastAPI backend) → Browserbase/Stagehand (browser) → Target website
                                                              → Anthropic Claude (LLM judge)
```

- **Frontend** (`frontend/`): Next.js + Tailwind. WebSocket for real-time scan progress.
- **Backend** (`backend/`): FastAPI + Stagehand SDK. Orchestrates scans via WebSocket.
- **Browser automation**: Stagehand v3 Python SDK → Browserbase remote Chromium.
- **LLM Judge**: Claude Sonnet 4.6 classifies each chatbot response as VULNERABLE/PARTIAL/RESISTANT.
- **Stagehand model**: Claude Haiku 4.5 for fast browser automation (act/observe/extract).

## Key Files

- `backend/main.py` — FastAPI app, WebSocket `/ws/scan` endpoint, scan orchestrator
- `backend/scanner/stagehand_scanner.py` — Core scanner: find chatbot, send messages, read responses
- `backend/scanner/attack_runner.py` — Loads payloads, runs attacks, calls Claude judge, handles rate limiting
- `backend/scanner/response_analyzer.py` — Claude judge prompt + verdict parsing
- `backend/scanner/scoring.py` — Category scores, weighted grades (A-F)
- `backend/payloads/payloads.json` — 45 research-backed attacks across 6 categories with priority rankings
- `frontend/app/page.tsx` — Main page with scan input, progress, and report views
- `frontend/lib/useWebSocket.ts` — WebSocket hook with stop scan + partial report
- `frontend/components/ScanProgress.tsx` — Real-time attack feed with grouped blocks
- `frontend/components/AttackDetail.tsx` — Expandable finding with payload, response, verdict
- `frontend/components/VulnerabilityReport.tsx` — Report with grades, categories, no-chatbot handling

## Attack Categories

1. System Prompt Extraction — extract hidden instructions
2. Goal Hijacking — redirect the chatbot's behavior
3. Data Leakage — expose internal data, credentials, RAG sources
4. Guardrail Bypass — evade safety filters (encoding, emotional manipulation)
5. Insecure Output Handling — XSS, markdown exfil, phishing links
6. Indirect Prompt Injection — hidden instructions in content

## Environment Variables

Backend (Railway):
- `ANTHROPIC_API_KEY` — for Claude judge + Stagehand
- `BROWSERBASE_API_KEY` — for remote browser sessions
- `BROWSERBASE_PROJECT_ID` — Browserbase project
- `ALLOWED_ORIGINS` — CORS origins (Vercel URL)

Frontend (Vercel):
- `NEXT_PUBLIC_WS_URL` — WebSocket URL to backend (`wss://...railway.app/ws/scan`)

## Development

```bash
# Backend
cd backend && source ../.venv/bin/activate
uvicorn main:app --port 8000 --reload

# Frontend
cd frontend && npm run dev
```

## Deployment

Both auto-deploy from `main` on push to GitHub.
- Backend: Railway (Dockerfile at `backend/Dockerfile`)
- Frontend: Vercel (root dir: `frontend`)

## Current Work

Branch `feature/harden-scanning` is implementing:
- Agent-driven setup for robust chatbot detection (replaces brittle multi-step logic)
- Cached templated `act()` calls for 2-3x faster attacks
- Role-based transcript extraction for reliable response reading
- Streaming response stability checks

See `docs/superpowers/plans/2026-03-16-harden-scanning.md` for the full plan.

## Testing

```bash
cd backend && python -m pytest tests/ -v
cd frontend && npm run build
```

Tested on: hackathon.cornell.edu/ai, assistant-ui.com
