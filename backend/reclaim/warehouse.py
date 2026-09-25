"""Warehouse system of record in RawTree: catalog, vendors, cost model, orders, returns, inventory."""
from __future__ import annotations

import json
from functools import lru_cache

from .rawtree import RawTree, db, now_ms, sql_str


class Warehouse:
    def __init__(self, store: RawTree = db):
        self.db = store

    # --- reference data (seeded once, cached) -----------------------------------------------------
    def products(self, skus: list[str]) -> dict[str, dict]:
        if not skus:
            return {}
        ids = ", ".join(sql_str(s) for s in skus)
        rows = self.db.query(f"SELECT * FROM {{t:products}} WHERE toString(sku) IN ({ids}) "
                             f"ORDER BY toInt64(seeded_at_ms) DESC LIMIT 1 BY toString(sku)")
        return {r["sku"]: r for r in rows}

    def product(self, sku: str) -> dict | None:
        return self.products([sku]).get(sku)

    @lru_cache(maxsize=256)
    def vendor(self, brand: str) -> dict | None:
        return self.db.one(f"SELECT * FROM {{t:vendors}} WHERE brand = {sql_str(brand.lower())} "
                           f"ORDER BY toInt64(seeded_at_ms) DESC LIMIT 1")

    @lru_cache(maxsize=64)
    def cost_model(self, category: str) -> dict:
        row = self.db.one(f"SELECT * FROM {{t:cost_model}} WHERE category = {sql_str(category)} "
                          f"ORDER BY toInt64(seeded_at_ms) DESC LIMIT 1")
        if row is None:
            row = self.cost_model("other_accessory")
        return {**row, "repair": json.loads(row.get("repair_json") or "{}")}

    # --- orders and returns (per run) -----------------------------------------------------------
    def add_orders(self, rows: list[dict]) -> None:
        self.db.insert("orders", rows)

    def add_returns(self, rows: list[dict]) -> None:
        self.db.insert("returns", rows)

    def order(self, run_id: str, order_id: str) -> dict | None:
        return self.db.one(f"SELECT * FROM {{t:orders}} WHERE run_id = {sql_str(run_id)} "
                           f"AND order_id = {sql_str(order_id)} LIMIT 1")

    def return_(self, run_id: str, return_id: str) -> dict | None:
        return self.db.one(f"SELECT * FROM {{t:returns}} WHERE run_id = {sql_str(run_id)} "
                           f"AND return_id = {sql_str(return_id)} LIMIT 1")

    def returns(self, run_id: str) -> list[dict]:
        return self.db.query(f"SELECT * FROM {{t:returns}} WHERE run_id = {sql_str(run_id)} "
                             f"ORDER BY toInt64(received_at_ms)")

    # --- inventory (append-only unit movements) --------------------------------------------------
    def move_unit(self, run_id: str, unit_id: str, sku: str, case_id: str, location: str, state: str,
                  **extra) -> dict:
        row = {"run_id": run_id, "unit_id": unit_id, "sku": sku, "case_id": case_id, "location": location,
               "state": state, "ts_ms": now_ms(), **extra}
        self.db.insert("inventory", row)
        return row

    def unit_state(self, run_id: str, unit_id: str) -> dict | None:
        return self.db.one(f"SELECT argMax(toString(location), toInt64(ts_ms)) AS loc, argMax(toString(state), toInt64(ts_ms)) AS st "
                           f"FROM {{t:inventory}} WHERE run_id = {sql_str(run_id)} AND unit_id = {sql_str(unit_id)} "
                           f"HAVING count() > 0")


warehouse = Warehouse()
