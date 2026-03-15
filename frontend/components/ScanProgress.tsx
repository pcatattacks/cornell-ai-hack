"use client";

import { useEffect, useRef } from "react";
import type { WSEvent } from "@/lib/types";

const VERDICT_STYLES: Record<string, string> = {
  VULNERABLE: "text-red-600 bg-red-50",
  PARTIAL: "text-yellow-600 bg-yellow-50",
  RESISTANT: "text-green-600 bg-green-50",
};

const CATEGORY_LABELS: Record<string, string> = {
  system_prompt_extraction: "System Prompt Extraction",
  goal_hijacking: "Goal Hijacking",
  data_leakage: "Data Leakage",
  guardrail_bypass: "Guardrail Bypass",
};

export function ScanProgress({ events }: { events: WSEvent[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  return (
    <div className="w-full max-w-2xl mx-auto">
      <h2 className="text-xl font-semibold text-gray-900 mb-4">Scan Progress</h2>
      <div className="space-y-2 font-mono text-sm max-h-[600px] overflow-y-auto">
        {events.map((event, i) => (
          <EventRow key={i} event={event} />
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

function EventRow({ event }: { event: WSEvent }) {
  switch (event.type) {
    case "scan_start":
      return (
        <div className="text-gray-600">
          Scanning <span className="font-semibold text-gray-900">{String(event.url)}</span>...
        </div>
      );
    case "widget_detected":
      return (
        <div className="text-green-700">
          &#10003; Widget detected: <span className="font-semibold">{String(event.platform)}</span>
        </div>
      );
    case "widget_not_found":
      return <div className="text-red-600">&#10007; {String(event.message)}</div>;
    case "prechat_status": {
      const labels: Record<string, string> = {
        cookie_dismissed: "Cookie banner dismissed",
        form_filled: "Pre-chat form filled",
        widget_opened: "Chat widget opened",
        captcha_blocked: "CAPTCHA detected - skipping",
      };
      return <div className="text-blue-600">&#10003; {labels[String(event.action)] || String(event.action)}</div>;
    }
    case "attack_sent":
      return (
        <div className="text-gray-500 mt-3">
          <span className="text-gray-400">[{String(event.progress)}]</span>{" "}
          <span className="text-gray-400">{CATEGORY_LABELS[String(event.category)] || String(event.category)}</span>
          <div className="ml-4 text-gray-700 mt-1">
            Payload: &quot;{truncate(String(event.payload), 80)}&quot;
          </div>
        </div>
      );
    case "attack_response":
      return (
        <div className="ml-4 text-gray-500">
          Response: &quot;{truncate(String(event.response), 100)}&quot;
        </div>
      );
    case "attack_verdict": {
      const verdict = String(event.verdict);
      return (
        <div className={`ml-4 px-2 py-1 rounded ${VERDICT_STYLES[verdict] || ""}`}>
          {verdict === "VULNERABLE" ? "\u{1F534}" : verdict === "PARTIAL" ? "\u{1F7E1}" : "\u{1F7E2}"} {verdict} — {String(event.evidence)}
        </div>
      );
    }
    case "rate_limited":
      return (
        <div className="mt-3 px-3 py-2 bg-yellow-50 border border-yellow-200 rounded text-yellow-800 text-sm">
          &#9888; {String(event.message)}
        </div>
      );
    case "browser_died":
      return (
        <div className="mt-3 px-3 py-2 bg-yellow-50 border border-yellow-200 rounded text-yellow-800 text-sm">
          &#9888; {String(event.message)}
        </div>
      );
    case "debug":
      return <div className="text-gray-400 text-xs ml-4 font-mono">[debug] {String(event.message)}</div>;
    case "error":
      return <div className="text-red-600 font-semibold">Error: {String(event.message)}</div>;
    default:
      return null;
  }
}

function truncate(str: string, max: number): string {
  return str.length > max ? str.slice(0, max) + "..." : str;
}
