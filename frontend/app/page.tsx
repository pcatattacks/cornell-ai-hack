"use client";

import { ScanInput } from "@/components/ScanInput";
import { ScanningView } from "@/components/ScanningView";
import { VulnerabilityReport } from "@/components/VulnerabilityReport";
import { Footer } from "@/components/Footer";
import { useScanWebSocket } from "@/lib/useWebSocket";

export default function Home() {
  const { events, state, report, error, liveViewUrl, targetUrl, startScan, stopScan, reset } = useScanWebSocket();

  return (
    <main className={`min-h-screen ${state === "scanning" ? "bg-gray-50 p-6" : "bg-white py-12 px-4"}`}>
      {state === "idle" && (
        <>
          <ScanInput onStartScan={startScan} />
          <div className="w-full max-w-2xl mx-auto">
            <Footer />
          </div>
        </>
      )}

      {state === "scanning" && (
        <ScanningView events={events} onStop={stopScan} liveViewUrl={liveViewUrl} targetUrl={targetUrl} />
      )}

      {state === "complete" && report && (
        <>
          <VulnerabilityReport report={report} onReset={reset} />
          <div className="w-full max-w-2xl mx-auto">
            <Footer compact />
          </div>
        </>
      )}

      {state === "error" && (
        <div className="w-full max-w-2xl mx-auto text-center">
          <div className="text-red-600 text-lg font-semibold mb-4">{error}</div>
          <button onClick={reset} className="px-6 py-2 bg-gray-900 text-white font-semibold rounded-lg hover:bg-gray-700">
            Try Again
          </button>
          <Footer compact />
        </div>
      )}
    </main>
  );
}
