"""Headless end-to-end run: new run_id -> dock replay -> watcher picks up returns -> supervisor graphs.

Escalations are answered by a scripted stand-in for the human (only in this script).
Usage: uv run scripts/run_headless.py [demo|eval|all] [--only D1,D5]
"""
import sys
import time

from _path import *  # noqa: F401,F403
from reclaim.evaluation import Evaluator
from reclaim.replay import DockReplay
from reclaim.runtime import Runner, Watcher

SCRIPTED_HUMAN = {
    "D5": {"action": "LIQUIDATE", "fraud_flag": True, "note": "An apple, not an iPhone. Flag the customer."},
    "D6": {"action": "RETURN_TO_VENDOR", "fraud_flag": False,
           "note": "Bench test confirms a battery fault; vendor credit beats a battery swap."},
}


def scripted_human(run_id: str, case_id: str, packet: dict) -> dict:
    key = case_id.removeprefix("RMA-")
    if key in SCRIPTED_HUMAN:
        return SCRIPTED_HUMAN[key] | {"by": "scripted"}
    if packet.get("fraud_suspected"):
        return {"action": "LIQUIDATE", "fraud_flag": True, "note": "Wrong item returned.", "by": "scripted"}
    return {"action": packet.get("suggested_action") or "LIQUIDATE", "fraud_flag": False,
            "note": "Accepted the agent's suggestion.", "by": "scripted"}


if __name__ == "__main__":
    which = next((a for a in sys.argv[1:] if not a.startswith("--") and "," not in a and a in
                  ("demo", "eval", "all")), "demo")
    only = next((sys.argv[i + 1].split(",") for i, a in enumerate(sys.argv) if a == "--only"), None)
    replay = DockReplay()
    run_id = replay.new_run_id(f"hl-{which}")
    runner = Runner(on_interrupt=scripted_human).start()
    watcher = Watcher(runner).start()
    watcher.watch(run_id)
    scenarios = [s for s in replay.seed(run_id, which) if not only or s["key"] in only]
    print(f"run {run_id}: {len(scenarios)} returns")
    t0 = time.time()
    for s in scenarios:
        replay.arrive(run_id, s)
    while len(watcher.seen) < len(scenarios):
        time.sleep(0.5)
    runner.wait_idle()
    print(f"done in {time.time() - t0:.0f}s")
    Evaluator().report(run_id, print_table=True)
