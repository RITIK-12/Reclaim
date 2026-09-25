"""Runtime: one worker thread runs Supervisor graphs (a single local model serialises work anyway);
a watcher polls RawTree and starts a case for every new return, with no human prompt."""
from __future__ import annotations

import queue
import sqlite3
import threading
import time
import traceback
from typing import Callable

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from .agents.supervisor import Supervisor
from .config import settings
from .memory import Memory, memory
from .rawtree import db
from .schema import ensure_schema
from .warehouse import Warehouse, warehouse

HumanPolicy = Callable[[str, str, dict], dict | None]


class Runner:
    def __init__(self, on_interrupt: HumanPolicy | None = None):
        ensure_schema()
        conn = sqlite3.connect(str(settings.checkpoint_db), check_same_thread=False)
        self.supervisor = Supervisor(checkpointer=SqliteSaver(conn))
        self.on_interrupt = on_interrupt
        self.jobs: queue.Queue = queue.Queue()
        self.current: str | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> "Runner":
        if not self._thread:
            self._thread = threading.Thread(target=self._loop, daemon=True, name="case-runner")
            self._thread.start()
        return self

    def open_case(self, run_id: str, case_id: str) -> None:
        self.jobs.put(("open", run_id, case_id, None))

    def resume(self, run_id: str, case_id: str, decision: dict) -> None:
        self.jobs.put(("resume", run_id, case_id, decision))

    def continue_case(self, run_id: str, case_id: str) -> None:
        """Pick a case back up from its last checkpoint (after a crash or restart)."""
        self.jobs.put(("continue", run_id, case_id, None))

    def wait_idle(self) -> None:
        self.jobs.join()
        db.flush()

    def _loop(self) -> None:
        while True:
            kind, run_id, case_id, payload = self.jobs.get()
            self.current = case_id
            cfg = {"configurable": {"thread_id": f"{run_id}:{case_id}"}, "recursion_limit": 80}
            try:
                inp = {"open": {"run_id": run_id, "case_id": case_id}, "resume": Command(resume=payload),
                       "continue": None}[kind]
                out = self.supervisor.graph.invoke(inp, cfg)
                if out.get("__interrupt__") and self.on_interrupt:
                    decision = self.on_interrupt(run_id, case_id, out["__interrupt__"][0].value)
                    if decision:
                        self.supervisor.graph.invoke(Command(resume=decision), cfg)
            except Exception:  # noqa: BLE001
                print(f"[runner] {case_id} crashed:\n{traceback.format_exc()}", flush=True)
            finally:
                self.current = None
                self.jobs.task_done()


class Watcher:
    """Proactive trigger: every new row in reclaim_returns for the active run starts a case."""

    def __init__(self, runner: Runner, store: Warehouse = warehouse, mem: Memory = memory,
                 interval_s: float = settings.watcher_interval_s):
        self.runner, self.store, self.memory, self.interval = runner, store, mem, interval_s
        self.run_id: str | None = None
        self.seen: set[str] = set()
        self._thread: threading.Thread | None = None

    def watch(self, run_id: str) -> None:
        self.run_id = run_id
        self.seen = set(self.memory.case_heads(run_id))  # already opened (e.g. before a restart)

    def start(self) -> "Watcher":
        if not self._thread:
            self._thread = threading.Thread(target=self._loop, daemon=True, name="dock-watcher")
            self._thread.start()
        return self

    def poll_once(self) -> list[str]:
        if not self.run_id:
            return []
        new = [r["return_id"] for r in self.store.returns(self.run_id) if r["return_id"] not in self.seen]
        for rid in new:
            self.seen.add(rid)
            self.runner.open_case(self.run_id, rid)
        return new

    def _loop(self) -> None:
        while True:
            try:
                self.poll_once()
            except Exception as e:  # noqa: BLE001
                print(f"[watcher] poll failed: {e}", flush=True)
            time.sleep(self.interval)
