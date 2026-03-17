"use client";

import { ScanInput } from "@/components/ScanInput";
import { ScanningView } from "@/components/ScanningView";
import { VulnerabilityReport } from "@/components/VulnerabilityReport";
import { useScanWebSocket } from "@/lib/useWebSocket";

export default function Home() {
  const { events, state, report, error, liveViewUrl, targetUrl, startScan, stopScan, reset } = useScanWebSocket();

  return (
    <main className="min-h-screen bg-white py-12 px-4">
      {state === "idle" && <ScanInput onStartScan={startScan} />}

      {state === "scanning" && (
        <ScanningView events={events} onStop={stopScan} liveViewUrl={liveViewUrl} targetUrl={targetUrl} />
      )}

      {state === "complete" && report && <VulnerabilityReport report={report} onReset={reset} />}

      {state === "error" && (
        <div className="w-full max-w-2xl mx-auto text-center">
          <div className="text-red-600 text-lg font-semibold mb-4">{error}</div>
          <button onClick={reset} className="px-6 py-2 bg-blue-600 text-white font-semibold rounded-lg hover:bg-blue-700">
            Try Again
          </button>
        </div>
      )}
    </main>
  );
}
