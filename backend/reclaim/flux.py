"""Black Forest Labs FLUX.2 client: edit a catalog photo into the photo of a returned unit."""
from __future__ import annotations

import time

import httpx

from .config import settings

FAILED = {"Error", "Failed", "Content Moderated", "Request Moderated", "Task not found"}


class Flux:
    def __init__(self, model: str = "flux-2-max", key: str = settings.bfl_key, url: str = settings.bfl_url):
        self.model = model
        self._http = httpx.Client(base_url=url, timeout=90, headers={"x-key": key, "accept": "application/json"})

    def edit(self, prompt: str, image_url: str, seed: int, width: int = 1024, height: int = 768,
             timeout_s: float = 300) -> tuple[str, bytes]:
        """Submit an edit, poll until ready, download the result (signed URLs expire in 10 minutes)."""
        r = self._http.post(f"/v1/{self.model}", json={"prompt": prompt, "input_image": image_url, "seed": seed,
                                                        "width": width, "height": height, "output_format": "jpeg",
                                                        "safety_tolerance": 2})
        r.raise_for_status()
        job = r.json()
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            time.sleep(1.5)
            s = self._http.get(job["polling_url"]).json()
            if s.get("status") == "Ready":
                img = httpx.get(s["result"]["sample"], timeout=60)
                img.raise_for_status()
                return job["id"], img.content
            if s.get("status") in FAILED:
                raise RuntimeError(f"FLUX {job['id']}: {s.get('status')} {s.get('details') or ''}")
        raise TimeoutError(f"FLUX {job['id']} not ready after {timeout_s}s")
