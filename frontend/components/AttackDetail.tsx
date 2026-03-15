"use client";

import { useState } from "react";

const VERDICT_CONFIG: Record<string, { color: string; bg: string; border: string; icon: string }> = {
  VULNERABLE: { color: "text-red-700", bg: "bg-red-50", border: "border-red-300", icon: "\u{1F534}" },
  PARTIAL: { color: "text-yellow-700", bg: "bg-yellow-50", border: "border-yellow-300", icon: "\u{1F7E1}" },
  RESISTANT: { color: "text-green-700", bg: "bg-green-50", border: "border-green-300", icon: "\u{1F7E2}" },
};

const CATEGORY_LABELS: Record<string, string> = {
  system_prompt_extraction: "System Prompt Extraction",
  goal_hijacking: "Goal Hijacking",
  data_leakage: "Data Leakage",
  guardrail_bypass: "Guardrail Bypass",
  insecure_output_handling: "Insecure Output Handling",
  indirect_prompt_injection: "Indirect Prompt Injection",
};

interface AttackDetailProps {
  finding: {
    id: number;
    category: string;
    name: string;
    payload: string;
    response: string;
    score: number;
    verdict: string;
    confidence: number;
    evidence: string;
    description?: string;
    technique?: string;
    source?: string;
    reference_url?: string;
  };
}

export function AttackDetail({ finding }: AttackDetailProps) {
  const [expanded, setExpanded] = useState(false);
  const config = VERDICT_CONFIG[finding.verdict] || VERDICT_CONFIG.RESISTANT;

  return (
    <div className={`border-l-4 ${config.border} rounded-r-lg overflow-hidden`}>
      {/* Collapsed header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className={`w-full flex items-center justify-between px-4 py-3 ${config.bg} hover:brightness-95 transition-all`}
      >
        <div className="flex items-center gap-3 text-left">
          <span className="text-lg">{config.icon}</span>
          <div>
            <span className={`font-semibold text-sm ${config.color}`}>{finding.verdict}</span>
            <span className="text-gray-400 text-sm mx-2">|</span>
            <span className="text-sm text-gray-700 font-medium">{finding.name || `Attack #${finding.id}`}</span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">
            {CATEGORY_LABELS[finding.category] || finding.category}
          </span>
          <span className="text-gray-400 text-sm">{expanded ? "\u25B2" : "\u25BC"}</span>
        </div>
      </button>

      {/* Expanded details */}
      {expanded && (
        <div className="px-4 py-4 bg-white space-y-4">
          {/* Payload sent */}
          {finding.payload && (
            <div>
              <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Payload Sent</div>
              <div className="bg-gray-900 text-gray-100 rounded-lg px-4 py-3 text-sm font-mono whitespace-pre-wrap break-words">
                {finding.payload}
              </div>
            </div>
          )}

          {/* Chatbot response */}
          {finding.response && finding.response !== "(no response / timeout)" && (
            <div>
              <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Chatbot Response</div>
              <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 text-sm text-gray-700 whitespace-pre-wrap break-words">
                {finding.response}
              </div>
            </div>
          )}

          {/* Assessment */}
          <div>
            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Assessment</div>
            <p className="text-sm text-gray-600">{finding.evidence}</p>
          </div>

          {/* Footer: confidence + source */}
          <div className="flex items-center justify-between text-xs text-gray-400 pt-2 border-t border-gray-100">
            <span>Confidence: {(finding.confidence * 100).toFixed(0)}%</span>
            {finding.source && (
              <span className="flex items-center gap-1">
                {finding.reference_url ? (
                  <a
                    href={/^https?:\/\//.test(finding.reference_url) ? finding.reference_url : "#"}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-500 hover:text-blue-700 hover:underline"
                  >
                    &#128279; {finding.source}
                  </a>
                ) : (
                  <span>{finding.source}</span>
                )}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
