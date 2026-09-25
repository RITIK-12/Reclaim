import { useEffect, useState } from "react";
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

  // Follow the agent (the case it is working on, else one waiting for a human) until the user picks a case.
  const [pinned, setPinned] = useState(false);
  const current = state?.current_case ?? null;
  useEffect(() => {
    if (pinned || !cases.length) return;
    const working = cases.find((c) => c.case_id === current);
    const waiting = cases.find((c) => c.status === "ESCALATED");
    setSelected((working ?? waiting ?? cases[0]).case_id);
  }, [cases, pinned, current]);
  useEffect(() => { setPinned(false); setSelected(null); }, [runId]);

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
