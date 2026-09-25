"""Operator: warehouse sub-agent. Executes the disposition in RawTree, then verifies by reading it back."""
from __future__ import annotations

import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ..warehouse import Warehouse, warehouse
from .base import SubAgent

# action -> (location, state, document the action creates)
PLAYBOOK = {
    "RESTOCK": ("OPEN_BOX_SHELF", "SELLABLE_OPEN_BOX", "open-box listing"),
    "REFURBISH": ("REFURB_BENCH", "AWAITING_REPAIR", "repair work order"),
    "RETURN_TO_VENDOR": ("RTV_STAGING", "AWAITING_PICKUP", "RTV authorization"),
    "LIQUIDATE": ("LIQUIDATION_CAGE", "LOTTED", "liquidation lot"),
}


class OperateState(TypedDict, total=False):
    case: dict
    action: str
    detail: dict
    attempts: int
    result: dict


class Operator(SubAgent):
    name = "operator"

    def __init__(self, *args, store: Warehouse = warehouse, **kw):
        self.store = store
        super().__init__(*args, **kw)

    def build(self) -> StateGraph:
        g = StateGraph(OperateState)
        g.add_node("execute", self.execute)
        g.add_node("verify", self.verify)
        g.add_edge(START, "execute")
        g.add_edge("execute", "verify")
        g.add_conditional_edges("verify", lambda s: END if s.get("result") else "execute")
        return g

    def run(self, case: dict, action: str = "LIQUIDATE", detail: dict | None = None, **inputs) -> dict:
        return self.graph.invoke({"case": case, "action": action, "detail": detail or {}, "attempts": 0})["result"]

    def execute(self, s: OperateState) -> dict:
        case, action = s["case"], s["action"]
        location, state, doc = PLAYBOOK[action]
        doc_id = f"{doc.split()[-1][:3].upper()}-{case['case_id']}"
        self.store.move_unit(case["run_id"], case["unit_id"], case["product"]["sku"], case["case_id"],
                             location, state, action=action, document=doc, document_id=doc_id, **s["detail"])
        self.log(case, "operator.executed", f"{action}: unit {case['unit_id']} → {location} ({doc} {doc_id})",
                 {"action": action, "location": location, "state": state, "document": doc, "document_id": doc_id,
                  **s["detail"]})
        return {"attempts": s["attempts"] + 1}

    def verify(self, s: OperateState) -> dict:
        case = s["case"]
        location, state, _ = PLAYBOOK[s["action"]]
        for delay in (0.3, 0.5, 0.8, 1.2, 2.0):
            row = self.store.unit_state(case["run_id"], case["unit_id"])
            if row and row["loc"] == location and row["st"] == state:
                self.log(case, "operator.verified", f"Verified in RawTree: {location} / {state}",
                         {"location": location, "state": state})
                return {"result": {"action": s["action"], "location": location, "state": state, "verified": True}}
            time.sleep(delay)
        if s["attempts"] >= 2:
            raise RuntimeError(f"could not verify unit {case['unit_id']} at {location}")
        return {}
