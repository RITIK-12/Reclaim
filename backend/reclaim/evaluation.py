"""Scores a run against ground truth (reclaim_eval_gt). Agents never read ground truth; only this does."""
from __future__ import annotations

import json

from .rawtree import RawTree, db, now_ms, sql_str


class Evaluator:
    def __init__(self, store: RawTree = db):
        self.db = store

    def rows(self, run_id: str) -> list[dict]:
        run = sql_str(run_id)
        gt = {r["return_id"]: r for r in self.db.query(f"SELECT * FROM {{t:eval_gt}} WHERE run_id = {run}")}
        events = self.db.query(f"SELECT toString(case_id) AS cid, toString(type) AS type, toString(payload) AS payload, "
                               f"toInt64(ts_ms) AS ts FROM {{t:mem_events}} WHERE run_id = {run} AND type IN "
                               f"('case.opened', 'inspector.completed', 'decision.made', 'case.escalated', "
                               f"'case.closed', 'case.failed') ORDER BY ts")
        cases: dict[str, dict] = {}
        for e in events:
            c = cases.setdefault(e["cid"], {"case_id": e["cid"]})
            p = json.loads(e["payload"] or "{}")
            if e["type"] == "case.opened":
                c["opened_ts"] = e["ts"]
            elif e["type"] == "inspector.completed":
                c.update(identity=p.get("identity"), grade=p.get("grade"), confidence=p.get("confidence"))
            elif e["type"] == "decision.made":
                c.update(agent_action=p.get("action"), uplift=p.get("uplift_vs_liquidate"),
                         precedent=p.get("precedent_ref"), decided_ts=e["ts"])
            elif e["type"] == "case.escalated":
                c.setdefault("agent_action", "ESCALATE")
                c["escalated"] = True
                c.setdefault("decided_ts", e["ts"])
            elif e["type"] in ("case.closed", "case.failed"):
                c.update(final_action=p.get("action"), decided_by=p.get("decided_by"), closed_ts=e["ts"])
        out = []
        for rid, g in sorted(gt.items()):
            c = cases.get(rid, {})
            agent = "ESCALATE" if c.get("escalated") else c.get("agent_action")
            out.append({**c, "case_id": rid, "key": g["key"], "set": g["set"], "gt_identity": g["gt_identity"],
                        "gt_grade": g["gt_grade"], "gt_action": g["gt_action"], "gt_escalate": g["gt_escalate"],
                        "agent": agent, "action_ok": agent == g["gt_action"],
                        "identity_ok": c.get("identity") == g["gt_identity"],
                        "secs": round((c.get("decided_ts", 0) - c.get("opened_ts", 0)) / 1000, 1)
                        if c.get("decided_ts") else None})
        return out

    def metrics(self, rows: list[dict]) -> dict:
        done = [r for r in rows if r.get("agent")]
        mism = [r for r in done if r["gt_identity"] == "mismatch"]
        should_esc = [r for r in done if r["gt_escalate"]]
        auto = [r for r in done if not r["gt_escalate"]]
        pct = lambda a, b: round(100 * a / b, 1) if b else None  # noqa: E731
        secs = [r["secs"] for r in done if r.get("secs")]
        return {
            "cases": len(rows), "completed": len(done),
            "action_accuracy": pct(sum(r["action_ok"] for r in done), len(done)),
            "identity_accuracy": pct(sum(r["identity_ok"] for r in done), len(done)),
            "fraud_catch_rate": pct(sum(r["agent"] == "ESCALATE" for r in mism), len(mism)),
            "unsafe_auto_resolves": sum(r["agent"] != "ESCALATE" for r in should_esc),
            "false_escalations": sum(r["agent"] == "ESCALATE" for r in auto),
            "grade_accuracy": pct(sum(r.get("grade") == r["gt_grade"] for r in done if r["gt_identity"] == "match"),
                                  len([r for r in done if r["gt_identity"] == "match"])),
            "uplift_vs_liquidate_usd": round(sum(r.get("uplift") or 0 for r in done), 2),
            "avg_secs_to_decision": round(sum(secs) / len(secs), 1) if secs else None,
        }

    def report(self, run_id: str, print_table: bool = False, save: bool = True) -> dict:
        rows = self.rows(run_id)
        m = self.metrics(rows)
        if print_table:
            print(f"{'case':8} {'gt_action':17} {'agent':17} {'ok':3} {'gt_id':9} {'id':9} {'conf':5} "
                  f"{'grade':5} {'secs':6} precedent")
            for r in rows:
                print(f"{r['key']:8} {r['gt_action']:17} {str(r['agent']):17} {'✓' if r['action_ok'] else '✗':3} "
                      f"{r['gt_identity']:9} {str(r.get('identity')):9} {str(r.get('confidence')):5} "
                      f"{r['gt_grade']}/{str(r.get('grade')):3} {str(r.get('secs')):6} {r.get('precedent') or ''}")
            print(json.dumps(m, indent=1))
        if save:
            self.db.insert("eval_runs", {"run_id": run_id, "ts_ms": now_ms(), **m})
        return m
