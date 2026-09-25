import { useState } from "react";
import type { CaseRow } from "../api";
import { ACTIONS, img, postJSON, pretty, usd, usePoll } from "../api";
import { ActionBadge, Card } from "./ui";

function InboxItem({ c, onOpen }: { c: CaseRow; onOpen: () => void }) {
  const [fraud, setFraud] = useState(false);
  const [note, setNote] = useState("");
  const [sent, setSent] = useState(false);
  const decide = async (action: string) => {
    setSent(true);
    await postJSON(`/api/cases/${c.case_id}/decision`, { action, fraud_flag: fraud, note });
  };
  return (
    <div className="enter rounded-lg border border-orange-300 bg-orange-50/60 p-3">
      <button onClick={onOpen} className="flex w-full gap-2 text-left">
        <img src={img(c.photo)} alt="" className="h-12 w-14 rounded object-cover" />
        <div className="min-w-0">
          <div className="font-mono text-[10px] text-hold">{c.case_id} · {usd(c.list_price)}</div>
          <div className="truncate text-[13px] font-medium">{c.title}</div>
          <div className="line-clamp-2 text-[11px] text-stone-600">{c.last_summary}</div>
        </div>
      </button>
      {sent ? (
        <div className="mt-2 font-mono text-[11px] text-live">Decision sent · agent resuming…</div>
      ) : (
        <>
          <div className="mt-2 grid grid-cols-2 gap-1.5">
            {ACTIONS.map((a) => (
              <button key={a} onClick={() => decide(a)} className="rounded border border-stone-300 bg-white px-2 py-1 font-mono text-[10px] font-semibold hover:border-ink hover:bg-ink hover:text-paper">
                {pretty(a).toUpperCase()}
              </button>
            ))}
          </div>
          <div className="mt-2 flex items-center gap-2">
            <label className="flex items-center gap-1 font-mono text-[10px] font-semibold text-fraud">
              <input type="checkbox" checked={fraud} onChange={(e) => setFraud(e.target.checked)} /> FLAG FRAUD
            </label>
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="note for the record…" className="min-w-0 flex-1 rounded border border-stone-300 bg-white px-2 py-1 text-[11px]" />
          </div>
        </>
      )}
    </div>
  );
}

function Memory({ runId }: { runId: string }) {
  const mem = usePoll<any>(runId ? "/api/memory" : null, 2500);
  const precedents = mem?.precedents ?? [];
  const applied = mem?.precedents_applied ?? [];
  const facts = mem?.facts ?? [];
  return (
    <Card title="Agent memory · RawTree" tag={<span className="font-mono text-[10px] text-muted">namespace {runId || "—"}</span>}>
      <div className="label mb-1">Human precedents learned</div>
      {precedents.length === 0 && <div className="text-[12px] text-muted">None yet. Every human decision becomes one.</div>}
      {precedents.map((p: any) => (
        <div key={p.case_id} className="mb-1.5 rounded border border-line px-2 py-1.5 text-[11px]">
          <div className="flex items-center justify-between"><span className="font-mono">{p.case_id}</span><ActionBadge action={p.action} /></div>
          <div className="truncate font-mono text-[10px] text-muted">{p.precedent_key}</div>
          {applied.filter((a: any) => a.precedent_ref === p.case_id).map((a: any) => (
            <div key={a.case_id} className="font-mono text-[10px] text-violet-700">↳ reused automatically for {a.case_id}</div>
          ))}
        </div>
      ))}
      <div className="label mb-1 mt-3">Price facts (TTL 6h, shared across cases)</div>
      <div className="max-h-40 space-y-0.5 overflow-y-auto">
        {facts.length === 0 && <div className="text-[12px] text-muted">Nothing learned yet.</div>}
        {facts.map((f: any, n: number) => (
          <div key={n} className="flex justify-between font-mono text-[10px]">
            <span className="truncate text-muted">{f.sku} · {pretty(f.kind)}</span><span>{usd(f.value, 2)}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

function Eval({ runId }: { runId: string }) {
  const ev = usePoll<any>(runId ? "/api/eval" : null, 4000);
  const m = ev?.metrics;
  if (!m || !m.completed) return null;
  const row = (label: string, v: any, good?: boolean) => (
    <div className="flex justify-between font-mono text-[11px]"><span className="text-muted">{label}</span><span className={good === undefined ? "" : good ? "text-go" : "text-fraud"}>{v ?? "—"}</span></div>
  );
  return (
    <Card title="Evaluation vs ground truth" tag={<span className="font-mono text-[10px] text-muted">{m.completed}/{m.cases} labelled</span>}>
      {row("action accuracy", `${m.action_accuracy}%`)}
      {row("identity accuracy", `${m.identity_accuracy}%`)}
      {row("fraud catch rate", m.fraud_catch_rate === null ? "—" : `${m.fraud_catch_rate}%`)}
      {row("unsafe auto-resolves", m.unsafe_auto_resolves, m.unsafe_auto_resolves === 0)}
      {row("false escalations", m.false_escalations)}
      {row("grade accuracy (matches)", `${m.grade_accuracy ?? "—"}%`)}
      {row("avg secs to decision", m.avg_secs_to_decision)}
    </Card>
  );
}

export default function SidePanel({ escalations, runId, onOpen }: { escalations: CaseRow[]; runId: string; onOpen: (id: string) => void }) {
  return (
    <aside className="min-h-0 space-y-3 overflow-y-auto pr-1">
      <Card title="Escalation inbox · human in the loop" tag={<span className={`font-mono text-[10px] ${escalations.length ? "text-hold" : "text-muted"}`}>{escalations.length} waiting</span>}>
        <div className="space-y-2">
          {escalations.length === 0 && <div className="text-[12px] text-muted">Nothing needs you. The agent escalates only when it should.</div>}
          {escalations.map((c) => <InboxItem key={c.case_id} c={c} onOpen={() => onOpen(c.case_id)} />)}
        </div>
      </Card>
      <Memory runId={runId} />
      <Eval runId={runId} />
    </aside>
  );
}
