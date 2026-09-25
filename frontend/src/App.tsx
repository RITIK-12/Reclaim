import { useEffect, useRef, useState } from "react";
import type { CaseDetail, CaseRow, Kpis } from "./api";
import { usePoll } from "./api";
import CaseView from "./components/CaseView";
import DockFeed from "./components/DockFeed";
import Header from "./components/Header";
import SidePanel from "./components/SidePanel";

export default function App() {
  const state = usePoll<{ run_id: string; current_case: string | null }>("/api/state", 1500);
  const runId = state?.run_id ?? "";
  const cases = usePoll<CaseRow[]>(runId ? `/api/cases?run=${runId}` : null, 1200) ?? [];
  const kpis = usePoll<Kpis>(runId ? `/api/kpis?run=${runId}` : null, 2000);
  const [selected, setSelected] = useState<string | null>(null);
  const detail = usePoll<CaseDetail>(selected ? `/api/cases/${selected}?run=${runId}` : null, 1200);

  // Follow the agent: move only when it starts a new case or a case starts waiting for a human.
  // Never re-select on a plain poll, or the page jumps every time a new return arrives.
  const [pinned, setPinned] = useState(false);
  const current = state?.current_case ?? null;
  const waiting = cases.find((c) => c.status === "ESCALATED")?.case_id ?? null;
  const target = current ?? waiting;
  const lastTarget = useRef<string | null>(null);
  useEffect(() => {
    if (pinned) return;
    if (target && target !== lastTarget.current) { lastTarget.current = target; setSelected(target); }
    else if (!selected && cases.length) setSelected(cases[0].case_id);
  }, [target, pinned, cases.length, selected]);
  useEffect(() => { setPinned(false); setSelected(null); lastTarget.current = null; }, [runId]);

  const open = (id: string) => { setPinned(true); setSelected(id); };
  const escalations = cases.filter((c) => c.status === "ESCALATED");

  return (
    <div className="flex h-full flex-col">
      <Header kpis={kpis} runId={runId} current={state?.current_case ?? null} />
      <main className="grid min-h-0 flex-1 grid-cols-[290px_1fr_320px] gap-4 p-4 2xl:grid-cols-[340px_1fr_370px]">
        <DockFeed cases={cases} selected={selected} onSelect={open} pinned={pinned} onFollow={() => setPinned(false)} />
        <section className="min-h-0 overflow-y-auto pr-1">
          <CaseView c={detail} />
        </section>
        <SidePanel escalations={escalations} runId={runId} onOpen={open} />
      </main>
    </div>
  );
}
