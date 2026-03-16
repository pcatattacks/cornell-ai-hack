# Frontend — Next.js + Tailwind

## Stack

- Next.js 15 (App Router)
- Tailwind CSS
- TypeScript
- WebSocket for real-time scan progress

## Running

```bash
npm install
npm run dev        # http://localhost:3000
npm run build      # production build check
```

## File Structure

```
app/
  layout.tsx              — Root layout, metadata ("AgentProbe — AI Chatbot Security Scanner")
  page.tsx                — Main page: idle → scanning → complete → error states
  globals.css             — Tailwind imports
lib/
  types.ts                — WSEventType, WSEvent, CategoryDetail, ScanReport, ScanState
  useWebSocket.ts         — useScanWebSocket hook: startScan, stopScan, reset, buildPartialReport
components/
  ScanInput.tsx           — URL input + auth checkbox + Start Scan button
  ScanProgress.tsx        — Real-time scan feed with grouped attack blocks, timer, Stop Scan button
  AttackDetail.tsx        — Expandable finding: payload, response, verdict, reference link
  CategoryCard.tsx        — Per-category grade card using AttackDetail components
  VulnerabilityReport.tsx — Full report view with grades, "No Chatbot Detected" handling
  GradeBadge.tsx          — Color-coded A-F grade badge
```

## State Machine

```
idle → scanning → complete
                → error
```

- `idle`: ScanInput shown
- `scanning`: ScanProgress shown with live WebSocket events
- `complete`: VulnerabilityReport shown (or "No Chatbot Detected")
- `error`: Error message with "Try Again" button

## WebSocket Events (from backend)

- `scan_start` — scan initiated
- `widget_detected` / `widget_not_found` — chatbot detection result
- `prechat_status` — cookie/form handling
- `attack_sent` — attack payload + metadata (name, category, source, reference_url)
- `attack_response` — chatbot's response text
- `attack_verdict` — VULNERABLE/PARTIAL/RESISTANT + evidence
- `rate_limited` / `browser_died` — scan stopped early
- `scan_complete` — full report object
- `debug` — internal scanner state (togglable via "Hide debug" button)
- `error` — fatal error

## Key Features

- **Stop Scan**: Closes WebSocket, builds partial report client-side from collected events
- **Timer**: Live elapsed time + attack count (e.g., "⏱ 2:34 · 12/30 attacks")
- **Loading indicator**: Bouncing dots ("Working...") between events
- **Attack blocks**: Each attack is a card with header (name + category + reference link), debug logs, payload (→), response (←), and verdict
- **No Chatbot Detected**: Friendly message with suggestions when no widget found
- **JSON export**: Download full report with all attack metadata

## Environment Variables

- `NEXT_PUBLIC_WS_URL` — WebSocket URL to backend (default: `ws://localhost:8000/ws/scan`)

## Deployment

Auto-deploys to Vercel from `main` branch. Root directory: `frontend`.
