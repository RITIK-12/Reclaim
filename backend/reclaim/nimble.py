"""Nimble web search client. Standard depth returns page text that contains live prices."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import httpx

from .config import settings

PRICE_RE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\d+(?:\.\d{2})?)")


def prices_in(text: str) -> list[float]:
    """All dollar amounts mentioned in a text."""
    return [float(m.replace(",", "")) for m in PRICE_RE.findall(text or "")]


@dataclass
class SearchHit:
    title: str
    url: str
    text: str  # description + content, trimmed
    prices: list[float] = field(default_factory=list)


@dataclass
class SearchResult:
    query: str
    hits: list[SearchHit]
    latency_ms: int
    fetched_at_ms: int


class Nimble:
    def __init__(self, url: str = settings.nimble_url, key: str = settings.nimble_key):
        self._http = httpx.Client(base_url=url, timeout=60,
                                  headers={"Authorization": f"Bearer {key}"})

    def search(self, query: str, *, depth: str = "standard", max_results: int = 6,
               include_domains: list[str] | None = None, text_chars: int = 1500) -> SearchResult:
        body: dict = {"query": query, "search_depth": depth, "max_results": max_results}
        if include_domains:
            body["include_domains"] = include_domains
        t0 = time.time()
        r = self._http.post("/v2/search", json=body)
        r.raise_for_status()
        hits = []
        for item in r.json().get("results", []):
            text = f"{item.get('description', '')}\n{item.get('content', '')}"[:text_chars]
            hits.append(SearchHit(title=item.get("title", ""), url=item.get("url", ""),
                                  text=text, prices=prices_in(text)))
        return SearchResult(query=query, hits=hits, latency_ms=int((time.time() - t0) * 1000),
                            fetched_at_ms=int(time.time() * 1000))


nimble = Nimble()
