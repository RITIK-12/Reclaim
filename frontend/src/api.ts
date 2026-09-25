import { useEffect, useState } from "react";

export type Status =
  | "QUEUED" | "RECEIVED" | "INSPECTING" | "PRICING" | "DECIDING"
  | "ESCALATED" | "EXECUTING" | "CLOSED" | "FAILED" | "ERROR";

export interface CaseRow {
  case_id: string; key: string; sku: string; title: string; category: string; list_price: number;
  reason_text: string; reason_category: string; received_at_ms: number; photo: string | null;
  status: Status; last_summary: string; action: string | null; decided_by: string | null;
  uplift: number | null; fraud_flag: boolean | null; precedent_ref: string | null; fraud_suspected: boolean;
}

export interface TimelineItem { ts_ms: number; agent: string; type: string; summary: string; payload: any }

export interface CaseDetail {
  case_id: string; status: Status; return: any; order: any; product: any;
  inspection: any | null; market: any | null; evidence: any[]; decision: any | null;
  escalation: any | null; human: any | null; execution: any | null; unit: any | null;
  timeline: TimelineItem[];
}

export interface Kpis {
  run_id: string; received: number; closed: number; auto_resolved_pct: number; escalated: number;
  pending_human: number; fraud_flags: number; uplift_vs_liquidate: number; avg_case_secs: number | null;
  llm_calls: number; avg_llm_ms: number; avg_brief_tokens: number; ledger_events: number;
  web_searches: number; cache_hits: number;
}

export const ACTIONS = ["RESTOCK", "REFURBISH", "RETURN_TO_VENDOR", "LIQUIDATE"] as const;

export async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

/** Poll an endpoint every `ms`. Returns data only for the current path (null while a new path loads).
 *  Each effect run owns its own `active` flag, so a poller for an old path can never reschedule itself. */
export function usePoll<T>(path: string | null, ms = 1200): T | null {
  const [state, setState] = useState<{ path: string | null; data: T | null }>({ path: null, data: null });
  useEffect(() => {
    if (!path) return;
    let active = true;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const d = await getJSON<T>(path);
        if (active) setState({ path, data: d });
      } catch { /* keep the last good data */ }
      if (active) timer = window.setTimeout(tick, ms);
    };
    tick();
    return () => { active = false; window.clearTimeout(timer); };
  }, [path, ms]);
  return state.path === path ? state.data : null;
}

export const img = (name?: string | null) => (name ? `/api/images/${name}` : "");
export const usd = (v?: number | null, digits = 0) =>
  v === null || v === undefined ? "—" : `${v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits })}`;
export const pretty = (s?: string | null) => (s ? s.replaceAll("_", " ").toLowerCase() : "");
export const domain = (url: string) => { try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; } };
