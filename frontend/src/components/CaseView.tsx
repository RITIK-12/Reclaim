import { useState } from "react";
import type { CaseDetail, TimelineItem } from "../api";
import { ACTIONS, domain, img, pretty, usd } from "../api";
import { ActionBadge, Card, Meter, SponsorTag, StatusChip } from "./ui";

const AGENT_STYLE: Record<string, string> = {
  supervisor: "bg-ink text-paper",
  inspector: "bg-teal-700 text-white",
  market: "bg-live text-white",
  operator: "bg-box text-white",
};

function Photos({ c }: { c: CaseDetail }) {
  const photos: string[] = c.return?.photos ?? [];
  const used = c.inspection?.photos_used ?? 1;
  const [idx, setIdx] = useState(0);
  return (
    <div className="grid grid-cols-2 gap-3">
      <figure className="card overflow-hidden">
        <div className="flex h-56 items-center justify-center bg-white p-2">
          <img src={img(`cat_${c.product?.sku}.jpg`)} alt="catalog" className="max-h-full max-w-full object-contain" />
        </div>
        <figcaption className="border-t border-line px-3 py-2"><span className="label">Ordered · catalog photo</span></figcaption>
      </figure>
      <figure className="card overflow-hidden">
        <div className="h-56 bg-stone-800"><img src={img(photos[idx])} alt="dock" className="h-full w-full object-cover" /></div>
        <figcaption className="flex items-center justify-between border-t border-line px-3 py-2">
          <span className="label">Arrived · dock photo {idx + 1}/{photos.length}</span>
          <span className="flex gap-1">
            {photos.map((_, i) => (
              <button key={i} onClick={() => setIdx(i)} className={`h-5 w-5 rounded font-mono text-[10px] ${i === idx ? "bg-ink text-paper" : "bg-stone-100"}`}>
                {i + 1}{i < used ? "" : ""}
              </button>
            ))}
          </span>
        </figcaption>
      </figure>
    </div>
  );
}

function Inspection({ i }: { i: any }) {
  if (!i) return <Card title="Inspector" tag={<SponsorTag color="bg-teal-50 text-teal-800">Liquid LFM2.5-VL · on-device</SponsorTag>}><Pending text="Looking at the photos…" /></Card>;
  const idColor = i.identity === "match" ? "text-go" : i.identity === "mismatch" ? "text-fraud" : "text-hold";
  return (
    <Card title="Inspector" tag={<SponsorTag color="bg-teal-50 text-teal-800">Liquid LFM2.5-VL · on-device</SponsorTag>}>
      <div className="grid grid-cols-3 gap-4">
        <div>
          <div className="label">Identity</div>
          <div className={`font-mono text-lg font-semibold uppercase ${idColor}`}>{i.identity}</div>
          <Meter value={i.confidence} color={i.identity === "match" ? "bg-go" : "bg-hold"} />
          <div className="mt-1 font-mono text-[10px] text-muted">confidence {Math.round(i.confidence * 100)}% · {i.photos_used} photo{i.photos_used > 1 ? "s" : ""}</div>
        </div>
        <div>
          <div className="label">Condition</div>
          <div className="font-mono text-lg font-semibold">Grade {i.grade}</div>
          <div className="font-mono text-[10px] text-muted">defect: {pretty(i.defect_class)}</div>
        </div>
        <div>
          <div className="label">Blind pass saw</div>
          <div className="text-sm font-medium">{i.observed}</div>
          <div className="font-mono text-[10px] text-muted">{(i.visible_defects ?? []).join(", ") || "no visible damage"}</div>
        </div>
      </div>
      {i.guard && <div className="mt-3 rounded border border-orange-200 bg-orange-50 px-3 py-2 font-mono text-[11px] text-hold">GUARD RULE · {i.guard}</div>}
      {i.notes && <p className="mt-3 text-[12px] leading-snug text-muted">{i.notes}</p>}
    </Card>
  );
}

function Market({ m, evidence, inspection }: { m: any; evidence: any[]; inspection: any }) {
  const tag = <SponsorTag color="bg-blue-50 text-blue-800">Nimble · live web</SponsorTag>;
  if (!m && inspection?.identity === "mismatch")
    return <Card title="Market analyst" tag={tag}><div className="py-3 text-sm text-muted">Skipped: the item is not what was ordered, so the Supervisor sent it straight to a human instead of spending web searches on it.</div></Card>;
  if (!m) return <Card title="Market analyst" tag={tag}><Pending text={inspection ? "Searching the live web…" : "Waiting for inspection…"} /></Card>;
  const accepted = evidence.filter((e) => e.accepted);
  const rejected = evidence.length - accepted.length;
  return (
    <Card title="Market analyst" tag={<div className="flex gap-1.5">{m.cache_hit && <SponsorTag color="bg-violet-50 text-violet-800">memory hit · no web call</SponsorTag>}{tag}</div>}>
      <div className="grid grid-cols-4 gap-3">
        {(["new", "open_box", "refurb", "used"] as const).map((k) => (
          <div key={k}>
            <div className="label">{pretty(k)}</div>
            <div className={`font-mono text-lg font-semibold ${m[k] ? "" : "text-stone-300"}`}>{m[k] ? usd(m[k]) : "—"}</div>
          </div>
        ))}
      </div>
      <div className="mt-3 max-h-36 space-y-1 overflow-y-auto">
        {(accepted.length ? accepted : m.sources ?? []).map((e: any, n: number) => (
          <a key={n} href={e.url} target="_blank" rel="noreferrer" className="flex items-center justify-between gap-2 rounded px-2 py-1 font-mono text-[11px] hover:bg-stone-50">
            <span className="truncate text-live">{domain(e.url)}</span>
            <span className="shrink-0 text-muted">{pretty(e.kind)} · <b className="text-ink">{usd(e.price, 2)}</b>{e.fetched_at_ms ? ` · ${new Date(e.fetched_at_ms).toLocaleTimeString()}` : ""}</span>
          </a>
        ))}
      </div>
      {rejected > 0 && <div className="mt-2 font-mono text-[10px] text-muted">{rejected} extracted price{rejected > 1 ? "s" : ""} rejected (not in source text / implausible)</div>}
    </Card>
  );
}

function DecisionCard({ d, human, execution, escalation }: { d: any; human: any; execution: any; escalation: any }) {
  if (!d && !human && !escalation) return <Card title="Decision"><Pending text="Scoring options…" /></Card>;
  const ev: Record<string, number> = d?.ev ?? {};
  const max = Math.max(1, ...Object.values(ev).map((v) => Math.max(0, v)));
  const final = human?.action ?? d?.action ?? (escalation ? "ESCALATE" : undefined);
  return (
    <Card title="Decision · expected recovery per action" tag={<div className="flex items-center gap-2">{d?.precedent_ref && <SponsorTag color="bg-violet-50 text-violet-800">human precedent {d.precedent_ref}</SponsorTag>}<ActionBadge action={final} size="lg" /></div>}>
      {d && (
        <div className="space-y-1.5">
          {ACTIONS.map((a) => {
            const allowed = d.allowed?.includes(a);
            const chosen = a === final;
            return (
              <div key={a} className={`grid grid-cols-[130px_1fr_80px] items-center gap-3 ${allowed ? "" : "opacity-35"}`}>
                <span className={`font-mono text-[11px] ${chosen ? "font-bold" : ""}`}>{chosen ? "▶ " : ""}{pretty(a)}</span>
                <Meter value={Math.max(0, ev[a] ?? 0)} max={max} color={chosen ? "bg-go" : allowed ? "bg-stone-500" : "bg-stone-300"} />
                <span className={`text-right font-mono text-[12px] tabular-nums ${(ev[a] ?? 0) < 0 ? "text-fraud" : ""}`}>{allowed ? usd(ev[a]) : "excluded"}</span>
              </div>
            );
          })}
        </div>
      )}
      {(d?.escalation_reason || escalation?.reason) && (
        <div className="mt-3 rounded border border-orange-200 bg-orange-50 px-3 py-2 text-[12px] text-hold">
          <b>Escalated to a human:</b> {d?.escalation_reason ?? escalation?.reason}
          {!human && <div className="mt-1 font-mono text-[10px]">graph paused durably (LangGraph interrupt) · waiting in the inbox →</div>}
        </div>
      )}
      {human && <div className="mt-3 rounded border border-orange-200 bg-white px-3 py-2 text-[12px]"><b className="text-hold">Human decided {pretty(human.action)}</b>{human.fraud_flag ? " · flagged fraud" : ""}{human.note ? ` — “${human.note}”` : ""}</div>}
      {d?.rationale && <p className="mt-3 text-[13px] leading-snug">{d.rationale}</p>}
      {execution && <div className="mt-3 font-mono text-[11px] text-go">✓ executed in RawTree · unit at {execution.location} / {execution.state}</div>}
      {d?.basis?.estimated?.length > 0 && <div className="mt-1 font-mono text-[10px] text-muted">estimated (no live price): {d.basis.estimated.map(pretty).join(", ")}</div>}
    </Card>
  );
}

function Timeline({ items }: { items: TimelineItem[] }) {
  const t0 = items[0]?.ts_ms ?? 0;
  return (
    <Card title={`Agent timeline · ${items.length} ledger events (RawTree)`}>
      <ol className="max-h-72 space-y-1 overflow-y-auto">
        {items.map((e, n) => {
          const human = e.type === "human.decided";
          return (
            <li key={n} className="grid grid-cols-[52px_78px_1fr] items-start gap-2 text-[12px]">
              <span className="pt-0.5 text-right font-mono text-[10px] text-muted">+{((e.ts_ms - t0) / 1000).toFixed(1)}s</span>
              <span className={`rounded px-1.5 py-0.5 text-center font-mono text-[10px] ${human ? "bg-hold text-white" : AGENT_STYLE[e.agent] ?? "bg-stone-200"}`}>{human ? "human" : e.agent}</span>
              <span className={e.type === "supervisor.route" ? "text-muted" : ""}>
                <span className="font-mono text-[10px] text-muted">{e.type}</span> {e.summary}
              </span>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}

function Pending({ text }: { text: string }) {
  return <div className="flex items-center gap-2 py-3 text-sm text-muted"><span className="pulse-dot h-2 w-2 rounded-full bg-live" />{text}</div>;
}

export default function CaseView({ c }: { c: CaseDetail | null }) {
  if (!c) return <div className="card flex h-full items-center justify-center text-muted">Select a return from the dock feed.</div>;
  const r = c.return;
  return (
    <div className="space-y-3">
      <div className="card flex items-start justify-between gap-4 p-4">
        <div className="min-w-0">
          <div className="font-mono text-[11px] text-muted">{c.case_id} · SKU {c.product?.sku} · {pretty(c.product?.category)} · paid {usd(c.order?.price_paid, 2)} · catalog {usd(c.product?.list_price, 2)} (2023)</div>
          <h2 className="mt-1 truncate text-lg font-semibold">{c.product?.title}</h2>
          <p className="mt-1 text-sm">Customer: <i>“{r?.reason_text}”</i> <span className="font-mono text-[10px] text-muted">({pretty(r?.reason_category)})</span></p>
        </div>
        <StatusChip status={c.status} />
      </div>
      <Photos c={c} />
      <div className="grid grid-cols-2 gap-3">
        <Inspection i={c.inspection} />
        <Market m={c.market} evidence={c.evidence ?? []} inspection={c.inspection} />
      </div>
      <DecisionCard d={c.decision} human={c.human} execution={c.execution} escalation={c.escalation} />
      <Timeline items={c.timeline} />
    </div>
  );
}
