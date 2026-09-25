"""Smoke test: 2-image JSON-schema call to the local Liquid VLM; measures latency."""
from typing import Literal

from pydantic import BaseModel

from _path import *  # noqa: F401,F403
from reclaim.config import settings
from reclaim.llm import llm


class Verdict(BaseModel):
    image1_object: str
    image2_object: str
    same_product: Literal["yes", "no", "uncertain"]
    confidence: float


imgs = [settings.images_dir / "smoke_iphone.jpg", settings.images_dir / "smoke_apple.jpg"]
for i in range(2):
    v, log = llm.structured(Verdict, "You are a warehouse returns inspector. Answer in JSON.",
                            "Image 1 is the catalog photo. Image 2 is what arrived at the dock. "
                            "Name each object and say if they are the same product.", imgs, node="smoke")
    print(f"run {i}: {log.latency_ms} ms, tokens {log.prompt_tokens}/{log.completion_tokens}: {v}")
