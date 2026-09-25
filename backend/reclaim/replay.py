"""Dock replay: stands in for the dock scanner by inserting labelled returns into RawTree. Not a simulator:
it only writes order/return rows (and ground truth into eval_gt, which agents never read)."""
from __future__ import annotations

import random
import time

from .memory import Memory, memory
from .rawtree import db, now_ms, sql_str
from .scenarios import ScenarioBook
from .warehouse import Warehouse, warehouse

DAY_MS = 86_400_000


class DockReplay:
    def __init__(self, book: ScenarioBook | None = None, store: Warehouse = warehouse, mem: Memory = memory):
        self.book = book or ScenarioBook(store)
        self.store, self.memory = store, mem

    @staticmethod
    def new_run_id(tag: str = "demo") -> str:
        return f"{tag}-{time.strftime('%m%d-%H%M%S')}"

    def seeded(self, run_id: str) -> bool:
        return bool(db.one(f"SELECT count() AS n FROM {{t:orders}} WHERE run_id = {sql_str(run_id)}")["n"])

    def seed(self, run_id: str, which: str = "demo") -> list[dict]:
        scenarios = self.book.returns(which)
        products = self.store.products([s["sku"] for s in scenarios])
        now = now_ms()
        orders, truth = [], []
        for s in scenarios:
            rng = random.Random(s["key"])
            orders.append({"run_id": run_id, "order_id": f"ORD-{s['key']}", "sku": s["sku"],
                           "customer_id": s["customer_id"], "purchased_at_ms": now - s["days_since_purchase"] * DAY_MS,
                           "price_paid": round(float(products[s["sku"]]["list_price"]) * (1 - rng.uniform(0, 0.08)), 2)})
            truth.append(self.truth_row(run_id, s, now))
        self.store.add_orders(orders)
        db.insert("eval_gt", truth)
        return scenarios

    @staticmethod
    def truth_row(run_id: str, s: dict, ts: int) -> dict:
        return {"run_id": run_id, "return_id": f"RMA-{s['key']}", "key": s["key"], "set": s["set"],
                "seeded_at_ms": ts, **{f"gt_{k}": v for k, v in s["gt"].items()}}

    def relabel(self, run_id: str) -> int:
        """Append corrected ground truth for a run (the evaluator uses the newest row per return)."""
        return db.insert("eval_gt", [self.truth_row(run_id, s, now_ms()) for s in self.book.returns("all")])

    def arrive(self, run_id: str, s: dict) -> str:
        rid = f"RMA-{s['key']}"
        self.store.add_returns([{"run_id": run_id, "return_id": rid, "order_id": f"ORD-{s['key']}",
                                 "sku": s["sku"], "customer_id": s["customer_id"], "reason_text": s["reason_text"],
                                 "reason_category": s["reason_category"], "photos": self.book.photo_names(s["key"]),
                                 "received_at_ms": now_ms(), "scenario_key": s["key"]}])
        return rid

    def human_decided(self, run_id: str, key: str) -> bool:
        return bool(db.one(f"SELECT count() AS n FROM {{t:mem_decisions}} WHERE run_id = {sql_str(run_id)} "
                           f"AND case_id = {sql_str('RMA-' + key)} AND decided_by = 'human'")["n"])

    def play(self, run_id: str, which: str = "demo", gap_s: float = 10.0, stop=lambda: False) -> None:
        """Arrivals with a gap; a scenario with `wait_for` arrives only after that case's human decision.
        Orders for the whole set are seeded once per run, so stages can be played one after another."""
        full = "eval" if which == "eval" else "all" if which == "all" else "demo"
        if not self.seeded(run_id):
            self.seed(run_id, full)
        for s in self.book.returns(which):
            while s.get("wait_for") and not self.human_decided(run_id, s["wait_for"]) and not stop():
                time.sleep(1.0)
            if stop():
                return
            self.arrive(run_id, s)
            time.sleep(gap_s)
