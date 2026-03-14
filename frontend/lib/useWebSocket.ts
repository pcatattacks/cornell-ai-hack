"use client";

import { useState, useCallback, useRef } from "react";
import type { WSEvent, ScanReport, ScanState } from "./types";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws/scan";

export function useScanWebSocket() {
  const [events, setEvents] = useState<WSEvent[]>([]);
  const [state, setState] = useState<ScanState>("idle");
  const [report, setReport] = useState<ScanReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const startScan = useCallback((url: string) => {
    setEvents([]);
    setReport(null);
    setError(null);
    setState("scanning");

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ url }));
    };

    ws.onmessage = (event) => {
      const data: WSEvent = JSON.parse(event.data);
      setEvents((prev) => [...prev, data]);

      if (data.type === "scan_complete") {
        setReport((data as unknown as { report: ScanReport }).report);
        setState("complete");
        ws.close();
      }

      if (data.type === "error" && (data as unknown as { fatal: boolean }).fatal) {
        setError((data as unknown as { message: string }).message);
        setState("error");
        ws.close();
      }
    };

    ws.onerror = () => {
      setError("WebSocket connection failed. Is the backend running?");
      setState("error");
    };

    ws.onclose = () => {
      wsRef.current = null;
    };
  }, []);

  const reset = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
    }
    setEvents([]);
    setReport(null);
    setError(null);
    setState("idle");
  }, []);

  return { events, state, report, error, startScan, reset };
}
