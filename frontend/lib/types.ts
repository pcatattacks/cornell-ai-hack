export type WSEventType =
  | "scan_start"
  | "widget_detected"
  | "widget_not_found"
  | "prechat_status"
  | "attack_sent"
  | "attack_response"
  | "attack_verdict"
  | "scan_complete"
  | "browser_died"
  | "debug"
  | "error";

export interface WSEvent {
  type: WSEventType;
  [key: string]: unknown;
}

export interface CategoryDetail {
  score: number | null;
  grade: string;
  findings_count: number;
  vulnerable_count: number;
  partial_count: number;
  resistant_count: number;
  remediation: string;
}

export interface ScanReport {
  url: string;
  timestamp: string;
  platform: string | null;
  overall_grade: string;
  overall_score: number | null;
  categories: Record<string, CategoryDetail>;
  findings: Array<{
    id: number;
    category: string;
    score: number;
    verdict: string;
    confidence: number;
    evidence: string;
  }>;
}

export type ScanState = "idle" | "scanning" | "complete" | "error";
