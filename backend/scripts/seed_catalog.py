"""Seed RawTree reference tables: cleaned catalog (reclaim_products), vendors, cost model.

Usage: uv run scripts/seed_catalog.py [--force]
Append-only store, so we skip tables that already have rows unless --force.
"""
import json
import sys

import duckdb

from _path import *  # noqa: F401,F403
from reclaim.catalog import HF_PARQUET, SOURCE_FILES, clean_row
from reclaim.config import settings
from reclaim.rawtree import db, now_ms
from reclaim.reference import COST_MODEL, VENDOR_TERMS

FORCE = "--force" in sys.argv
RAW = settings.data_dir / "catalog_raw.parquet"


def has_rows(table: str) -> bool:
    try:
        return bool(db.one(f"SELECT count() AS n FROM {{t:{table}}}")["n"])
    except RuntimeError:  # table does not exist yet
        return False


def load_raw() -> list[dict]:
    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false")
    if not RAW.exists():
        files = ", ".join(f"'{f}'" for f in SOURCE_FILES)
        con.execute(f"COPY (SELECT * EXCLUDE (embeddings, __index_level_0__) FROM read_parquet({HF_PARQUET}) "
                    f"WHERE filename IN ({files})) TO '{RAW}' (FORMAT parquet)")
    cur = con.execute(f"SELECT * FROM '{RAW}' WHERE price IS NOT NULL AND image IS NOT NULL")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def seed(table: str, rows: list[dict]) -> None:
    if has_rows(table) and not FORCE:
        print(f"{table}: already seeded, skipping (use --force)")
        return
    print(f"{table}: inserted {db.insert(table, rows)}")


if __name__ == "__main__":
    ts = now_ms()
    products = [clean_row(r) | {"seeded_at_ms": ts} for r in load_raw()]
    seed("products", products)
    seed("vendors", [{"brand": b, "rtv_allowed": True, "credit_pct": c, "window_days": w,
                      "synthetic": True, "seeded_at_ms": ts} for b, (c, w) in VENDOR_TERMS.items()])
    seed("cost_model", [{"category": c, **{k: v for k, v in m.items() if k != "repair"},
                         "repair_json": json.dumps(m["repair"]), "synthetic": True, "seeded_at_ms": ts}
                        for c, m in COST_MODEL.items()])
    print(db.query("SELECT category, count() AS n, round(avg(list_price), 2) AS avg_price "
                   "FROM {t:products} GROUP BY category ORDER BY n DESC"))
