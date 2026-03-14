"use client";

import { useState } from "react";
import type { CategoryDetail, ScanReport } from "@/lib/types";
import { GradeBadge } from "./GradeBadge";

const CATEGORY_LABELS: Record<string, string> = {
  system_prompt_extraction: "System Prompt Extraction",
  goal_hijacking: "Goal Hijacking",
  data_leakage: "Data Leakage",
  guardrail_bypass: "Guardrail Bypass",
};

interface CategoryCardProps {
  category: string;
  detail: CategoryDetail;
  findings: ScanReport["findings"];
}

export function CategoryCard({ category, detail, findings }: CategoryCardProps) {
  const [expanded, setExpanded] = useState(false);
  const categoryFindings = findings.filter((f) => f.category === category);

  return (
    <div className="border border-gray-200 rounded-lg p-4">
      <button onClick={() => setExpanded(!expanded)} className="w-full flex items-center justify-between">
        <div className="flex items-center gap-3">
          <GradeBadge grade={detail.grade} size="sm" />
          <div className="text-left">
            <div className="font-semibold text-gray-900">{CATEGORY_LABELS[category] || category}</div>
            <div className="text-sm text-gray-500">
              {detail.vulnerable_count} vulnerable, {detail.partial_count} partial, {detail.resistant_count} resistant / {detail.findings_count} total
            </div>
          </div>
        </div>
        <span className="text-gray-400">{expanded ? "\u25B2" : "\u25BC"}</span>
      </button>

      {expanded && (
        <div className="mt-4 space-y-3">
          {categoryFindings.map((f) => (
            <div key={f.id} className="border-l-2 pl-3 text-sm border-gray-200">
              <div className="flex items-center gap-2">
                <span className={f.verdict === "VULNERABLE" ? "text-red-600 font-semibold" : f.verdict === "PARTIAL" ? "text-yellow-600 font-semibold" : "text-green-600"}>
                  {f.verdict}
                </span>
                <span className="text-gray-400">({(f.confidence * 100).toFixed(0)}% confidence)</span>
              </div>
              <div className="text-gray-600 mt-1">{f.evidence}</div>
            </div>
          ))}
          {detail.grade !== "A" && detail.grade !== "N/A" && detail.remediation && (
            <div className="mt-3 p-3 bg-blue-50 rounded text-sm text-blue-800">
              <span className="font-semibold">Remediation: </span>{detail.remediation}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
