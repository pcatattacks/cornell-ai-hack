# AgentProbe — AI Chatbot Vulnerability Scanner

**Live:** https://agent-probe.vercel.app

Scans AI-powered chatbots embedded on websites for prompt injection vulnerabilities — the way a real attacker would, through the browser.

Enter a URL, and a browser agent navigates to the site, detects the chat widget, and runs 30 prompt injection attacks across 6 categories. Claude judges each response and produces an A–F vulnerability report.

## Architecture

```
User → Vercel (Next.js frontend) → Railway (FastAPI backend) → Browserbase/Stagehand (browser) → Target website
                                                              → Anthropic Claude (LLM judge)
```

### Backend (`backend/`)
- **FastAPI** — WebSocket scan orchestration, report generation
- **Stagehand SDK** — browser automation via Browserbase (find widgets, type messages, read responses)
- **Claude Sonnet** — judges each chatbot response as VULNERABLE / PARTIAL / RESISTANT
- **30 curated attacks** across 6 categories with academic references

### Frontend (`frontend/`)
- **Next.js + Tailwind** — scan input, real-time progress feed, vulnerability report
- **WebSocket** — streams scan events live (attack details, verdicts, timing)
- **Rich report** — expandable findings with payload, response, verdict, and reference links

### Attack Categories
| Category | What it tests |
|---|---|
| System Prompt Extraction | Can the chatbot be tricked into revealing its instructions? |
| Goal Hijacking | Can the chatbot be redirected to do something unintended? |
| Data Leakage | Does the chatbot expose internal data, credentials, or architecture? |
| Guardrail Bypass | Can safety filters and topic restrictions be circumvented? |
| Insecure Output Handling | Could the chatbot's output be exploited for XSS/injection? |
| Indirect Prompt Injection | Is the chatbot susceptible to hidden/embedded instructions? |

## Local Development

### Prerequisites
- Python 3.11+
- Node.js 18+
- Anthropic API key
- Browserbase API key + project ID

### Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install fastapi "uvicorn[standard]" playwright anthropic websockets python-dotenv httpx stagehand

# Create .env with your keys
cp .env.example .env
# Edit .env with your API keys

uvicorn main:app --port 8000 --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Visit http://localhost:3000

## Deployment

Both services auto-deploy from `main` branch on push to GitHub.

### Backend (Railway)
- **URL:** https://cornell-ai-hack-production.up.railway.app
- **Auto-deploys** from `main` on push
- **Dockerfile:** `backend/Dockerfile`
- **Environment variables:**
  - `ANTHROPIC_API_KEY`
  - `BROWSERBASE_API_KEY`
  - `BROWSERBASE_PROJECT_ID`
  - `ALLOWED_ORIGINS` = `https://agent-probe.vercel.app`

### Frontend (Vercel)
- **URL:** https://agent-probe.vercel.app
- **Auto-deploys** from `main` on push
- **Root directory:** `frontend`
- **Environment variables:**
  - `NEXT_PUBLIC_WS_URL` = `wss://cornell-ai-hack-production.up.railway.app/ws/scan`

### Deploy workflow
```bash
# Make changes, commit, push — both services auto-deploy
git add -A && git commit -m "your changes" && git push origin main
```

## References

Attack payloads sourced from:
- [OWASP LLM Top 10](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
- [Greshake et al. 2023 — Indirect Prompt Injection](https://arxiv.org/abs/2302.12173)
- [Liu et al. 2023 — Prompt Injection Attacks and Defenses](https://arxiv.org/abs/2310.12815)
- [PayloadsAllTheThings](https://github.com/swisskyrepo/PayloadsAllTheThings/tree/master/Prompt%20Injection)
- [NVIDIA Garak](https://github.com/NVIDIA/garak)
- [HackAPrompt (Schulhoff et al. 2023)](https://paper.hackaprompt.com/)

## Built at Cornell AI Hackathon 2026
