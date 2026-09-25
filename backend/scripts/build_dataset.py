"""Synthetic returns dataset: shortlist 100 products -> reasons + FLUX.2 [max] prompts -> images -> CSV + RawTree.

Usage: uv run scripts/build_dataset.py [--rebuild]   (re-running only generates missing images)
"""
import json
import sys

from _path import *  # noqa: F401,F403
from reclaim.dataset import CSV_PATH, DatasetBuilder, generate_images, read_csv, seed_vendor_terms, store_rows, write_csv
from reclaim.rawtree import db, now_ms
from reclaim.reference import COST_MODEL

rows = DatasetBuilder().build() if "--rebuild" in sys.argv or not CSV_PATH.exists() else read_csv()
write_csv(rows)
print(f"{len(rows)} rows, vendor terms added: {seed_vendor_terms(rows)}")
m = COST_MODEL["earbuds"]
db.insert("cost_model", {"category": "earbuds", **{k: v for k, v in m.items() if k != "repair"},
                         "repair_json": json.dumps(m["repair"]), "synthetic": True, "seeded_at_ms": now_ms()})
errors = generate_images(rows, workers=8)
write_csv(rows)
store_rows(rows)
print(f"done: {sum(bool(r.image_file) for r in rows)} images, {len(errors)} errors")
for e in errors:
    print("  ", e)
