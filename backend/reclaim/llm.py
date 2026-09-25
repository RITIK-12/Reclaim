"""Liquid LFM2.5-VL via LM Studio (OpenAI-compatible). One model for vision and text."""
from __future__ import annotations

import base64
import io
import json
import time
from pathlib import Path
from typing import TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from PIL import Image
from pydantic import BaseModel, ValidationError

from .config import settings

T = TypeVar("T", bound=BaseModel)


def image_part(path: Path, max_side: int = settings.image_max_side) -> dict:
    """Resize (longest side = max_side) and encode as an OpenAI image_url content part."""
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}


class CallLog(BaseModel):
    """What we record per LLM call (goes to the llm_calls table)."""
    node: str
    latency_ms: int
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LiquidLLM:
    def __init__(self, model: str = settings.llm_model, base_url: str = settings.llm_url):
        self.chat = ChatOpenAI(model=model, base_url=base_url, api_key="lm-studio",
                               temperature=0.1, max_tokens=500, timeout=180)

    def structured(self, schema: type[T], system: str, text: str,
                   images: list[Path] | None = None, node: str = "llm") -> tuple[T, CallLog]:
        """JSON-schema constrained call, validated by Pydantic, one retry with the error."""
        content: list[dict] = [{"type": "text", "text": text}]
        content += [image_part(p) for p in images or []]
        messages = [SystemMessage(system), HumanMessage(content=content)]
        runnable = self.chat.with_structured_output(schema, method="json_schema", include_raw=True)
        last_err: Exception | None = None
        for _ in range(2):
            t0 = time.time()
            out = runnable.invoke(messages)
            raw = out["raw"]
            usage = getattr(raw, "usage_metadata", None) or {}
            log = CallLog(node=node, latency_ms=int((time.time() - t0) * 1000),
                          prompt_tokens=usage.get("input_tokens", 0),
                          completion_tokens=usage.get("output_tokens", 0))
            if out.get("parsed") is not None:
                return out["parsed"], log
            last_err = out.get("parsing_error")
            messages = messages + [raw, HumanMessage(f"Invalid JSON ({last_err}). Reply again with valid JSON only.")]
        raise ValueError(f"{node}: structured output failed: {last_err}")

    def text(self, system: str, text: str, node: str = "llm") -> tuple[str, CallLog]:
        t0 = time.time()
        raw = self.chat.invoke([SystemMessage(system), HumanMessage(text)])
        usage = raw.usage_metadata or {}
        return raw.content.strip(), CallLog(node=node, latency_ms=int((time.time() - t0) * 1000),
                                            prompt_tokens=usage.get("input_tokens", 0),
                                            completion_tokens=usage.get("output_tokens", 0))


llm = LiquidLLM()
