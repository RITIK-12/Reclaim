import { useState, type ReactNode } from "react";
import type { CaseDetail, TimelineItem } from "../api";
import { ACTIONS, domain, img, pretty, usd } from "../api";
import { ActionBadge, Meter, SponsorTag, StatusChip } from "./ui";

type StepState = "done" | "active" | "waiting" | "pending" | "skipped";

const AGENT_STYLE: Record<string, string> = {
  supervisor: "bg-ink text-paper", inspector: "bg-teal-700 text-white", market: "bg-live text-white",
  operator: "bg-box text-white",
};

/** Where the case is in the pipeline, derived only from what the agent has written to RawTree. */
function stepStates(c: CaseDetail): Record<string, StepState> {
  const st = c.status;
  const inspected = !!c.inspection;
  const mismatch = c.inspection?.identity === "mismatch";
  const priced = !!c.market;
  const decided = !!c.decision;
  const escalated = !!c.escalation;
  const human = !!c.human;
  const executed = !!c.execution;
  return {
    inspect: inspected ? "done" : st === "QUEUED" ? "pending" : "active",
    price: priced ? "done" : mismatch ? "skipped" : inspected ? "active" : "pending",
    decide: decided ? "done" : mismatch && escalated ? "skipped" : priced ? "active" : "pending",
    human: human ? "done" : escalated ? "waiting" : executed || (decided && !escalated) ? "skipped" : "pending",
    execute: executed ? "done" : st === "EXECUTING" || (human && !executed) ? "active" : "pending",
  };
}

function Dot({ s, n }: { s: StepState; n: number }) {
  const style: Record<StepState, string> = {
    done: "bg-go text-white border-go", active: "bg-white text-live border-live", waiting: "bg-hold text-white border-hold",
    pending: "bg-white text-stone-300 border-stone-300", skipped: "bg-stone-100 text-stone-400 border-stone-300",
  };
  return (
    <span className={`relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-2 font-mono text-[11px] font-bold ${style[s]}`}>
      {s === "done" ? "✓" : s === "skipped" ? "–" : s === "waiting" ? "!" : n}
      {s === "active" && <span className="pulse-dot absolute inset-0 rounded-full border-2 border-live" />}
    </span>
  );
}

function Step({ n, title, tag, state, note, children, last = false }: {
  n: number; title: string; tag?: ReactNode; state: StepState; note?: string; children?: ReactNode; last?: boolean;
}) {
  const open = state === "done" || state === "waiting" || (state === "active" && !!children);
  return (
    <li className="relative flex gap-4">
      {!last && <span className="absolute left-[13px] top-7 h-[calc(100%-4px)] w-0.5 bg-line" />}
      <Dot s={state} n={n} />
      <div className={`min-w-0 flex-1 pb-5 ${state === "pending" || state === "skipped" ? "opacity-60" : ""}`}>
        <div className="flex min-h-7 flex-wrap items-center gap-2">
          <h3 className="text-[15px] font-semibold">{title}</h3>
          {tag}
          {state === "active" && <span className="font-mono text-[10px] text-live">working…</span>}
          {state === "waiting" && <span className="font-mono text-[10px] font-semibold text-hold">waiting for a human</span>}
          {note && <span className="font-mono text-[10px] text-muted">{note}</span>}
        </div>
        {open && children && <div className="mt-2">{children}</div>}
      </div>
    </li>
  );
}

function Photos({ c }: { c: CaseDetail }) {
  const photos: string[] = c.return?.photos ?? [];
  const [idx, setIdx] = useState(0);
  return (
    <div className="grid grid-cols-2 gap-3">
      <figure className="card overflow-hidden">
        <div className="flex h-52 items-center justify-center bg-white p-2">
          <img src={img(`cat_${c.product?.sku}.jpg`)} alt="catalog" className="max-h-full max-w-full object-contain" />
        </div>
        <figcaption className="border-t border-line px-3 py-1.5"><span className="label">What was ordered · catalog photo</span></figcaption>
      </figure>
      <figure className="card overflow-hidden">
        <div className="h-52 bg-stone-800"><img src={img(photos[idx])} alt="dock" className="h-full w-full object-cover" /></div>
        <figcaption className="flex items-center justify-between border-t border-line px-3 py-1.5">
          <span className="label">What arrived · dock photo {idx + 1}/{photos.length}</span>
          <span className="flex gap-1">
            {photos.map((_, i) => (
              <button key={i} onClick={() => setIdx(i)} className={`h-5 w-5 rounded font-mono text-[10px] ${i === idx ? "bg-ink text-paper" : "bg-stone-100"}`}>{i + 1}</button>
            ))}
          </span>
        </figcaption>
      </figure>
    </div>
  );
}

function InspectResult({ i }: { i: any }) {
  if (!i) return null;
  const idColor = i.identity === "match" ? "text-go" : i.identity === "mismatch" ? "text-fraud" : "text-hold";
  return (
    <div className="card mt-3 p-3">
      <div className="grid grid-cols-3 gap-4">
        <div>
          <div className="label">Is it the ordered item?</div>
          <div className={`font-mono text-lg font-semibold uppercase ${idColor}`}>{i.identity}</div>
          <Meter value={i.confidence} color={i.identity === "match" ? "bg-go" : "bg-hold"} />
          <div className="mt-1 font-mono text-[10px] text-muted">confidence {Math.round(i.confidence * 100)}% · {i.photos_used} photo{i.photos_used > 1 ? "s" : ""}</div>
        </div>
        <div>
          <div className="label">Condition</div>
          <div className="font-mono text-lg font-semibold">Grade {i.grade}</div>
          <div className="font-mono text-[10px] text-muted">{pretty(i.defect_class)}</div>
        </div>
        <div>
          <div className="label">Blind look saw</div>
          <div className="text-sm font-medium">{i.observed}</div>
          <div className="font-mono text-[10px] text-muted">{(i.visible_defects ?? []).join(", ") || "no visible damage"}</div>
        </div>
      </div>
      {i.guard && <div className="mt-2 rounded border border-orange-200 bg-orange-50 px-3 py-1.5 font-mono text-[11px] text-hold">GUARD RULE · {i.guard}</div>}
    </div>
  );
}

function PriceResult({ m, evidence }: { m: any; evidence: any[] }) {
  if (!m) return null;
  const accepted = evidence.filter((e) => e.accepted);
  const rejected = evidence.length - accepted.length;
  return (
    <div className="card p-3">
      <div className="grid grid-cols-4 gap-3">
        {(["new", "open_box", "refurb", "used"] as const).map((k) => (
          <div key={k}>
            <div className="label">{pretty(k)}</div>
            <div className={`font-mono text-lg font-semibold ${m[k] ? "" : "text-stone-300"}`}>{m[k] ? usd(m[k]) : "—"}</div>
          </div>
        ))}
      </div>
      <div className="mt-2 max-h-28 space-y-0.5 overflow-y-auto">
        {(accepted.length ? accepted : m.sources ?? []).map((e: any, n: number) => (
          <a key={n} href={e.url} target="_blank" rel="noreferrer" className="flex items-center justify-between gap-2 rounded px-2 py-0.5 font-mono text-[11px] hover:bg-stone-50">
            <span className="truncate text-live">{domain(e.url)}</span>
            <span className="shrink-0 text-muted">{pretty(e.kind)} · <b className="text-ink">{usd(e.price, 2)}</b>{e.fetched_at_ms ? ` · ${new Date(e.fetched_at_ms).toLocaleTimeString()}` : ""}</span>
          </a>
        ))}
      </div>
      {rejected > 0 && <div className="mt-1 font-mono text-[10px] text-muted">{rejected} extracted price{rejected > 1 ? "s" : ""} rejected (not in the source text or implausible)</div>}
    </div>
  );
}

function DecisionResult({ d }: { d: any }) {
  if (!d) return null;
  const ev: Record<string, number> = d.ev ?? {};
  const max = Math.max(1, ...Object.values(ev).map((v) => Math.max(0, v)));
  const pick = d.action === "ESCALATE" ? d.suggested_action : d.action;
  return (
    <div className="card p-3">
      <div className="space-y-1.5">
        {ACTIONS.map((a) => {
          const allowed = d.allowed?.includes(a);
          const chosen = a === pick;
          return (
            <div key={a} className={`grid grid-cols-[130px_1fr_80px] items-center gap-3 ${allowed ? "" : "opacity-35"}`}>
              <span className={`font-mono text-[11px] ${chosen ? "font-bold" : ""}`}>{chosen ? "▶ " : ""}{pretty(a)}</span>
              <Meter value={Math.max(0, ev[a] ?? 0)} max={max} color={chosen ? "bg-go" : allowed ? "bg-stone-500" : "bg-stone-300"} />
              <span className={`text-right font-mono text-[12px] tabular-nums ${(ev[a] ?? 0) < 0 ? "text-fraud" : ""}`}>{allowed ? usd(ev[a]) : "not allowed"}</span>
            </div>
          );
        })}
      </div>
      {d.rationale && <p className="mt-2 text-[13px] leading-snug">{d.rationale}</p>}
      {d.basis?.estimated?.length > 0 && <div className="mt-1 font-mono text-[10px] text-muted">estimated (no live price found): {d.basis.estimated.map(pretty).join(", ")}</div>}
    </div>
  );
}

function Ledger({ items }: { items: TimelineItem[] }) {
  const t0 = items[0]?.ts_ms ?? 0;
  return (
    <details className="card p-3">
      <summary className="label cursor-pointer">Full agent ledger · {items.length} events in RawTree</summary>
      <ol className="mt-2 max-h-64 space-y-1 overflow-y-auto">
        {items.map((e, n) => {
          const human = e.type === "human.decided";
          return (
            <li key={n} className="grid grid-cols-[52px_78px_1fr] items-start gap-2 text-[12px]">
              <span className="pt-0.5 text-right font-mono text-[10px] text-muted">+{((e.ts_ms - t0) / 1000).toFixed(1)}s</span>
              <span className={`rounded px-1.5 py-0.5 text-center font-mono text-[10px] ${human ? "bg-hold text-white" : AGENT_STYLE[e.agent] ?? "bg-stone-200"}`}>{human ? "human" : e.agent}</span>
              <span className={e.type === "supervisor.route" ? "text-muted" : ""}><span className="font-mono text-[10px] text-muted">{e.type}</span> {e.summary}</span>
            </li>
          );
        })}
      </ol>
    </details>
  );
}

export default function CaseView({ c }: { c: CaseDetail | null }) {
  if (!c) return (
    <div className="card flex h-full flex-col items-center justify-center gap-2 p-10 text-center text-muted">
      <div className="font-mono text-sm tracking-[0.2em] text-ink">NO CASE SELECTED</div>
      <p className="max-w-md text-sm">When a return arrives, the Supervisor opens a case on its own: Liquid inspects the photos,
        Nimble prices the item on the live web, the policy picks an action and the Operator executes it in RawTree.</p>
    </div>
  );
  const r = c.return;
  const s = stepStates(c);
  const t0 = c.timeline[0]?.ts_ms;
  const at = (type: string) => {
    const e = c.timeline.find((x) => x.type === type);
    return e && t0 ? `+${((e.ts_ms - t0) / 1000).toFixed(0)}s` : undefined;
  };
  const final = c.human?.action ?? (c.decision && c.decision.action !== "ESCALATE" ? c.decision.action : undefined);
  const escReason = c.decision?.escalation_reason ?? c.escalation?.reason;
  return (
    <div className="space-y-3">
      <div className="card flex items-start justify-between gap-4 p-4">
        <div className="min-w-0">
          <div className="font-mono text-[11px] text-muted">{c.case_id} · SKU {c.product?.sku} · {pretty(c.product?.category)} · paid {usd(c.order?.price_paid, 2)} · catalog {usd(c.product?.list_price, 2)} (2023)</div>
          <h2 className="mt-1 truncate text-lg font-semibold">{c.product?.title}</h2>
          <p className="mt-1 text-sm">Customer: <i>“{r?.reason_text}”</i> <span className="font-mono text-[10px] text-muted">({pretty(r?.reason_category)})</span></p>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <StatusChip status={c.status} />
          {final && <ActionBadge action={final} size="lg" />}
        </div>
      </div>

      <ol className="card p-4 pb-0">
        <Step n={1} title="Arrived at the dock" state="done" note={t0 ? new Date(t0).toLocaleTimeString() : undefined}
          tag={<SponsorTag color="bg-amber-50 text-amber-800">RawTree trigger · no human prompt</SponsorTag>} />
        <Step n={2} title="Inspecting the photos" state={s.inspect} note={at("inspector.completed")}
          tag={<SponsorTag color="bg-teal-50 text-teal-800">Liquid LFM2.5-VL · on-device</SponsorTag>}>
          <Photos c={c} />
          <InspectResult i={c.inspection} />
        </Step>
        <Step n={3} title="Pricing it on the live web" state={s.price}
          note={s.price === "skipped" ? "skipped: not the ordered item" : at("market.completed") ?? at("market.cache_hit")}
          tag={<div className="flex gap-1.5">{c.market?.cache_hit && <SponsorTag color="bg-violet-50 text-violet-800">from memory · no web call</SponsorTag>}<SponsorTag color="bg-blue-50 text-blue-800">Nimble · live web</SponsorTag></div>}>
          <PriceResult m={c.market} evidence={c.evidence ?? []} />
        </Step>
        <Step n={4} title="Deciding the best action" state={s.decide} note={at("decision.made")}
          tag={<div className="flex items-center gap-1.5">{c.decision?.precedent_ref && <SponsorTag color="bg-violet-50 text-violet-800">human precedent {c.decision.precedent_ref}</SponsorTag>}<SponsorTag color="bg-stone-100 text-stone-700">expected value + rules</SponsorTag></div>}>
          <DecisionResult d={c.decision} />
        </Step>
        <Step n={5} title="Human review" state={s.human} note={s.human === "skipped" ? "not needed: resolved autonomously" : at("human.decided")}>
          {escReason && (
            <div className="rounded border border-orange-200 bg-orange-50 px-3 py-2 text-[12px] text-hold">
              <b>Escalated:</b> {escReason}
              {!c.human && <div className="mt-1 font-mono text-[10px]">graph paused durably (LangGraph interrupt) · decide in the inbox →</div>}
            </div>
          )}
          {c.human && <div className="mt-2 rounded border border-line bg-white px-3 py-2 text-[12px]"><b className="text-hold">Human chose {pretty(c.human.action)}</b>{c.human.fraud_flag ? " · flagged fraud" : ""}{c.human.note ? ` — “${c.human.note}”` : ""}</div>}
        </Step>
        <Step n={6} title="Executed in the warehouse" state={s.execute} note={at("operator.verified")} last
          tag={<SponsorTag color="bg-amber-50 text-amber-800">RawTree · verified by read-back</SponsorTag>}>
          {c.execution && <div className="font-mono text-[12px] text-go">✓ unit U-{c.case_id} at <b>{c.execution.location}</b> / {c.execution.state}</div>}
        </Step>
      </ol>

      <Ledger items={c.timeline} />
    </div>
  );
}
