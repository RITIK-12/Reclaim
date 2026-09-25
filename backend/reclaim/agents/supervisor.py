"""Supervisor: the main agent. Owns a case from dock to closure, calls sub-agents, pauses for humans.

Routing has two layers: `allowed_next` (deterministic) lists the legal next steps; when more than one
is legal the Liquid model chooses, with a stated reason. Every step lands in the RawTree ledger.
"""
from __future__ import annotations

import time
import traceback
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from ..config import settings
from ..decision import ACTIONS, ESCALATE, DecisionInput, decide, precedent_key
from ..llm import LiquidLLM, llm
from ..memory import Memory, build_brief, memory, tokens
from ..warehouse import Warehouse, warehouse
from .inspector import Inspector
from .market import MarketAnalyst
from .operator import Operator


class CaseState(TypedDict, total=False):
    run_id: str
    case_id: str
    case: dict
    inspection: dict
    market: dict
    decision: dict
    escalation: dict
    human: dict
    execution: dict
    researched: bool
    steps: int
    next: str
    error: str


class RouteChoice(BaseModel):
    next: Literal["research_more", "decide"]
    reason: str = Field(description="One short sentence")


ROUTER_SYSTEM = ("You supervise a warehouse returns team. Pick the next step for this case. Prefer acting "
                 "over waiting, but do not decide on evidence that is too thin to trust.")
RATIONALE_SYSTEM = ("You explain a warehouse disposition decision in at most two short sentences, using only "
                    "the facts given. No preamble.")


class Supervisor:
    name = "supervisor"

    def __init__(self, mem: Memory = memory, model: LiquidLLM = llm, store: Warehouse = warehouse,
                 checkpointer=None):
        self.memory, self.llm, self.store = mem, model, store
        self.inspector = Inspector(mem, model)
        self.market = MarketAnalyst(mem, model)
        self.operator = Operator(mem, model, store=store)
        self.graph = self.build().compile(checkpointer=checkpointer)

    def build(self) -> StateGraph:
        g = StateGraph(CaseState)
        g.add_node("open", self.open_case)
        g.add_node("route", self.route)
        g.add_node("inspect", self._guarded(lambda s: {"inspection": self.inspector.run(s["case"])}, "inspector"))
        g.add_node("price", self._guarded(
            lambda s: {"market": self.market.run(s["case"], deep=s.get("researched", False))}, "market"))
        g.add_node("decide", self._guarded(self.decide, "decide"))
        g.add_node("flag", self.flag)
        g.add_node("await_human", self.await_human)
        g.add_node("operate", self._guarded(self.operate, "operator"))
        g.add_node("close", self.close)
        g.add_edge(START, "open")
        g.add_edge("open", "route")
        g.add_conditional_edges("route", lambda s: s["next"],
                                {n: n for n in ("inspect", "price", "decide", "flag", "operate", "close")})
        for n in ("inspect", "price", "decide", "operate"):
            g.add_edge(n, "route")
        g.add_edge("flag", "await_human")
        g.add_edge("await_human", "route")
        g.add_edge("close", END)
        return g

    # --- routing ------------------------------------------------------------------------------------
    @staticmethod
    def allowed_next(s: CaseState, steps: int) -> list[tuple[str, str]]:
        if s.get("error"):
            return [("close", "failed after the human decision")] if s.get("human") else \
                [("flag", f"a sub-agent failed ({s['error'][:80]})")]
        if steps > settings.max_steps:
            return [("close", "step budget exhausted")] if s.get("human") else [("flag", "step budget exhausted")]
        if s.get("execution"):
            return [("close", "disposition executed and verified")]
        if s.get("human"):
            return [("operate", f"human decided {s['human']['action']}")]
        d = s.get("decision")
        if d:
            return [("flag", d["escalation_reason"])] if d["action"] == ESCALATE else \
                [("operate", f"auto-execute {d['action']}")]
        insp = s.get("inspection")
        if not insp:
            return [("inspect", "inspection comes first")]
        if insp["identity"] == "mismatch":
            return [("flag", "the item does not match the order; no point pricing it")]
        m = s.get("market")
        if not m:
            return [("price", "need live market prices")]
        if m["weak"] and not s.get("researched"):
            return [("research_more", f"evidence is thin ({', '.join(m['kinds_found']) or 'no prices'}); "
                                      "one more search round"),
                    ("decide", "decide now, estimating the missing prices")]
        return [("decide", "inspection and prices are in")]

    def route(self, s: CaseState) -> dict:
        steps = s.get("steps", 0) + 1
        options = self.allowed_next(s, steps)
        if len(options) == 1:
            nxt, why, by = *options[0], "rule"
        else:
            nxt, why = self.choose(s, options)
            by = "llm"
        self.log(s["case"], "supervisor.route", f"→ {nxt}: {why}",
                 {"next": nxt, "reason": why, "by": by, "options": [o[0] for o in options]})
        update: dict = {"next": "price" if nxt == "research_more" else nxt, "steps": steps}
        if nxt == "research_more":
            update["researched"] = True
        return update

    def choose(self, s: CaseState, options: list[tuple[str, str]]) -> tuple[str, str]:
        menu = "\n".join(f"- {name}: {why}" for name, why in options)
        try:
            brief = self.brief(s)
            out, call = self.llm.structured(RouteChoice, ROUTER_SYSTEM, f"{brief}\n\nOPTIONS:\n{menu}",
                                            node="supervisor.route")
            self.memory.log_llm(s["run_id"], s["case_id"], self.name, call, tokens(brief))
            if out.next in {o[0] for o in options}:
                return out.next, out.reason
        except Exception:  # noqa: BLE001 - the router must never break the case
            pass
        return options[-1][0], "default choice (router unavailable)"

    # --- nodes --------------------------------------------------------------------------------------
    def open_case(self, s: CaseState) -> dict:
        run_id, case_id = s["run_id"], s["case_id"]
        r = o = p = None
        for delay in (0, 0.5, 1.0, 2.0, 3.0, 4.0):  # RawTree ingest delay: rows can take a moment to appear
            time.sleep(delay)
            r = self.store.return_(run_id, case_id)
            o = r and self.store.order(run_id, r["order_id"])
            p = r and self.store.product(r["sku"])
            if r and o and p:
                break
        else:
            raise RuntimeError(f"{case_id}: return/order/product rows not visible in RawTree")
        days = max(0, int((int(r["received_at_ms"]) - int(o["purchased_at_ms"])) / 86_400_000))
        keep = ("return_id", "order_id", "sku", "customer_id", "reason_text", "reason_category", "photos",
                "received_at_ms")
        case = {"run_id": run_id, "case_id": case_id, "unit_id": f"U-{case_id}",
                "return": {k: r.get(k) for k in keep},
                "order": {"order_id": o["order_id"], "price_paid": float(o["price_paid"]),
                          "days_since_purchase": days},
                "product": {k: p.get(k) for k in ("sku", "title", "brand", "model", "category", "family",
                                                  "repairable", "list_price", "condition_at_sale", "image_url")}}
        self.store.move_unit(run_id, case["unit_id"], p["sku"], case_id, "RECEIVING_DOCK", "RECEIVED")
        self.log(case, "case.opened", f"{p['title'][:70]} arrived — \"{r['reason_text']}\"",
                 {"return": case["return"], "order": case["order"], "product": case["product"]})
        return {"case": case, "steps": 0}

    def decide(self, s: CaseState) -> dict:
        case, insp, m = s["case"], s["inspection"], s["market"]
        p, o, r = case["product"], case["order"], case["return"]
        key = precedent_key(p["category"], insp["defect_class"], r["reason_category"], insp["grade"])
        x = DecisionInput(
            category=p["category"], repairable=bool(p["repairable"]), condition_at_sale=p["condition_at_sale"],
            price_paid=o["price_paid"], list_price=float(p["list_price"]),
            days_since_purchase=o["days_since_purchase"], reason_category=r["reason_category"],
            identity=insp["identity"], match_confidence=insp["confidence"], grade=insp["grade"],
            defect_class=insp["defect_class"], defect_visible=insp["defect_visible"],
            market={k: m.get(k) for k in ("new", "used", "refurb", "open_box")},
            cost=self.store.cost_model(p["category"]), vendor=self.store.vendor(p["brand"]),
            precedent=self.memory.precedent(case["run_id"], key, case["case_id"]))
        d = decide(x).to_dict() | {"precedent_key": key}
        d["rationale"] = self.rationale(s, d)
        if d["action"] != ESCALATE:
            self.memory.record_decision(case["run_id"], case["case_id"], d["action"], "agent", key,
                                        d["rationale"], precedent_ref=d["precedent_ref"], ev=d["ev"],
                                        uplift=d["uplift_vs_liquidate"])
        head = f"ESCALATE: {d['escalation_reason']}" if d["action"] == ESCALATE else \
            f"{d['action']} (EV ${d['ev'][d['action']]:.0f}, +${d['uplift_vs_liquidate']:.0f} vs liquidate)"
        if d["precedent_ref"]:
            head += f" — following human precedent {d['precedent_ref']}"
        self.log(case, "decision.made", head, d)
        return {"decision": d}

    def rationale(self, s: CaseState, d: dict) -> str:
        facts = (f"Decision: {d['action']}. Allowed: {d['allowed']}. EV per action: {d['ev']}. "
                 f"Rules: {d['rules_fired'][-2:]}. Escalation reason: {d['escalation_reason']}. "
                 f"Precedent: {d['precedent_ref']}.")
        try:
            brief = self.brief(s)
            text, call = self.llm.text(RATIONALE_SYSTEM, f"{brief}\n\n{facts}", node="supervisor.rationale")
            self.memory.log_llm(s["run_id"], s["case_id"], self.name, call, tokens(brief))
            return text[:400]
        except Exception:  # noqa: BLE001
            return facts

    def flag(self, s: CaseState) -> dict:
        case, d, insp = s["case"], s.get("decision") or {}, s.get("inspection") or {}
        mismatch = insp.get("identity") == "mismatch"
        reason = d.get("escalation_reason") or (f"Sub-agent failure: {s['error']}" if s.get("error") else None) \
            or ("The returned item does not match the ordered product (possible return fraud)." if mismatch
                else "Needs human review.")
        packet = {"reason": reason, "rules_fired": d.get("rules_fired", []),
                  "suggested_action": d.get("suggested_action") or "LIQUIDATE", "fraud_suspected": mismatch,
                  "inspection": insp, "market": s.get("market"), "ev": d.get("ev"),
                  "photos": case["return"]["photos"], "catalog_image": f"cat_{case['product']['sku']}.jpg"}
        self.store.move_unit(case["run_id"], case["unit_id"], case["product"]["sku"], case["case_id"],
                             "QUARANTINE", "HOLD_FOR_REVIEW")
        self.log(case, "case.escalated", reason, packet)
        return {"escalation": packet}

    def await_human(self, s: CaseState) -> dict:
        """Durable pause: the graph checkpoints here and resumes when a human decides (hours later is fine)."""
        human = interrupt(s["escalation"])
        case, insp = s["case"], s.get("inspection") or {}
        action = human.get("action") if human.get("action") in ACTIONS else "LIQUIDATE"
        key = (s.get("decision") or {}).get("precedent_key") or precedent_key(
            case["product"]["category"], insp.get("defect_class", "unknown"), case["return"]["reason_category"],
            insp.get("grade", "D"))
        fraud = bool(human.get("fraud_flag"))
        self.memory.record_decision(case["run_id"], case["case_id"], action, "human", key, human.get("note", ""),
                                    fraud_flag=fraud, note=human.get("note", ""),
                                    ev=(s.get("decision") or {}).get("ev"))
        self.log(case, "human.decided", f"Human chose {action}" + (" and flagged fraud" if fraud else "") +
                 (f" — \"{human['note']}\"" if human.get("note") else ""), human)
        return {"human": {**human, "action": action}, "error": ""}  # the human's call supersedes a failure

    def operate(self, s: CaseState) -> dict:
        action = (s.get("human") or {}).get("action") or s["decision"]["action"]
        basis, ev = (s.get("decision") or {}).get("basis", {}), (s.get("decision") or {}).get("ev", {})
        detail = {"RESTOCK": {"listing_price": basis.get("open_box")},
                  "REFURBISH": {"expected_resale": basis.get("refurb")},
                  "RETURN_TO_VENDOR": {"expected_credit": ev.get("RETURN_TO_VENDOR")},
                  "LIQUIDATE": {"expected_recovery": ev.get("LIQUIDATE")}}[action]
        return {"execution": self.operator.run(s["case"], action=action,
                                               detail={k: v for k, v in detail.items() if v is not None})}

    def close(self, s: CaseState) -> dict:
        case, ex, d = s["case"], s.get("execution"), s.get("decision") or {}
        by = "human" if s.get("human") else "agent"
        if ex:
            self.log(case, "case.closed", f"Closed: {ex['action']} by {by}, unit at {ex['location']}",
                     {"action": ex["action"], "decided_by": by, "location": ex["location"],
                      "uplift_vs_liquidate": d.get("uplift_vs_liquidate"), "steps": s.get("steps")})
        else:
            self.log(case, "case.failed", f"Could not complete: {s.get('error')}", {"error": s.get("error")})
        return {}

    # --- helpers ------------------------------------------------------------------------------------
    def brief(self, s: CaseState) -> str:
        case = s["case"]
        r = case["return"]
        history = self.memory.history(case["run_id"], r["sku"], r["customer_id"], case["case_id"])
        facts = self.memory.facts(case["run_id"], r["sku"])
        results = {"inspection": {k: (s.get("inspection") or {}).get(k) for k in
                                  ("identity", "confidence", "grade", "defect_class", "observed")}
                   if s.get("inspection") else None,
                   "market": {k: (s.get("market") or {}).get(k) for k in ("new", "used", "refurb", "open_box")}
                   if s.get("market") else None}
        return build_brief(case, history, facts, None, results)

    def log(self, case: dict, type_: str, summary: str, payload: dict | None = None) -> None:
        self.memory.log(case["run_id"], case["case_id"], self.name, type_, summary, payload)

    def _guarded(self, fn, label: str):
        def node(s: CaseState) -> dict:
            try:
                return fn(s)
            except Exception as e:  # noqa: BLE001 - failures escalate instead of crashing the case
                self.log(s["case"], "case.error", f"{label} failed: {e}", {"trace": traceback.format_exc()[-1500:]})
                return {"error": f"{label}: {e}"}
        return node
