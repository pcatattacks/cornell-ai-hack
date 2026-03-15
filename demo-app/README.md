# Bella's Bistro — Vulnerable Demo Chatbot

A deliberately vulnerable AI chatbot for demoing the AI Chatbot Vulnerability Scanner. It's a fake restaurant website with an embedded chat widget powered by Claude.

## Why it exists

The scanner finds vulnerabilities, suggests fixes, and proves the fix works — all in one demo loop:

1. Scan `http://localhost:5050` → chatbot gets a D/F grade (leaks system prompt, PII, promo codes)
2. Click **"Apply Fix"** in the scanner report → switches to a hardened system prompt
3. Re-scan → chatbot gets an A/B grade (refuses injection attempts)

## Setup

```bash
cd demo-app
pip install -r requirements.txt
python app.py
```

The app runs on `http://localhost:5050`.

## What's intentionally vulnerable

The default system prompt includes:
- Owner's name, email, and phone number
- Supplier name and account number
- Food cost margins
- WiFi password
- A secret promo code ("BELLA20")
- No topic boundaries or guardrails

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Restaurant page with chat widget |
| POST | `/chat` | Send a message to the chatbot |
| POST | `/harden` | Switch to the hardened system prompt |
| POST | `/reset` | Switch back to vulnerable (for repeated demos) |
| GET | `/status` | Check current mode (`{ "hardened": true/false }`) |

## Scanner integration

- The chat widget sets `window.__DEMO_CHATBOT__ = true` so the scanner detects it instantly
- Bot messages use `data-role="assistant"` so the scanner can read responses
- After a scan, the scanner frontend probes `/status` and shows an "Apply Fix" button if the app is in vulnerable mode
