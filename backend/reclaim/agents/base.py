"""Base class for sub-agents: each one is a compiled LangGraph subgraph with shared logging helpers."""
from __future__ import annotations

from pathlib import Path
from typing import TypeVar

from langgraph.graph import StateGraph
from pydantic import BaseModel

from ..config import settings
from ..llm import LiquidLLM, llm
from ..memory import Memory, memory

T = TypeVar("T", bound=BaseModel)


class SubAgent:
    name = "agent"

    def __init__(self, mem: Memory = memory, model: LiquidLLM = llm):
        self.memory, self.llm = mem, model
        self.graph = self.build().compile()

    def build(self) -> StateGraph:
        raise NotImplementedError

    def run(self, case: dict, **inputs) -> dict:
        """Invoke the subgraph for one case; every subgraph writes its output to `result`."""
        return self.graph.invoke({"case": case, **inputs})["result"]

    # --- helpers shared by all sub-agents ----------------------------------------------------------
    def log(self, case: dict, type_: str, summary: str, payload: dict | None = None) -> None:
        self.memory.log(case["run_id"], case["case_id"], self.name, type_, summary, payload)

    def ask(self, case: dict, schema: type[T], system: str, text: str, images: list[Path] | None = None,
            node: str = "", brief_tokens: int = 0) -> T:
        out, call = self.llm.structured(schema, system, text, images, node=f"{self.name}.{node}")
        self.memory.log_llm(case["run_id"], case["case_id"], self.name, call, brief_tokens)
        return out

    @staticmethod
    def image(name: str) -> Path:
        return settings.images_dir / name
