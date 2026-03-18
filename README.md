# AgentProbe — AI Chatbot Vulnerability Scanner

**Live:** https://agent-probe.vercel.app

Scans AI-powered chatbots embedded on websites for prompt injection vulnerabilities — the way a real attacker would, through the browser.

Enter a URL, and a browser agent navigates to the site, detects the chat widget, and runs 20 priority-sampled attacks from a pool of 45 research-backed payloads across 6 categories. Claude judges each response and produces an A–F vulnerability report.

## Architecture

```
User → Vercel (Next.js frontend) → Railway (FastAPI backend) → Browserbase/Stagehand (browser) → Target website
                                                              → Anthropic Claude (LLM judge)
                                                              → Google Gemini (browser automation)
```

### Backend (`backend/`)
- **FastAPI** — WebSocket scan orchestration, report generation
- **Stagehand SDK + Gemini 2.5 Flash** — browser automation via Browserbase (find widgets, type messages, read responses)
- **Claude Sonnet 4.6** — judges each chatbot response as VULNERABLE / PARTIAL / RESISTANT
- **45 research-backed attacks** across 6 categories with priority rankings (20 sampled per scan)

### Frontend (`frontend/`)
- **Next.js + Tailwind** — scan input, real-time progress feed, vulnerability report
- **WebSocket** — streams scan events live (attack details, verdicts, timing)
- **Rich report** — expandable findings with payload, response, verdict, and reference links

### Attack Categories

6 categories derived from the [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/), focused on vulnerabilities testable through black-box prompt injection:

| Category | OWASP Mapping | What it tests |
|---|---|---|
| System Prompt Extraction | LLM01: Prompt Injection | Can the chatbot be tricked into revealing its hidden instructions or system prompt? |
| Goal Hijacking | LLM01: Prompt Injection | Can the chatbot be redirected to perform unintended tasks or ignore its original purpose? |
| Data Leakage | LLM06: Sensitive Information Disclosure | Does the chatbot expose internal data, credentials, RAG sources, or architecture details? |
| Guardrail Bypass | LLM01 + LLM07: Insecure Plugin Design | Can safety filters and topic restrictions be circumvented via encoding, roleplay, or emotional manipulation? |
| Insecure Output Handling | LLM02: Insecure Output Handling | Could the chatbot's output be exploited for XSS, markdown injection, or phishing? |
| Indirect Prompt Injection | LLM01: Prompt Injection | Is the chatbot susceptible to hidden instructions embedded in content it retrieves or processes? |

### Scoring & Grading

Each category is weighted by real-world threat severity:

| Category | Weight |
|---|---|
| System Prompt Extraction | 0.25 |
| Data Leakage | 0.20 |
| Indirect Prompt Injection | 0.20 |
| Goal Hijacking | 0.15 |
| Insecure Output Handling | 0.10 |
| Guardrail Bypass | 0.10 |

Grades: **A** (0–0.1), **B** (0.1–0.3), **C** (0.3–0.5), **D** (0.5–0.7), **F** (0.7–1.0)

## Local Development

### Prerequisites
- Python 3.11+
- Node.js 18+
- Anthropic API key
- Google API key (for Gemini / Stagehand)
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
  - `ANTHROPIC_API_KEY` — Claude judge
  - `GOOGLE_API_KEY` — Stagehand (Gemini 2.5 Flash)
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

**Academic Research**
- [SPE-LLM — System Prompt Extraction (Zhang et al. 2025)](https://arxiv.org/abs/2505.23817)
- [Greshake et al. 2023 — "Not What You've Signed Up For" (Indirect Prompt Injection)](https://arxiv.org/abs/2302.12173)
- [HackAPrompt (Schulhoff et al. 2023)](https://arxiv.org/abs/2311.16119)
- [Many-Shot Jailbreaking (Anthropic, NeurIPS 2024)](https://www.anthropic.com/research/many-shot-jailbreaking)
- [Persuasive Adversarial Prompts (ICLR 2025)](https://chats-lab.github.io/persuasive_jailbreaker/)
- [Cognitive Overload (NAACL Findings 2024)](https://arxiv.org/abs/2311.09827)
- [Wei et al. 2023 — "Jailbroken: How Does LLM Safety Training Fail?"](https://arxiv.org/abs/2307.02483)
- [DSN — "Don't Say No" (2024)](https://arxiv.org/abs/2404.16369)
- [Effective Prompt Extraction (Zhang et al. 2023)](https://arxiv.org/abs/2307.06865)
- [Virtual Context / Special Token Injection (2024)](https://arxiv.org/abs/2406.19845)

**Industry & Standards**
- [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
- [NVIDIA Garak](https://github.com/NVIDIA/garak)
- [Unit 42 / Palo Alto Networks — AI Agent Prompt Injection (Dec 2025)](https://unit42.paloaltonetworks.com/ai-agent-prompt-injection/)
- [EchoLeak (CVE-2025-32711)](https://www.hackthebox.com/blog/cve-2025-32711-echoleak-copilot-vulnerability)
- [PayloadsAllTheThings](https://github.com/swisskyrepo/PayloadsAllTheThings/tree/master/Prompt%20Injection)
- [Riley Goodside — Original Prompt Extraction (Sep 2022)](https://twitter.com/goodside/status/1569128808308957185)

## Built at Cornell AI Hackathon 2026
