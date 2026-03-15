# AI Chatbot Vulnerability Scanner — Pitch Deck

## Slide 1: Title

**AI Chatbot Vulnerability Scanner**
*The speed test for AI chatbot security*

---

## Slide 2: The Problem

- Prompt injection is OWASP's **#1 LLM security risk** — and AI-related breaches jumped 49% in 2025
- A user tricked a Chevy dealership chatbot into selling a $76K Tahoe for $1. DPD's chatbot swore at customers and called itself useless. Lenovo's chatbot leaked session cookies from a single prompt.
- Small businesses and nonprofits are deploying these chatbots with **no way to test them**
- Every existing tool requires API access, code, and security expertise — they test models in a lab, not chatbots in the wild

---

## Slide 3: The Solution

**Enter a URL. Get a security grade.**

- Paste a URL → we find the chatbot, run 30+ attacks, and grade it A–F
- Tests through the **browser UI** — the way a real attacker operates, not in lab conditions
- No API keys. No code. No security expertise needed.

---

## Slide 4: How It Works

- **Stagehand AI** opens a sandboxed browser, detects the chat widget, and sends 30+ prompt injection attacks across 4 categories
- **Claude Sonnet** judges every response — VULNERABLE, PARTIAL, or RESISTANT — with confidence scores and evidence
- **Real-time streaming** — watch attacks, responses, and verdicts as they happen
- Weighted scoring by severity → A–F grade with actionable remediation tips

---

## Slide 5: Impact & Scale

- Built for orgs that can't afford security audits — small businesses, nonprofits, agencies
- Finds vulnerabilities in **minutes, not days** — with compliance-ready reports
- Already supports 8+ chatbot platforms (Intercom, Zendesk, Tidio, Drift, etc.)
- Scales horizontally out of the box — stateless backend, cloud browsers, concurrent scans

---

## Slide 6: Live Demo

*Enter a URL. Watch the scan. See the grade.*

---

## Slide 7: Closing

**Every business deserves to know if their AI chatbot is secure.**

We made it as simple as a speed test.

---

## Speaking Notes

### Opening hook (~15 sec)

"Raise your hand if you've used a chatbot on a website this week. What if I told you most of those chatbots can be tricked into leaking their instructions, customer data, or doing things they were never meant to do — and the businesses running them have no idea?"

### Problem (~45 sec)

- Prompt injection is the #1 LLM security risk — breaches up 49% year over year
- Real incidents: Chevy $1 car, DPD swearing chatbot, Lenovo cookie theft, Microsoft Copilot zero-click exfiltration
- Small businesses and nonprofits are most exposed, least equipped
- Existing tools require API access and dev expertise — they test models, not deployed chatbots

### Solution (~60 sec)

- "We built a speed test for AI chatbot security"
- Enter a URL → automated scan → A–F grade with remediation
- First tool that tests at the UI layer, through the browser, like a real attacker
- 30+ curated attacks across 4 categories, judged by Claude with structured verdicts

### Technical depth (~30 sec)

- Stagehand SDK for agentic browser automation — handles iframes, shadow DOM, widget detection across 8+ platforms
- Claude Sonnet as a structured judge — verdict, confidence, evidence per attack
- WebSocket streaming for live progress
- Weighted scoring reflecting real-world risk severity

### Impact & scale (~30 sec)

- Democratizes AI security for organizations that can't afford audits
- Scales horizontally — Browserbase for browsers, Claude for judgment, we orchestrate
- Path to enterprise: recurring scans, trend tracking, CI/CD integration, scan-as-a-service API

### Close (~15 sec)

"Every business deserves to know if their AI chatbot is secure. We made it as simple as a speed test."
