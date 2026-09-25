"""Smoke test: insert -> query round trip, ingest delay, auto-schema types."""
import json
import time
import uuid

from _path import *  # noqa: F401,F403
from reclaim.rawtree import db, now_ms

marker = uuid.uuid4().hex[:8]
row = {"marker": marker, "ts_ms": now_ms(), "iso": "2026-09-25T20:15:00Z", "tags": ["a", "b"],
       "nested": {"k": 1, "s": "x"}, "payload": json.dumps({"k": 1}), "price": 12.5, "flag": True}
t0 = time.time()
print("inserted", db.insert("smoke", row))
while True:
    rows = db.query(f"SELECT * FROM {{t:smoke}} WHERE marker = '{marker}'")
    if rows:
        break
    time.sleep(0.2)
print(f"visible after {time.time() - t0:.2f}s:", rows[0])
print(db.query("SELECT name, type FROM system.columns WHERE table = '{t:smoke}'".replace("{t:smoke}", db.t("smoke"))))
