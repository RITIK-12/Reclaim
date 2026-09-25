"""Run only the Inspector on chosen scenarios (fast iteration on the VLM prompts).
Usage: uv run scripts/probe_inspector.py D1 D5 E03"""
import sys
import time

from _path import *  # noqa: F401,F403
from reclaim.agents.inspector import Inspector
from reclaim.scenarios import ScenarioBook
from reclaim.warehouse import warehouse

book = ScenarioBook()
wanted = sys.argv[1:] or ["D1", "D5", "E03", "E04", "E06", "D7"]
inspector = Inspector()
run_id = f"probe-{time.strftime('%H%M%S')}"
for s in [r for r in book.returns("all") if r["key"] in wanted]:
    p = warehouse.product(s["sku"])
    case = {"run_id": run_id, "case_id": f"RMA-{s['key']}", "unit_id": "U-probe",
            "return": {"reason_text": s["reason_text"], "reason_category": s["reason_category"],
                       "photos": book.photos_for(s), "sku": s["sku"]},
            "product": {k: p.get(k) for k in ("sku", "title", "brand", "category", "list_price")}}
    t0 = time.time()
    res = inspector.run(case)
    ok = "✓" if res["identity"] == s["gt"]["identity"] else "✗"
    print(f"{s['key']:4} {ok} gt={s['gt']['identity']:9} got={res['identity']:9} conf={res['confidence']} "
          f"grade={res['grade']}(gt {s['gt']['grade']}) saw='{res['observed']}' [{res['observed_category']}] "
          f"text='{res['visible_text']}' guard={res['guard']} {time.time() - t0:.1f}s")
