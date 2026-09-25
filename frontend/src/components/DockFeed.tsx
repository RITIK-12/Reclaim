import type { CaseRow } from "../api";
import { img, usd } from "../api";
import { ActionBadge, StatusChip } from "./ui";

export default function DockFeed({ cases, selected, onSelect }: { cases: CaseRow[]; selected: string | null; onSelect: (id: string) => void }) {
  return (
    <aside className="flex min-h-0 flex-col">
      <div className="flex items-center justify-between px-1 pb-2">
        <h2 className="label">Receiving dock · live feed</h2>
        <span className="font-mono text-[10px] text-muted">{cases.length} returns</span>
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
        {cases.length === 0 && (
          <div className="card p-6 text-center text-sm text-muted">Waiting for returns to arrive at the dock…</div>
        )}
        {cases.map((c) => (
          <button key={c.case_id} onClick={() => onSelect(c.case_id)}
            className={`enter card flex w-full gap-3 p-2.5 text-left transition hover:border-stone-400 ${selected === c.case_id ? "border-ink ring-1 ring-ink" : ""}`}>
            <img src={img(c.photo)} alt="" className="h-14 w-16 shrink-0 rounded object-cover" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-[10px] text-muted">{c.case_id} · {usd(c.list_price)}</span>
                <StatusChip status={c.status} />
              </div>
              <div className="mt-0.5 truncate text-[13px] font-medium">{c.title}</div>
              <div className="truncate text-[11px] text-muted">“{c.reason_text}”</div>
              {(c.action || c.status === "ESCALATED") && (
                <div className="mt-1 flex items-center gap-1.5">
                  <ActionBadge action={c.status === "ESCALATED" && !c.action ? "ESCALATE" : c.action} />
                  {c.decided_by === "human" && <span className="font-mono text-[10px] text-hold">by human</span>}
                  {c.precedent_ref && <span className="font-mono text-[10px] text-violet-700">via precedent</span>}
                  {c.fraud_flag && <span className="font-mono text-[10px] font-semibold text-fraud">FRAUD</span>}
                </div>
              )}
            </div>
          </button>
        ))}
      </div>
    </aside>
  );
}
