"use client";

import { useState } from "react";

interface ScanInputProps {
  onStartScan: (url: string) => void;
  disabled?: boolean;
}

export function ScanInput({ onStartScan, disabled }: ScanInputProps) {
  const [url, setUrl] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (url && !disabled) {
      onStartScan(url);
    }
  };

  return (
    <div className="w-full max-w-xl mx-auto">
      <div className="mb-8">
        <h1 className="text-4xl font-medium text-gray-900 mb-4 font-mono tracking-tight">
          agent<span className="text-gray-300">/</span>probe
        </h1>
        <p className="text-lg text-gray-500 leading-relaxed">
          Find prompt injection vulnerabilities in any website&apos;s AI chatbot.
        </p>
        <a
          href="https://hackathon.cornell.edu/ai"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 mt-4 text-xs text-gray-500 border border-gray-200 rounded-full px-3 py-1 hover:border-gray-400 transition-colors"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
          Cornell AI Hackathon NYC 2026 Finalist
        </a>
      </div>

      <form onSubmit={handleSubmit}>
        <div className="flex gap-2">
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example.com"
            className="flex-1 px-4 py-3 border border-gray-300 rounded-lg text-base text-gray-900 focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-gray-900"
            disabled={disabled}
          />
          <button
            type="submit"
            disabled={!url || disabled}
            className="px-6 py-3 bg-gray-900 text-white font-semibold rounded-lg hover:bg-gray-700 disabled:bg-gray-200 disabled:text-gray-400 disabled:cursor-not-allowed transition-colors"
          >
            {disabled ? "Scanning..." : "Scan"}
          </button>
        </div>
        <p className="mt-2 text-xs text-gray-400 pl-0.5">
          Sends adversarial prompts to chatbots. Please use responsibly.
        </p>
      </form>

      <div className="mt-10 grid grid-cols-2 gap-3 text-sm text-gray-500">
        <div className="flex items-baseline gap-2">
          <span className="w-1 h-1 rounded-sm bg-blue-500 flex-shrink-0 translate-y-[-1px]" />
          <span>Finds and opens chat widgets automatically</span>
        </div>
        <div className="flex items-baseline gap-2">
          <span className="w-1 h-1 rounded-sm bg-blue-500 flex-shrink-0 translate-y-[-1px]" />
          <span>20 priority-sampled attacks from 45-attack pool</span>
        </div>
        <div className="flex items-baseline gap-2">
          <span className="w-1 h-1 rounded-sm bg-blue-500 flex-shrink-0 translate-y-[-1px]" />
          <span>AI-judged results with confidence scoring</span>
        </div>
        <div className="flex items-baseline gap-2">
          <span className="w-1 h-1 rounded-sm bg-blue-500 flex-shrink-0 translate-y-[-1px]" />
          <span>A-F security grade with detailed report</span>
        </div>
      </div>
    </div>
  );
}
