"""Run the agent end to end on the 100-return FLUX dataset and write docs/EVALUATION.md.

Usage: uv run scripts/eval_dataset.py [--workers 3] [--split test] [--limit N]
Escalations are answered by a simulated human (never recorded as precedent, so each case stands alone).
"""
import sys
import time

from _path import *  # noqa: F401,F403
from reclaim.config import ROOT, settings
from reclaim.dataset import arrive, prepare_run_images, read_csv, seed_run
from reclaim.evaluation import Evaluator, markdown_report
from reclaim.runtime import Runner, Watcher


def arg(name: str, default: str | None = None) -> str | None:
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def simulated_human(run_id: str, case_id: str, packet: dict) -> dict:
    if packet.get("fraud_suspected"):
        return {"action": "LIQUIDATE", "fraud_flag": True, "note": "Wrong item returned.", "by": "simulated"}
    return {"action": packet.get("suggested_action") or "LIQUIDATE", "fraud_flag": False,
            "note": "Accepted the agent's suggestion.", "by": "simulated"}


def write_report(run_id: str, n: int, workers: int, timing: str) -> str:
    """Score the run against ground truth, write docs/EVALUATION.md and store the metrics in RawTree."""
    notes = [f"* Dataset: `backend/dataset/returns_100.csv` ({n} returns, FLUX.2 [max] dock photos of real "
             "catalog products; 5 categories × 20, 4 per action per category).",
             f"* Model: Liquid LFM2.5-VL-3B F16, served locally from `models/` by llama.cpp at {settings.llm_url}, "
             f"{workers} case(s) at a time on an M1 Pro (16 GB). {timing}",
             "* Live web prices from Nimble; every step written to RawTree; escalations answered by a simulated "
             "human that never becomes precedent."]
    md = markdown_report(Evaluator(), run_id, "Reclaim · evaluation on the 100-return synthetic dataset", notes)
    (ROOT / "docs" / "EVALUATION.md").write_text(md)
    Evaluator().report(run_id)  # also stored in reclaim_eval_runs
    return md


if __name__ == "__main__":
    rows = read_csv()
    if arg("--split"):
        rows = [r for r in rows if r.split == arg("--split")]
    rows = rows[: int(arg("--limit", "1000"))]
    prepare_run_images(rows)
    run_id = f"ds-{time.strftime('%m%d-%H%M%S')}"
    runner = Runner(on_interrupt=simulated_human, workers=int(arg("--workers", "3"))).start()
    watcher = Watcher(runner).start()
    watcher.watch(run_id)
    seed_run(run_id, rows)
    time.sleep(1.5)
    t0 = time.time()
    for r in rows:
        arrive(run_id, r)
    print(f"run {run_id}: {len(rows)} returns arrived", flush=True)
    while len(watcher.seen) < len(rows):
        time.sleep(1)
    runner.wait_idle()
    wall = time.time() - t0
    time.sleep(2)
    print(write_report(run_id, len(rows), runner.workers, f"Wall clock {wall / 60:.1f} min."))
