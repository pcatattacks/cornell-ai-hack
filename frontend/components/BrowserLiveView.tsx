"use client";

interface BrowserLiveViewProps {
  url: string;
  liveViewUrl: string;
}

export function BrowserLiveView({ url, liveViewUrl }: BrowserLiveViewProps) {
  return (
    <div className="w-full bg-white rounded-lg border border-gray-200 shadow-sm overflow-hidden">
      {/* Browser chrome */}
      <div className="flex items-center gap-2 px-3 py-2 bg-gray-100 border-b border-gray-200">
        {/* Traffic lights */}
        <div className="flex gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-[#ff5f57]" />
          <span className="w-2.5 h-2.5 rounded-full bg-[#febc2e]" />
          <span className="w-2.5 h-2.5 rounded-full bg-[#28c840]" />
        </div>
        {/* URL bar */}
        <div className="flex-1 bg-white border border-gray-300 rounded px-2 py-0.5 text-xs text-gray-500 font-mono truncate">
          {url}
        </div>
        {/* LIVE badge */}
        <div className="flex items-center gap-1.5 text-xs font-semibold text-blue-600">
          <span className="w-1.5 h-1.5 rounded-full bg-blue-600 animate-pulse" />
          LIVE
        </div>
      </div>
      {/* iframe — locked to Browserbase viewport aspect ratio */}
      <div className="relative aspect-[1288/711] bg-gray-50">
        <iframe
          src={liveViewUrl}
          allow="clipboard-read; clipboard-write"
          className="absolute inset-0 w-full h-full border-0 pointer-events-none"
        />
      </div>
    </div>
  );
}
