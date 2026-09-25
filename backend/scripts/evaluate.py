"""Score a finished run against ground truth: uv run scripts/evaluate.py <run_id> [--relabel]"""
import sys

from _path import *  # noqa: F401,F403
from reclaim.evaluation import Evaluator
from reclaim.replay import DockReplay
from reclaim.schema import ensure_schema

run_id = sys.argv[1]
if "--relabel" in sys.argv:
    ensure_schema()
    print("relabelled", DockReplay().relabel(run_id), "returns")
    import time
    time.sleep(2)
Evaluator().report(run_id, print_table=True)
