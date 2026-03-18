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
    <div className="w-full mx-auto">
      <div className="flex flex-col lg:flex-row gap-6" style={{ height: "calc(100vh - 48px)" }}>
        {/* Browser pane — 50%, vertically centered */}
        <div className="lg:flex-1 min-w-0 flex items-center">
          <BrowserLiveView url={targetUrl || ""} liveViewUrl={liveViewUrl} />
        </div>
        {/* Attack feed — 50% */}
        <div className="lg:flex-1 min-w-0 lg:h-full overflow-hidden">
          <ScanProgress events={events} onStop={onStop} />
        </div>
      </div>
    </div>
  );
}
