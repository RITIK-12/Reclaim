"""Resume a dataset evaluation run: finish in-flight cases from their checkpoints, run the rest, write the report.
Usage: uv run scripts/resume_eval.py <run_id> [--workers 1]"""
import statistics
import sys
import time

from _path import *  # noqa: F401,F403
from reclaim.memory import memory
from reclaim.runtime import Runner, Watcher
from reclaim.warehouse import warehouse
from eval_dataset import simulated_human, write_report  # same simulated human as the original run

DONE = ("case.closed", "case.failed")

run_id = sys.argv[1]
workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 1
total = len(warehouse.returns(run_id))
runner = Runner(on_interrupt=simulated_human, workers=workers).start()
inflight = [cid for cid, h in memory.case_heads(run_id).items() if h["last_type"] not in DONE]
for cid in inflight:
    runner.continue_case(run_id, cid)  # LangGraph checkpoint: pick up exactly where the killed process stopped
watcher = Watcher(runner).start()
watcher.watch(run_id)  # queues every return that was never opened
print(f"resumed {run_id}: {total} returns, {len(inflight)} in-flight from checkpoints, workers={workers}", flush=True)
while len(watcher.seen) < total:
    time.sleep(1)
while runner.jobs.unfinished_tasks:
    time.sleep(20)
    heads = memory.case_heads(run_id)
    print(time.strftime("%H:%M:%S"), f"closed {sum(h['last_type'] in DONE for h in heads.values())}/{total}",
          flush=True)
runner.wait_idle()
time.sleep(2)
heads = memory.case_heads(run_id)
median_s = statistics.median((h["last_ts"] - h["first_ts"]) / 1000 for h in heads.values())
print(write_report(run_id, total, workers, f"Median {median_s:.0f} s per case (run resumed after a stop)."))
