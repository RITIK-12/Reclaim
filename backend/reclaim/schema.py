"""Column sets for every run-scoped RawTree table (all prefixed reclaim_).

RawTree stores rows as JSON and a path can only be queried once some row has it, so `ensure_schema`
writes one sentinel row (run_id = "_init") per table with every column. All real queries filter by run_id.

Warehouse (system of record): orders, returns, inventory
Agent memory:                 mem_events, mem_knowledge, mem_decisions, mem_evidence
Telemetry and scoring:        llm_calls, eval_gt, eval_runs
Reference (seeded once):      products, vendors, cost_model   (see scripts/seed_catalog.py)
Synthetic dataset:            dataset, dataset_images         (see scripts/build_dataset.py)
"""
from __future__ import annotations

from .rawtree import RawTree, db, now_ms

SENTINEL = "_init"
SCHEMAS: dict[str, dict] = {
    "orders": {"order_id": "", "sku": "", "customer_id": "", "price_paid": 0.0, "purchased_at_ms": 0},
    "returns": {"return_id": "", "order_id": "", "sku": "", "customer_id": "", "reason_text": "",
                "reason_category": "", "photos": [""], "received_at_ms": 0, "scenario_key": ""},
    "inventory": {"unit_id": "", "sku": "", "case_id": "", "location": "", "state": "", "action": "",
                  "document": "", "document_id": "", "ts_ms": 0},
    "mem_events": {"case_id": "", "event_id": "", "ts_ms": 0, "agent": "", "type": "", "summary": "",
                   "payload": "{}"},
    "mem_knowledge": {"subject": "", "predicate": "", "value": 0.0, "source_url": "", "learned_in_case": "",
                      "observed_at_ms": 0, "expires_at_ms": 0},
    "mem_decisions": {"case_id": "", "action": "", "decided_by": "", "precedent_key": "", "rationale": "",
                      "fraud_flag": False, "note": "", "precedent_ref": "", "ev": "{}", "uplift": 0.0, "ts_ms": 0},
    "mem_evidence": {"case_id": "", "sku": "", "tool": "", "query": "", "url": "", "title": "", "price": 0.0,
                     "kind": "", "fetched_at_ms": 0, "accepted": False, "rejected_because": ""},
    "llm_calls": {"case_id": "", "agent": "", "node": "", "latency_ms": 0, "prompt_tokens": 0,
                  "completion_tokens": 0, "brief_tokens": 0, "ts_ms": 0},
    "eval_gt": {"return_id": "", "key": "", "set": "", "seeded_at_ms": 0, "gt_identity": "", "gt_grade": "", "gt_action": "",
                "gt_escalate": False, "gt_fraud": False, "gt_why": ""},
    "eval_runs": {"ts_ms": 0, "cases": 0, "completed": 0, "action_accuracy": 0.0, "identity_accuracy": 0.0,
                  "fraud_catch_rate": 0.0, "unsafe_auto_resolves": 0, "false_escalations": 0,
                  "grade_accuracy": 0.0, "grade_within_one": 0.0, "uplift_vs_liquidate_usd": 0.0, "avg_secs_to_decision": 0.0},
}


def ensure_schema(store: RawTree = db) -> list[str]:
    """Write a full sentinel row into any table whose columns are not all queryable yet."""
    fixed = []
    for table, cols in SCHEMAS.items():
        try:
            store.query(f"SELECT {', '.join(['run_id', *cols])} FROM {{t:{table}}} WHERE run_id = '{SENTINEL}' LIMIT 1")
        except RuntimeError:
            store.insert(table, {"run_id": SENTINEL, **cols, **({"ts_ms": now_ms()} if "ts_ms" in cols else {})})
            fixed.append(table)
    return fixed
