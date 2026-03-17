"use client";

import type { WSEvent } from "@/lib/types";
import { BrowserLiveView } from "./BrowserLiveView";
import { ScanProgress } from "./ScanProgress";

interface ScanningViewProps {
  events: WSEvent[];
  onStop?: () => void;
  liveViewUrl: string | null;
  targetUrl: string | null;
}

export function ScanningView({ events, onStop, liveViewUrl, targetUrl }: ScanningViewProps) {
  // Before live view URL arrives, show attack feed full-width (same as before)
  if (!liveViewUrl) {
    return (
      <div className="w-full max-w-2xl mx-auto">
        <ScanProgress events={events} onStop={onStop} />
      </div>
    );
  }

  return (
    <div className="w-full max-w-6xl mx-auto">
      <div className="flex flex-col lg:flex-row gap-4" style={{ height: "calc(100vh - 120px)" }}>
        {/* Browser pane — 60% */}
        <div className="lg:flex-[3] min-h-[300px] lg:min-h-0">
          <BrowserLiveView url={targetUrl || ""} liveViewUrl={liveViewUrl} />
        </div>
        {/* Attack feed — 40% */}
        <div className="lg:flex-[2] min-h-[300px] lg:min-h-0 overflow-hidden">
          <ScanProgress events={events} onStop={onStop} />
        </div>
      </div>
    </div>
  );
}
