"""Lets scripts import the `reclaim` package when run as `uv run scripts/x.py`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
