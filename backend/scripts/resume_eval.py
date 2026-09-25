"""Resume a dataset evaluation run: finish in-flight cases from their checkpoints, then the rest.
Usage: uv run scripts/resume_eval.py <run_id> [--workers 1]"""
import sys
import time

from _path import *  # noqa: F401,F403
from reclaim.memory import memory
from reclaim.runtime import Runner, Watcher
from eval_dataset import simulated_human  # same simulated human as the original run

run_id = sys.argv[1]
workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 1
runner = Runner(on_interrupt=simulated_human, workers=workers).start()
heads = memory.case_heads(run_id)
inflight = [cid for cid, h in heads.items() if h["last_type"] not in ("case.closed", "case.failed")]
for cid in inflight:
    runner.continue_case(run_id, cid)  # LangGraph checkpoint: pick up exactly where the killed process stopped
watcher = Watcher(runner).start()
watcher.watch(run_id)  # queues every return that was never opened
print(f"resumed {run_id}: {len(inflight)} in-flight from checkpoints, workers={workers}", flush=True)
while True:
    time.sleep(30)
    print(time.strftime("%H:%M:%S"), "queued", runner.jobs.qsize(), flush=True)
