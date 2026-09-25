import { useState } from "react";
import type { Kpis } from "../api";
import { postJSON, usd } from "../api";

function Kpi({ label, value, sub, accent = "" }: { label: string; value: string | number; sub?: string; accent?: string }) {
  return (
    <div className="min-w-0 border-l border-line pl-4 first:border-l-0 first:pl-0">
      <div className="label truncate">{label}</div>
      <div className={`mt-0.5 font-mono text-2xl font-semibold tabular-nums ${accent}`}>{value}</div>
      {sub && <div className="truncate font-mono text-[10px] text-muted">{sub}</div>}
    </div>
  );
}

export default function Header({ kpis, runId, current }: { kpis: Kpis | null; runId: string; current: string | null }) {
  const [busy, setBusy] = useState(false);
  const start = async (which: string, new_run: boolean, gap_s: number) => {
    setBusy(true);
    try { await postJSON("/api/demo/start", { which, new_run, gap_s }); } finally { setBusy(false); }
  };
  const k = kpis;
  return (
    <header className="border-b border-line bg-card">
      <div className="flex items-center justify-between gap-6 px-6 pt-4">
        <div className="flex items-baseline gap-4">
          <h1 className="font-mono text-xl font-bold tracking-[0.2em]">RECLAIM</h1>
          <p className="text-sm text-muted">
            Autonomous returns desk · <span className="text-teal-700">Liquid sees</span> · <span className="text-live">Nimble prices</span> · <span className="text-box">RawTree remembers</span>
          </p>
        </div>
        <div className="flex items-center gap-3 font-mono text-[11px] text-muted">
          <span>{runId ? `run ${runId}` : "no active run"}</span>
          {current && <span className="flex items-center gap-1.5 text-live"><span className="pulse-dot h-1.5 w-1.5 rounded-full bg-live" />agent working on {current}</span>}
          <button disabled={busy} onClick={() => start("warmup", true, 3)} className="rounded border border-line px-3 py-1.5 text-[11px] font-semibold tracking-wider hover:bg-stone-100 disabled:opacity-50">NEW SHIFT</button>
          <button disabled={busy || !runId} onClick={() => start("live", false, 8)} className="rounded bg-ink px-3 py-1.5 text-[11px] font-semibold tracking-wider text-paper hover:bg-stone-700 disabled:opacity-50">TRUCK ARRIVES ▸</button>
          <button disabled={busy} onClick={() => start("eval", true, 2)} className="rounded border border-line px-3 py-1.5 text-[11px] font-semibold tracking-wider hover:bg-stone-100 disabled:opacity-50">RUN EVAL SET</button>
        </div>
      </div>
      <div className="grid grid-cols-8 gap-4 px-6 py-4">
        <Kpi label="Returns received" value={k?.received ?? 0} sub={`${k?.closed ?? 0} closed`} />
        <Kpi label="Auto-resolved" value={`${k?.auto_resolved_pct ?? 0}%`} sub="no human needed" accent="text-go" />
        <Kpi label="Awaiting human" value={k?.pending_human ?? 0} sub={`${k?.escalated ?? 0} escalated total`} accent={k?.pending_human ? "text-hold" : ""} />
        <Kpi label="Fraud flags" value={k?.fraud_flags ?? 0} sub="wrong item returned" accent={k?.fraud_flags ? "text-fraud" : ""} />
        <Kpi label="Extra recovered" value={usd(k?.uplift_vs_liquidate)} sub="extra $ vs liquidate-all" accent="text-go" />
        <Kpi label="Avg time per case" value={k?.avg_case_secs ? `${k.avg_case_secs}s` : "—"} sub={`${k?.llm_calls ?? 0} Liquid calls · ${k?.avg_llm_ms ?? 0} ms avg`} />
        <Kpi label="Web evidence" value={k?.web_searches ?? 0} sub={`Nimble searches · ${k?.cache_hits ?? 0} memory hits`} accent="text-live" />
        <Kpi label="Context per call" value={`${k?.avg_brief_tokens ?? 0} tok`} sub={`ledger: ${k?.ledger_events ?? 0} events in RawTree`} />
      </div>
    </header>
  );
}
