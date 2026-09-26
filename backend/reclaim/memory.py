"""Agent memory in RawTree, separate from warehouse tables.

  mem_events     episodic ledger: every supervisor/sub-agent/tool step (the UI timeline)
  mem_knowledge  semantic memory: price facts with a TTL, shared across cases
  mem_decisions  decisions; rows decided_by='human' are precedents for later cases
  mem_evidence   web sources behind every price
  llm_calls      telemetry per LLM call, incl. brief size (context meter)

Memory is namespaced by run_id: a run is one warehouse shift, so a fresh run starts with clean memory.
The brief is the agent's working memory: rebuilt from these tables for each call, never stored.
"""
from __future__ import annotations

import json
import uuid

from .config import settings
from .rawtree import RawTree, db, now_ms, sql_str


def _j(v) -> str:
    return json.dumps(v, default=str)


class Memory:
    def __init__(self, store: RawTree = db):
        self.db = store

    # --- episodic -------------------------------------------------------------------------------
    def log(self, run_id: str, case_id: str, agent: str, type_: str, summary: str, payload: dict | None = None) -> dict:
        row = {"run_id": run_id, "case_id": case_id, "event_id": uuid.uuid4().hex[:12], "ts_ms": now_ms(),
               "agent": agent, "type": type_, "summary": summary, "payload": _j(payload or {})}
        self.db.insert("mem_events", row, wait=False)
        return row

    def events(self, run_id: str, case_id: str) -> list[dict]:
        rows = self.db.query(f"SELECT * FROM {{t:mem_events}} WHERE run_id = {sql_str(run_id)} "
                             f"AND case_id = {sql_str(case_id)} ORDER BY toInt64(ts_ms)")
        for r in rows:
            r["payload"] = json.loads(r.get("payload") or "{}")
        return rows

    def case_heads(self, run_id: str) -> dict[str, dict]:
        """Latest event per case: the status projection. On a same-millisecond tie the terminal event wins."""
        rank = "toInt64(ts_ms) * 10 + (toString(type) IN ('case.closed', 'case.failed'))"
        rows = self.db.query(
            f"SELECT toString(case_id) AS cid, argMax(toString(type), {rank}) AS last_type, "
            f"argMax(toString(summary), {rank}) AS last_summary, max(toInt64(ts_ms)) AS last_ts, "
            f"min(toInt64(ts_ms)) AS first_ts, count() AS n FROM {{t:mem_events}} "
            f"WHERE run_id = {sql_str(run_id)} GROUP BY cid")
        return {r["cid"]: r for r in rows}

    def ledger_size(self, run_id: str) -> int:
        row = self.db.one(f"SELECT count() AS n FROM {{t:mem_events}} WHERE run_id = {sql_str(run_id)}")
        return int(row["n"]) if row else 0

    # --- semantic (price facts with TTL) -----------------------------------------------------------
    def facts(self, run_id: str, sku: str) -> dict[str, dict]:
        rows = self.db.query(
            f"SELECT toString(predicate) AS p, argMax(toFloat64(value), toInt64(observed_at_ms)) AS v, "
            f"argMax(toString(source_url), toInt64(observed_at_ms)) AS src, max(toInt64(observed_at_ms)) AS at "
            f"FROM {{t:mem_knowledge}} WHERE run_id = {sql_str(run_id)} AND subject = {sql_str(sku)} "
            f"AND toInt64(expires_at_ms) > {now_ms()} GROUP BY p")
        return {r["p"]: {"value": r["v"], "source_url": r["src"], "observed_at_ms": r["at"]} for r in rows}

    def remember_facts(self, run_id: str, case_id: str, sku: str, facts: dict[str, tuple[float, str]]) -> None:
        now = now_ms()
        ttl = settings.price_ttl_hours * 3600_000
        rows = [{"run_id": run_id, "subject": sku, "predicate": p, "value": v, "source_url": src,
                 "learned_in_case": case_id, "observed_at_ms": now, "expires_at_ms": now + ttl}
                for p, (v, src) in facts.items() if v]
        if rows:
            self.db.insert("mem_knowledge", rows)

    # --- evidence ---------------------------------------------------------------------------------
    def add_evidence(self, run_id: str, case_id: str, sku: str, rows: list[dict]) -> None:
        if rows:
            self.db.insert("mem_evidence", [{"run_id": run_id, "case_id": case_id, "sku": sku, **r} for r in rows],
                           wait=False)

    def evidence(self, run_id: str, case_id: str) -> list[dict]:
        return self.db.query(f"SELECT * FROM {{t:mem_evidence}} WHERE run_id = {sql_str(run_id)} "
                             f"AND case_id = {sql_str(case_id)} ORDER BY toInt64(fetched_at_ms)")

    # --- decisions + precedent --------------------------------------------------------------------
    def record_decision(self, run_id: str, case_id: str, action: str, decided_by: str, key: str,
                        rationale: str = "", fraud_flag: bool = False, precedent_ref: str | None = None,
                        ev: dict | None = None, uplift: float = 0.0, note: str = "") -> None:
        self.db.insert("mem_decisions", {
            "run_id": run_id, "case_id": case_id, "action": action, "decided_by": decided_by,
            "precedent_key": key, "rationale": rationale, "fraud_flag": fraud_flag, "note": note,
            "precedent_ref": precedent_ref or "", "ev": _j(ev or {}), "uplift": uplift, "ts_ms": now_ms()})

    def precedent(self, run_id: str, key: str, exclude_case: str) -> dict | None:
        return self.db.one(f"SELECT toString(case_id) AS case_id, toString(action) AS action, "
                           f"toString(note) AS note FROM {{t:mem_decisions}} WHERE run_id = {sql_str(run_id)} "
                           f"AND decided_by = 'human' AND precedent_key = {sql_str(key)} "
                           f"AND case_id != {sql_str(exclude_case)} ORDER BY toInt64(ts_ms) DESC LIMIT 1")

    def decisions(self, run_id: str) -> list[dict]:
        return self.db.query(f"SELECT * FROM {{t:mem_decisions}} WHERE run_id = {sql_str(run_id)} "
                             f"ORDER BY toInt64(ts_ms)")

    # --- history used in the brief ------------------------------------------------------------------
    def history(self, run_id: str, sku: str, customer_id: str, case_id: str) -> dict:
        sku_rows = self.db.query(f"SELECT count() AS n FROM {{t:returns}} WHERE run_id = {sql_str(run_id)} "
                                 f"AND sku = {sql_str(sku)} AND return_id != {sql_str(case_id)}")
        cust = self.db.query(
            f"SELECT count() AS n, countIf(toString(fraud_flag) IN ('true', '1')) AS flags FROM {{t:mem_decisions}} "
            f"WHERE run_id = {sql_str(run_id)} AND toString(case_id) IN (SELECT toString(return_id) FROM {{t:returns}} "
            f"WHERE run_id = {sql_str(run_id)} AND customer_id = {sql_str(customer_id)} "
            f"AND return_id != {sql_str(case_id)})")
        return {"sku_returns": int(sku_rows[0]["n"]) if sku_rows else 0,
                "customer_returns": int(cust[0]["n"]) if cust else 0,
                "customer_fraud_flags": int(cust[0]["flags"]) if cust else 0}

    # --- telemetry --------------------------------------------------------------------------------
    def log_llm(self, run_id: str, case_id: str, agent: str, call, brief_tokens: int = 0) -> None:
        self.db.insert("llm_calls", {"run_id": run_id, "case_id": case_id, "agent": agent, "node": call.node,
                                     "latency_ms": call.latency_ms, "prompt_tokens": call.prompt_tokens,
                                     "completion_tokens": call.completion_tokens, "brief_tokens": brief_tokens,
                                     "ts_ms": now_ms()}, wait=False)


def build_brief(case: dict, history: dict, facts: dict, precedent: dict | None, results: dict) -> str:
    """Working memory for one call: short, purpose-built, bounded (~800 tokens max)."""
    p, o, r = case["product"], case["order"], case["return"]
    lines = [
        f"RETURN {r['return_id']}: {r['reason_category']} — \"{r['reason_text']}\"",
        f"PRODUCT: {p['title'][:120]} | brand {p['brand']} | category {p['category']} | list ${p['list_price']}",
        f"ORDER: paid ${o['price_paid']} {o['days_since_purchase']} days ago | sold as {p['condition_at_sale']}",
        f"HISTORY: {history.get('sku_returns', 0)} other returns of this SKU this shift; customer has "
        f"{history.get('customer_returns', 0)} other returns, {history.get('customer_fraud_flags', 0)} fraud flags",
    ]
    if facts:
        lines.append("KNOWN PRICES: " + ", ".join(f"{k} ${v['value']:.0f}" for k, v in facts.items()))
    if precedent:
        lines.append(f"PRECEDENT: human chose {precedent['action']} for similar case {precedent['case_id']}")
    for name, value in results.items():
        if value:
            lines.append(f"{name.upper()}: {json.dumps(value, default=str)[:400]}")
    return "\n".join(lines)


def tokens(text: str) -> int:
    return max(1, len(text) // 4)


memory = Memory()
