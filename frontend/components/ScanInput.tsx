"use client";

import { useState } from "react";

interface ScanInputProps {
  onStartScan: (url: string) => void;
  disabled?: boolean;
}

export function ScanInput({ onStartScan, disabled }: ScanInputProps) {
  const [url, setUrl] = useState("");
  const [authorized, setAuthorized] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (url && authorized && !disabled) {
      onStartScan(url);
    }
  };

  return (
    <div className="w-full max-w-2xl mx-auto">
      <div className="text-center mb-8">
        <h1 className="text-4xl font-bold text-gray-900 mb-2">AgentProbe</h1>
        <p className="text-lg text-gray-600">
          Scan any AI chatbot for prompt injection vulnerabilities — the way a real attacker would.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="flex gap-2">
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="Enter website URL (e.g., https://example.com)"
            className="flex-1 px-4 py-3 border border-gray-300 rounded-lg text-lg text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            disabled={disabled}
          />
          <button
            type="submit"
            disabled={!url || !authorized || disabled}
            className="px-6 py-3 bg-blue-600 text-white font-semibold rounded-lg hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          >
            {disabled ? "Scanning..." : "Start Scan"}
          </button>
        </div>

        <label className="flex items-start gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={authorized}
            onChange={(e) => setAuthorized(e.target.checked)}
            className="mt-1 h-4 w-4 text-blue-600 rounded border-gray-300"
            disabled={disabled}
          />
          <span className="text-sm text-gray-600">
            I have authorization to perform security testing on this website.
          </span>
        </label>
      </form>

      <div className="mt-8 grid grid-cols-2 gap-4 text-sm text-gray-500">
        <div className="flex items-start gap-2">
          <span className="text-blue-500 mt-0.5">&#9679;</span>
          <span>Detects AI chatbot widgets (Intercom, Tidio, Zendesk, Crisp)</span>
        </div>
        <div className="flex items-start gap-2">
          <span className="text-blue-500 mt-0.5">&#9679;</span>
          <span>Runs 30+ prompt injection attacks across 4 categories</span>
        </div>
        <div className="flex items-start gap-2">
          <span className="text-blue-500 mt-0.5">&#9679;</span>
          <span>AI-powered analysis classifies each vulnerability</span>
        </div>
        <div className="flex items-start gap-2">
          <span className="text-blue-500 mt-0.5">&#9679;</span>
          <span>Generates a detailed security report with A-F grading</span>
        </div>
      </div>
    </div>
  );
}
