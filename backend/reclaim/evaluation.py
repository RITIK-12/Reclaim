"""Scores a run against ground truth (reclaim_eval_gt). Agents never read ground truth; only this does."""
from __future__ import annotations

import json

from .rawtree import RawTree, db, now_ms, sql_str


class Evaluator:
    def __init__(self, store: RawTree = db):
        self.db = store

    def rows(self, run_id: str) -> list[dict]:
        run = sql_str(run_id)
        gt = {r["return_id"]: r for r in self.db.query(  # newest label per return wins (corrections are appended)
            f"SELECT * FROM {{t:eval_gt}} WHERE run_id = {run} ORDER BY toInt64(seeded_at_ms)")}
        events = self.db.query(f"SELECT toString(case_id) AS cid, toString(type) AS type, toString(payload) AS payload, "
                               f"toInt64(ts_ms) AS ts FROM {{t:mem_events}} WHERE run_id = {run} AND toString(type) IN "
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
            out.append({**c, "case_id": rid, "key": g["key"], "set": g["set"], "category": g.get("category"),
                        "scenario": g.get("scenario"), "gt_rule": g.get("gt_why"), "gt_identity": g["gt_identity"],
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
        matches = [r for r in done if r["gt_identity"] == "match" and r.get("identity") == "match"]
        pct = lambda a, b: round(100 * a / b, 1) if b else None  # noqa: E731
        secs = [r["secs"] for r in done if r.get("secs")]
        return {
            "cases": len(rows), "completed": len(done),
            "action_accuracy": pct(sum(r["action_ok"] for r in done), len(done)),
            "identity_accuracy": pct(sum(r["identity_ok"] for r in done), len(done)),
            "fraud_catch_rate": pct(sum(r["agent"] == "ESCALATE" for r in mism), len(mism)),
            "unsafe_auto_resolves": sum(r["agent"] != "ESCALATE" for r in should_esc),
            "false_escalations": sum(r["agent"] == "ESCALATE" for r in auto),
            "grade_accuracy": pct(sum(r.get("grade") == r["gt_grade"] for r in matches), len(matches)),
            "grade_within_one": pct(sum(abs(ord(r.get("grade") or "Z") - ord(r["gt_grade"])) <= 1 for r in matches),
                                    len(matches)),
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


ACTION_ORDER = ("RESTOCK", "REFURBISH", "RETURN_TO_VENDOR", "LIQUIDATE", "ESCALATE")


def _pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}%" if b else "—"


def markdown_report(ev: Evaluator, run_id: str, title: str, notes: list[str]) -> str:
    """Full evaluation report for a run: headline metrics, confusion matrix, per action/category, failures."""
    rows = ev.rows(run_id)
    done = [r for r in rows if r.get("agent")]
    m = ev.metrics(rows)
    tel = ev.db.one(f"SELECT count() AS calls, avg(toFloat64(latency_ms)) AS ms, sum(toInt64(prompt_tokens)) AS pt, "
                    f"sum(toInt64(completion_tokens)) AS ct, avgIf(toFloat64(brief_tokens), toFloat64(brief_tokens) > 0) "
                    f"AS brief FROM {{t:llm_calls}} WHERE run_id = '{run_id}'") or {}
    web = ev.db.one(f"SELECT countIf(toString(type) = 'market.search') AS searches, countIf(toString(type) = "
                    f"'market.cache_hit') AS hits, countIf(toString(type) = 'inspector.reinspect') AS reinspect, "
                    f"countIf(toString(type) = 'supervisor.route' AND position(toString(payload), '\"by\": \"llm\"') > 0) "
                    f"AS llm_routes, count() AS events FROM {{t:mem_events}} WHERE run_id = '{run_id}'") or {}
    secs = sorted(r["secs"] for r in done if r.get("secs"))
    q = lambda p: secs[min(len(secs) - 1, int(p * len(secs)))] if secs else 0  # noqa: E731
    L = [f"# {title}", "", f"Run `{run_id}` · {len(done)}/{len(rows)} returns processed end to end by the agent "
         "(proactive trigger → Inspector → Market Analyst → decision → escalation or Operator → verify).", ""]
    L += [*notes, "", "## Headline", "", "| Metric | Result |", "|---|---|",
          f"| Action accuracy | **{m['action_accuracy']}%** ({sum(r['action_ok'] for r in done)}/{len(done)}) |",
          f"| Identity accuracy (right item vs wrong item) | {m['identity_accuracy']}% |",
          f"| Wrong-item / fraud returns sent to a human | {m['fraud_catch_rate']}% |",
          f"| Unsafe auto-resolves (should have gone to a human) | **{m['unsafe_auto_resolves']}** |",
          f"| False escalations (human bothered for nothing) | {m['false_escalations']} |",
          f"| Condition grade exact / within one step | {m['grade_accuracy']}% / {m['grade_within_one']}% |",
          f"| Extra value recovered vs liquidate-all (auto-resolved cases) | ${m['uplift_vs_liquidate_usd']:,.0f} |",
          f"| Time to decision: mean / median / p90 | {m['avg_secs_to_decision']} s / {q(0.5)} s / {q(0.9)} s |",
          f"| Liquid calls (avg latency) | {int(tel.get('calls') or 0)} ({float(tel.get('ms') or 0):.0f} ms) |",
          f"| Tokens: prompt / completion | {int(tel.get('pt') or 0):,} / {int(tel.get('ct') or 0):,} |",
          f"| Avg working-memory brief per Supervisor call | {float(tel.get('brief') or 0):.0f} tokens |",
          f"| Nimble searches / memory hits | {int(web.get('searches') or 0)} / {int(web.get('hits') or 0)} |",
          f"| Re-inspections (second photo) / LLM routing decisions | {int(web.get('reinspect') or 0)} / "
          f"{int(web.get('llm_routes') or 0)} |",
          f"| Ledger events written to RawTree | {int(web.get('events') or 0):,} |", ""]
    # confusion matrix
    L += ["## Confusion matrix (rows = ground truth, columns = agent)", "",
          "| truth \\ agent | " + " | ".join(a.replace("RETURN_TO_VENDOR", "RTV") for a in ACTION_ORDER) + " | recall |",
          "|---|" + "---|" * (len(ACTION_ORDER) + 1)]
    for gt in ACTION_ORDER:
        grp = [r for r in done if r["gt_action"] == gt]
        cells = [str(sum(r["agent"] == a for r in grp)) for a in ACTION_ORDER]
        L.append(f"| **{gt.replace('RETURN_TO_VENDOR', 'RTV')}** | " + " | ".join(cells) +
                 f" | {_pct(sum(r['action_ok'] for r in grp), len(grp))} |")
    prec = [_pct(sum(r["action_ok"] for r in done if r["agent"] == a), sum(r["agent"] == a for r in done))
            for a in ACTION_ORDER]
    L += ["| precision | " + " | ".join(prec) + " | |", ""]
    # per category
    cats = sorted({r["category"] for r in done if r.get("category")})
    if cats:
        L += ["## By product category", "", "| Category | Action accuracy | Identity accuracy | Avg secs |", "|---|---|---|---|"]
        for c in cats:
            g = [r for r in done if r["category"] == c]
            s = [r["secs"] for r in g if r.get("secs")]
            L.append(f"| {c} | {_pct(sum(r['action_ok'] for r in g), len(g))} | "
                     f"{_pct(sum(r['identity_ok'] for r in g), len(g))} | {sum(s) / len(s):.1f} |" if s else f"| {c} | — | — | — |")
        L.append("")
    scen = sorted({r["scenario"] for r in done if r.get("scenario")})
    if scen:
        L += ["## By scenario", "", "| Scenario | Cases | Correct |", "|---|---|---|"]
        for sc in scen:
            g = [r for r in done if r["scenario"] == sc]
            L.append(f"| {sc} | {len(g)} | {_pct(sum(r['action_ok'] for r in g), len(g))} |")
        L.append("")
    test = [r for r in done if r.get("set") == "test"]
    if test:
        L += ["## Held-out test split (10 returns, baseline before any tuning)", "",
              f"Action accuracy {_pct(sum(r['action_ok'] for r in test), len(test))}, identity accuracy "
              f"{_pct(sum(r['identity_ok'] for r in test), len(test))}.", "",
              "| Case | Category | Truth | Agent | OK |", "|---|---|---|---|---|"]
        L += [f"| {r['key']} | {r['category']} | {r['gt_action']} | {r['agent']} | {'✓' if r['action_ok'] else '✗'} |"
              for r in test]
        L.append("")
    fails = [r for r in done if not r["action_ok"]]
    L += [f"## Misses ({len(fails)})", "", "| Case | Category | Scenario | Truth | Agent | Identity (truth/agent) | Grade (truth/agent) |",
          "|---|---|---|---|---|---|---|"]
    L += [f"| {r['key']} | {r.get('category')} | {r.get('scenario')} | {r['gt_action']} | {r['agent']} | "
          f"{r['gt_identity']}/{r.get('identity')} | {r['gt_grade']}/{r.get('grade')} |" for r in fails]
    return "\n".join(L) + "\n"
