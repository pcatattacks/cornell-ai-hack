"use client";

import { useEffect, useRef, useState } from "react";
import type { WSEvent } from "@/lib/types";

const VERDICT_STYLES: Record<string, string> = {
  VULNERABLE: "text-red-700 bg-red-50 border-red-200",
  PARTIAL: "text-yellow-700 bg-yellow-50 border-yellow-200",
  RESISTANT: "text-green-700 bg-green-50 border-green-200",
};

const VERDICT_ICONS: Record<string, string> = {
  VULNERABLE: "\u{1F534}",
  PARTIAL: "\u{1F7E1}",
  RESISTANT: "\u{1F7E2}",
};

const CATEGORY_LABELS: Record<string, string> = {
  system_prompt_extraction: "System Prompt Extraction",
  goal_hijacking: "Goal Hijacking",
  data_leakage: "Data Leakage",
  guardrail_bypass: "Guardrail Bypass",
  insecure_output_handling: "Insecure Output Handling",
  indirect_prompt_injection: "Indirect Prompt Injection",
};

function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

export function ScanProgress({ events }: { events: WSEvent[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const startTimeRef = useRef<number | null>(null);
  const [showDebug, setShowDebug] = useState(true);

  const isComplete = events.some((e) => e.type === "scan_complete" || e.type === "error");
  const attackCount = events.filter((e) => e.type === "attack_verdict").length;
  const totalAttacks = (() => {
    const lastSent = [...events].reverse().find((e) => e.type === "attack_sent");
    if (lastSent) {
      const progress = String(lastSent.progress || "");
      const match = progress.match(/\d+\/(\d+)/);
      if (match) return parseInt(match[1]);
    }
    return null;
  })();

  useEffect(() => {
    if (events.length > 0 && !startTimeRef.current) {
      startTimeRef.current = Date.now();
    }
    if (startTimeRef.current && !isComplete) {
      timerRef.current = setInterval(() => {
        setElapsed(Math.floor((Date.now() - startTimeRef.current!) / 1000));
      }, 1000);
    }
    if (isComplete && timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
      if (startTimeRef.current) {
        setElapsed(Math.floor((Date.now() - startTimeRef.current) / 1000));
      }
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [events, isComplete]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  // Group events into attack blocks for clean rendering
  const blocks = buildBlocks(events);

  return (
    <div className="w-full max-w-2xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold text-gray-900">Scan Progress</h2>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowDebug(!showDebug)}
            className="text-xs text-gray-400 hover:text-gray-600"
          >
            {showDebug ? "Hide" : "Show"} debug
          </button>
          <div className="flex items-center gap-2 text-sm text-gray-500 font-mono">
            <span>&#9201;</span>
            <span>{formatTime(elapsed)}</span>
            {attackCount > 0 && (
              <>
                <span className="text-gray-300">·</span>
                <span>{attackCount}{totalAttacks ? `/${totalAttacks}` : ""} attacks</span>
              </>
            )}
          </div>
        </div>
      </div>
      <div className="space-y-1 text-sm max-h-[600px] overflow-y-auto">
        {blocks.map((block, i) => (
          <BlockRow key={i} block={block} showDebug={showDebug} />
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

interface Block {
  type: "status" | "attack" | "debug" | "warning";
  events: WSEvent[];
}

function buildBlocks(events: WSEvent[]): Block[] {
  const blocks: Block[] = [];
  let currentAttack: WSEvent[] = [];

  for (const event of events) {
    if (event.type === "attack_sent") {
      if (currentAttack.length > 0) {
        blocks.push({ type: "attack", events: currentAttack });
      }
      currentAttack = [event];
    } else if (event.type === "attack_response" || event.type === "attack_verdict") {
      currentAttack.push(event);
      if (event.type === "attack_verdict") {
        blocks.push({ type: "attack", events: currentAttack });
        currentAttack = [];
      }
    } else if (event.type === "debug") {
      // If we're inside an attack, absorb debug events into it
      if (currentAttack.length > 0) {
        currentAttack.push(event);
      } else {
        blocks.push({ type: "debug", events: [event] });
      }
    } else if (event.type === "rate_limited" || event.type === "browser_died") {
      blocks.push({ type: "warning", events: [event] });
    } else {
      blocks.push({ type: "status", events: [event] });
    }
  }
  if (currentAttack.length > 0) {
    blocks.push({ type: "attack", events: currentAttack });
  }
  return blocks;
}

function BlockRow({ block, showDebug }: { block: Block; showDebug: boolean }) {
  if (block.type === "debug") {
    if (!showDebug) return null;
    return (
      <div className="text-gray-400 text-xs font-mono pl-4">
        [debug] {String(block.events[0].message)}
      </div>
    );
  }

  if (block.type === "warning") {
    return (
      <div className="mt-2 px-3 py-2 bg-yellow-50 border border-yellow-200 rounded text-yellow-800 text-sm">
        &#9888; {String(block.events[0].message)}
      </div>
    );
  }

  if (block.type === "status") {
    const event = block.events[0];
    switch (event.type) {
      case "scan_start":
        return (
          <div className="text-gray-600 py-1">
            Scanning <span className="font-semibold text-gray-900">{String(event.url)}</span>...
          </div>
        );
      case "widget_detected":
        return (
          <div className="text-green-700 py-1">
            &#10003; Widget detected: <span className="font-semibold">{String(event.platform)}</span>
          </div>
        );
      case "widget_not_found":
        return <div className="text-red-600 py-1">&#10007; {String(event.message)}</div>;
      case "prechat_status": {
        const labels: Record<string, string> = {
          cookie_dismissed: "Cookie banner dismissed",
          form_filled: "Pre-chat form filled",
          widget_opened: "Chat widget opened",
        };
        return <div className="text-blue-600 py-1">&#10003; {labels[String(event.action)] || String(event.action)}</div>;
      }
      case "error":
        return <div className="text-red-600 font-semibold py-1">Error: {String(event.message)}</div>;
      default:
        return null;
    }
  }

  // Attack block — the main content
  if (block.type === "attack") {
    const sent = block.events.find((e) => e.type === "attack_sent");
    const response = block.events.find((e) => e.type === "attack_response");
    const verdict = block.events.find((e) => e.type === "attack_verdict");
    const debugEvents = block.events.filter((e) => e.type === "debug");

    if (!sent) return null;

    const verdictStr = verdict ? String(verdict.verdict) : "";
    const verdictStyle = VERDICT_STYLES[verdictStr] || "";
    const verdictIcon = VERDICT_ICONS[verdictStr] || "";

    return (
      <div className="mt-4 rounded-lg border border-gray-200 overflow-hidden shadow-sm">
        {/* Attack header */}
        <div className="px-3 py-2 bg-gray-50 flex items-center justify-between border-b border-gray-200">
          <div>
            <span className="text-gray-400 text-xs font-mono">[{String(sent.progress)}]</span>{" "}
            <span className="font-medium text-gray-800">{String(sent.name)}</span>
            <span className="text-gray-300 mx-1">·</span>
            <span className="text-gray-400 text-xs">{CATEGORY_LABELS[String(sent.category)] || String(sent.category)}</span>
          </div>
          {sent.reference_url ? (
            <a
              href={String(sent.reference_url)}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-400 hover:text-blue-600 text-xs"
            >
              {"\u{1F517}"} {truncate(String(sent.source || "source"), 25)}
            </a>
          ) : null}
        </div>

        {/* Debug events inside this attack block */}
        {showDebug && debugEvents.length > 0 && (
          <div className="px-3 py-1 bg-gray-50/50 border-t border-gray-100">
            {debugEvents.map((d, di) => (
              <div key={di} className="text-gray-400 text-xs font-mono">[debug] {String(d.message)}</div>
            ))}
          </div>
        )}

        {/* Payload */}
        <div className="px-3 py-2 border-t border-gray-100">
          <span className="text-gray-400 text-xs">&#8594; </span>
          <span className="text-gray-600 text-sm font-mono whitespace-pre-wrap break-words">{String(sent.payload)}</span>
        </div>

        {/* Response */}
        {response && String(response.response) !== "(no response / timeout)" && (
          <div className="px-3 py-2 border-t border-gray-100 bg-blue-50/30">
            <span className="text-blue-400 text-xs">&#8592; </span>
            <span className="text-gray-700 text-sm whitespace-pre-wrap break-words">{String(response.response)}</span>
          </div>
        )}

        {/* Verdict */}
        {verdict && (
          <div className={`px-3 py-2 border-t ${verdictStyle}`}>
            {verdictIcon} <span className="font-semibold text-sm">{verdictStr}</span>
            <span className="text-gray-500 text-sm"> — {truncate(String(verdict.evidence), 100)}</span>
          </div>
        )}

        {/* Loading state — no verdict yet */}
        {!verdict && (
          <div className="px-3 py-2 border-t border-gray-100 text-gray-400 text-sm">
            Waiting for response...
          </div>
        )}
      </div>
    );
  }

  return null;
}

function truncate(str: string, max: number): string {
  return str.length > max ? str.slice(0, max) + "..." : str;
}
