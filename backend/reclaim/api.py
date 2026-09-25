"""FastAPI app: hosts the runner + watcher (the proactive agent) and serves the dashboard's JSON.

Run: uv run uvicorn reclaim.api:app --port 8000
Everything the UI shows is read back from RawTree; the API never keeps its own copy of case state.
"""
from __future__ import annotations

import json
import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import settings
from .decision import ACTIONS
from .evaluation import Evaluator
from .memory import memory
from .rawtree import db, sql_str
from .replay import DockReplay
from .runtime import Runner, Watcher
from .warehouse import warehouse

RUN_FILE = settings.data_dir / "current_run.txt"
STAGE = {"case.opened": "RECEIVED", "case.escalated": "ESCALATED", "human.decided": "EXECUTING",
         "decision.made": "DECIDING", "case.closed": "CLOSED", "case.failed": "FAILED", "case.error": "ERROR"}
ROUTE_STAGE = {"inspect": "INSPECTING", "price": "PRICING", "decide": "DECIDING", "operate": "EXECUTING",
               "flag": "ESCALATED", "close": "CLOSED"}


class Decision(BaseModel):
    action: str
    fraud_flag: bool = False
    note: str = ""


class DemoStart(BaseModel):
    which: str = "shift"     # shift (5 FLUX returns, one per action) | live (precedent pair) | demo | eval | all
    gap_s: float = 12.0
    new_run: bool = True


class App:
    """Process-wide agent runtime: one runner thread, one watcher, one active run."""

    def __init__(self):
        self.runner = Runner().start()
        self.watcher = Watcher(self.runner).start()
        self.replay = DockReplay()
        self.run_id = RUN_FILE.read_text().strip() if RUN_FILE.exists() else ""
        self._stop_replay = threading.Event()
        if self.run_id:
            self.watcher.watch(self.run_id)
            self.resume_unfinished()

    def resume_unfinished(self) -> None:
        """Crash-resume: continue cases that were mid-flight from their LangGraph checkpoint."""
        for cid, head in memory.case_heads(self.run_id).items():
            if stage_of(head) not in ("CLOSED", "FAILED", "ESCALATED"):
                self.runner.continue_case(self.run_id, cid)

    def start_demo(self, which: str, gap_s: float, new_run: bool = True) -> str:
        """New shift (fresh run_id = fresh memory namespace) or more arrivals into the current one."""
        if new_run or not self.run_id:
            self._stop_replay.set()
            self._stop_replay = threading.Event()
            self.run_id = self.replay.new_run_id("eval" if which == "eval" else "shift")
            RUN_FILE.write_text(self.run_id)
            self.watcher.watch(self.run_id)
        stop = self._stop_replay
        threading.Thread(target=self.replay.play, args=(self.run_id, which, gap_s, stop.is_set),
                         daemon=True, name="dock-replay").start()
        return self.run_id


def stage_of(head: dict) -> str:
    t = head.get("last_type", "")
    if t == "supervisor.route":
        nxt = json.loads(head.get("last_payload") or "{}").get("next", "")
        return ROUTE_STAGE.get(nxt, "RECEIVED")
    if t.startswith("inspector."):
        return "INSPECTING"
    if t.startswith("market."):
        return "PRICING"
    if t.startswith("operator."):
        return "EXECUTING"
    return STAGE.get(t, "RECEIVED")


state: App | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global state
    state = App()
    yield


app = FastAPI(title="Reclaim", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def run_id() -> str:
    if not state or not state.run_id:
        raise HTTPException(409, "No active run. POST /api/demo/start first.")
    return state.run_id


def heads(run: str) -> dict[str, dict]:
    rows = db.query(
        f"SELECT toString(case_id) AS cid, argMax(toString(type), toInt64(ts_ms)) AS last_type, "
        f"argMax(toString(summary), toInt64(ts_ms)) AS last_summary, "
        f"argMax(toString(payload), toInt64(ts_ms)) AS last_payload, "
        f"min(toInt64(ts_ms)) AS first_ts, max(toInt64(ts_ms)) AS last_ts, count() AS n "
        f"FROM {{t:mem_events}} WHERE run_id = {sql_str(run)} GROUP BY cid")
    return {r["cid"]: r for r in rows}


@app.get("/api/state")
def get_state():
    return {"run_id": state.run_id if state else "", "current_case": state.runner.current if state else None,
            "queued": state.runner.jobs.qsize() if state else 0, "model": settings.llm_model}


@app.post("/api/demo/start")
def demo_start(body: DemoStart):
    if body.which not in ("shift", "live", "classic", "demo", "eval", "all"):
        raise HTTPException(400, "which must be shift, live, classic, demo, eval or all")
    return {"run_id": state.start_demo(body.which, body.gap_s, body.new_run)}


@app.post("/api/view/{rid}")
def view_run(rid: str):
    """Point the dashboard at an existing run (e.g. a headless or eval run) without resuming anything."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", rid):
        raise HTTPException(400, "bad run id")
    state.run_id = rid
    return {"run_id": rid}


@app.get("/api/cases")
def list_cases():
    run = run_id()
    returns = warehouse.returns(run)
    hs = heads(run)
    decisions = {d["case_id"]: d for d in memory.decisions(run)}
    products = warehouse.products(sorted({r["sku"] for r in returns}))
    out = []
    for r in reversed(returns):
        h, d, p = hs.get(r["return_id"], {}), decisions.get(r["return_id"], {}), products.get(r["sku"], {})
        out.append({"case_id": r["return_id"], "key": r.get("scenario_key"), "sku": r["sku"],
                    "title": p.get("title", ""), "category": p.get("category"), "list_price": p.get("list_price"),
                    "reason_text": r["reason_text"], "reason_category": r["reason_category"],
                    "received_at_ms": r["received_at_ms"], "photo": (r.get("photos") or [None])[0],
                    "status": stage_of(h) if h else "QUEUED", "last_summary": h.get("last_summary", ""),
                    "action": d.get("action"), "decided_by": d.get("decided_by"), "uplift": d.get("uplift"),
                    "fraud_flag": d.get("fraud_flag"), "precedent_ref": d.get("precedent_ref") or None})
    return out


@app.get("/api/cases/{case_id}")
def case_detail(case_id: str):
    run = run_id()
    r = warehouse.return_(run, case_id)
    if not r:
        raise HTTPException(404, "unknown case")
    events = memory.events(run, case_id)
    last = {}
    for e in events:
        last[e["type"]] = e["payload"]
    order = warehouse.order(run, r["order_id"]) or {}
    decision = last.get("decision.made") or {}
    return {
        "case_id": case_id, "return": r, "order": order, "product": warehouse.product(r["sku"]),
        "status": stage_of({"last_type": events[-1]["type"], "last_payload": json.dumps(events[-1]["payload"])})
        if events else "QUEUED",
        "inspection": last.get("inspector.completed"), "market": last.get("market.completed")
        or last.get("market.cache_hit"), "evidence": memory.evidence(run, case_id), "decision": decision or None,
        "escalation": last.get("case.escalated"), "human": last.get("human.decided"),
        "execution": last.get("operator.verified"), "unit": warehouse.unit_state(run, f"U-{case_id}"),
        "timeline": [{k: e[k] for k in ("ts_ms", "agent", "type", "summary")} | {"payload": e["payload"]}
                     for e in events],
    }


@app.get("/api/escalations")
def escalations():
    return [c for c in list_cases() if c["status"] == "ESCALATED"]


@app.post("/api/cases/{case_id}/decision")
def decide(case_id: str, body: Decision):
    if body.action not in ACTIONS:
        raise HTTPException(400, f"action must be one of {ACTIONS}")
    state.runner.resume(run_id(), case_id, body.model_dump() | {"by": "ui"})
    return {"ok": True}


@app.get("/api/kpis")
def kpis():
    run = run_id()
    cases = list_cases()
    closed = [c for c in cases if c["status"] == "CLOSED"]
    auto = [c for c in closed if c["decided_by"] == "agent"]
    llm = db.one(f"SELECT count() AS calls, avg(toFloat64(latency_ms)) AS avg_ms, "
                 f"avgIf(toFloat64(brief_tokens), toFloat64(brief_tokens) > 0) AS avg_brief, "
                 f"sum(toInt64(prompt_tokens)) AS prompt_tokens FROM {{t:llm_calls}} WHERE run_id = {sql_str(run)}") or {}
    counts = db.one(f"SELECT count() AS events, countIf(toString(type) = 'market.cache_hit') AS cache_hits, "
                    f"countIf(toString(type) = 'market.search') AS searches FROM {{t:mem_events}} "
                    f"WHERE run_id = {sql_str(run)}") or {}
    hs = heads(run)
    secs = [(h["last_ts"] - h["first_ts"]) / 1000 for cid, h in hs.items()
            if any(c["case_id"] == cid and c["status"] == "CLOSED" for c in cases)]
    return {
        "run_id": run, "received": len(cases), "closed": len(closed),
        "auto_resolved_pct": round(100 * len(auto) / len(closed), 1) if closed else 0,
        "escalated": sum(c["decided_by"] == "human" or c["status"] == "ESCALATED" for c in cases),
        "pending_human": sum(c["status"] == "ESCALATED" for c in cases),
        "fraud_flags": sum(bool(c["fraud_flag"]) for c in cases),
        "uplift_vs_liquidate": round(sum(float(c["uplift"] or 0) for c in closed), 2),
        "avg_case_secs": round(sum(secs) / len(secs), 1) if secs else None,
        "llm_calls": int(llm.get("calls") or 0), "avg_llm_ms": round(float(llm.get("avg_ms") or 0)),
        "avg_brief_tokens": round(float(llm.get("avg_brief") or 0)), "ledger_events": int(counts.get("events") or 0),
        "web_searches": int(counts.get("searches") or 0), "cache_hits": int(counts.get("cache_hits") or 0),
    }


@app.get("/api/memory")
def memory_panel():
    run = run_id()
    facts = db.query(f"SELECT toString(subject) AS sku, toString(predicate) AS kind, toFloat64(value) AS value, "
                     f"toString(source_url) AS source, toString(learned_in_case) AS learned_in "
                     f"FROM {{t:mem_knowledge}} WHERE run_id = {sql_str(run)} ORDER BY toInt64(observed_at_ms) DESC "
                     f"LIMIT 30")
    precedents = [d for d in memory.decisions(run) if d.get("decided_by") == "human"]
    applied = [d for d in memory.decisions(run) if d.get("precedent_ref")]
    return {"facts": facts, "precedents": precedents, "precedents_applied": applied}


@app.get("/api/eval")
def eval_report(run: str | None = None):
    ev = Evaluator()
    rows = ev.rows(run or run_id())
    return {"rows": rows, "metrics": ev.metrics(rows)}


@app.get("/api/images/{name}")
def image(name: str):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.jpg", name):
        raise HTTPException(400, "bad image name")
    path: Path = settings.images_dir / name
    if not path.exists():
        raise HTTPException(404, "no such image")
    return FileResponse(path, media_type="image/jpeg")
