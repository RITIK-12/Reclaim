"""Market Analyst: Nimble sub-agent. Recall cached prices, else search the live web, extract, validate."""
from __future__ import annotations

import re
import statistics
from concurrent.futures import ThreadPoolExecutor
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from ..nimble import Nimble, SearchResult, nimble
from .base import SubAgent

KINDS = ("new", "used", "refurb", "open_box")
RESALE_DOMAINS = ["ebay.com", "backmarket.com", "amazon.com", "bestbuy.com", "walmart.com", "swappa.com"]


class PriceSource(BaseModel):
    hit: int = Field(description="Number of the search result the price comes from")
    price: float
    kind: Literal[KINDS]  # type: ignore[valid-type]


class PriceExtraction(BaseModel):
    prices: list[PriceSource] = Field(max_length=12)


class MarketState(TypedDict, total=False):
    case: dict
    deep: bool
    searches: list[dict]
    result: dict


def short_title(product: dict, max_words: int = 6) -> str:
    """Brand + model-ish words: cut at the first separator, keep through the last word with a digit."""
    title = re.sub(r"[\(\[].*?[\)\]]", " ", product["title"])
    words = re.split(r"[,|–—]| - ", title)[0].split()[:max_words]
    digit = max((i for i, wd in enumerate(words) if any(c.isdigit() for c in wd)), default=-1)
    keep = words[:max(digit + 1, 3)] if digit >= 0 else words[:5]
    while keep and keep[-1].lower() in {"with", "for", "and", "the", "+", "-"}:
        keep.pop()
    return " ".join(keep)


class MarketAnalyst(SubAgent):
    name = "market"

    def __init__(self, *args, search: Nimble = nimble, **kw):
        self.nimble = search
        super().__init__(*args, **kw)

    def build(self) -> StateGraph:
        g = StateGraph(MarketState)
        g.add_node("recall", self.recall)
        g.add_node("search", self.search)
        g.add_node("extract", self.extract)
        g.add_edge(START, "recall")
        g.add_conditional_edges("recall", lambda s: END if s.get("result") else "search", {"search": "search", END: END})
        g.add_edge("search", "extract")
        g.add_edge("extract", END)
        return g

    def run(self, case: dict, deep: bool = False, **inputs) -> dict:
        return self.graph.invoke({"case": case, "deep": deep})["result"]

    # --- nodes ------------------------------------------------------------------------------------
    def recall(self, s: MarketState) -> dict:
        """Shared semantic memory: fresh price facts learned from an earlier case skip the web."""
        case = s["case"]
        if s.get("deep"):
            return {}
        facts = self.memory.facts(case["run_id"], case["product"]["sku"])
        if "new" not in facts:
            return {}
        prices = {k: facts[k]["value"] if k in facts else None for k in KINDS}
        result = self._summary(prices, [{"url": f["source_url"], "price": f["value"], "kind": k}
                                        for k, f in facts.items()], cache_hit=True)
        self.log(case, "market.cache_hit", f"Reused {len(facts)} price facts from memory "
                 f"(new ${prices['new']:.0f})", result)
        return {"result": result}

    def search(self, s: MarketState) -> dict:
        p = s["case"]["product"]
        name = short_title(p)
        if s.get("deep"):
            model = f" {p['model']}" if p.get("model") else ""
            queries = [(f"{p['brand']}{model} {name} price", None),
                       (f"{name} renewed refurbished price", ["backmarket.com", "ebay.com", "amazon.com"])]
        else:
            queries = [(f"{name} price", None), (f"{name} used refurbished open box price", RESALE_DOMAINS)]
        with ThreadPoolExecutor(2) as pool:
            results: list[SearchResult] = list(pool.map(lambda q: self.nimble.search(q[0], include_domains=q[1]),
                                                        queries))
        for r in results:
            self.log(s["case"], "market.search", f"Nimble: \"{r.query}\" → {len(r.hits)} results "
                     f"in {r.latency_ms} ms", {"query": r.query, "latency_ms": r.latency_ms,
                                               "urls": [h.url for h in r.hits]})
        return {"searches": [{"query": r.query, "fetched_at_ms": r.fetched_at_ms,
                              "hits": [h.__dict__ for h in r.hits]} for r in results]}

    def extract(self, s: MarketState) -> dict:
        case, p = s["case"], s["case"]["product"]
        hits = [(srch["query"], srch["fetched_at_ms"], h) for srch in s["searches"] for h in srch["hits"]]
        listing = "\n\n".join(f"[{i}] {h['title']} — {h['url']}\n{h['text'][:900]}"
                              for i, (_, _, h) in enumerate(hits))
        extraction = self.ask(
            case, PriceExtraction,
            "You extract product prices from web search results. Only use prices that appear in the text.",
            f"Product: \"{p['title'][:150]}\" (catalog price ${p['list_price']} in 2023).\n"
            "From the results below, list prices for THIS product only (not accessories, cases, other models, "
            "monthly payments or discount amounts). kind: new = new retail price, used = pre-owned, "
            "refurb = refurbished/renewed, open_box = open box.\n\n" + listing, node="extract")
        sources, evidence = self._validate(extraction.prices, hits, p["list_price"])
        prices = {k: (round(statistics.median([x["price"] for x in sources if x["kind"] == k]), 2)
                      if any(x["kind"] == k for x in sources) else None) for k in KINDS}
        for k in ("used", "refurb", "open_box"):  # a second-hand price above new is mislabelled
            if prices["new"] and prices[k] and prices[k] > 1.05 * prices["new"]:
                prices[k] = None
                sources = [x for x in sources if x["kind"] != k]
        result = self._summary(prices, sources, cache_hit=False)
        self.memory.add_evidence(case["run_id"], case["case_id"], p["sku"], evidence)
        self.memory.remember_facts(case["run_id"], case["case_id"], p["sku"],
                                   {k: (prices[k], next((x["url"] for x in sources if x["kind"] == k), ""))
                                    for k in KINDS})
        found = ", ".join(f"{k} ${v:.0f}" for k, v in prices.items() if v) or "no usable prices"
        self.log(case, "market.completed", f"{len(sources)} validated prices: {found}", result)
        return {"result": result}

    # --- helpers ----------------------------------------------------------------------------------
    @staticmethod
    def _validate(prices: list[PriceSource], hits: list, list_price: float) -> tuple[list[dict], list[dict]]:
        """Keep a price only if it literally appears in the retrieved text and is plausible for the product.
        Small models mix up result numbers, so the price is credited to the result that actually contains it."""
        sources, evidence, seen = [], [], set()
        for x in prices:
            owners = [i for i, (_, _, h) in enumerate(hits) if any(abs(x.price - v) < 0.01 for v in h["prices"])]
            idx = x.hit if x.hit in owners else (owners[0] if owners else x.hit)
            if not 0 <= idx < len(hits):
                continue
            query, fetched_at, h = hits[idx]
            plausible = 0.05 * list_price <= x.price <= 3 * list_price
            ok = bool(owners) and plausible and (x.kind, x.price) not in seen
            evidence.append({"tool": "nimble.search", "query": query, "url": h["url"], "title": h["title"][:120],
                             "price": x.price, "kind": x.kind, "fetched_at_ms": fetched_at, "accepted": ok,
                             "rejected_because": "" if ok else ("not in any source text" if not owners else
                                                                "implausible vs catalog price" if not plausible
                                                                else "duplicate")})
            if ok:
                seen.add((x.kind, x.price))
                sources.append({"url": h["url"], "price": x.price, "kind": x.kind})
        return sources, evidence

    @staticmethod
    def _summary(prices: dict, sources: list[dict], cache_hit: bool) -> dict:
        kinds = [k for k in KINDS if prices.get(k)]
        return {**prices, "sources": sources[:12], "kinds_found": kinds, "cache_hit": cache_hit,
                "weak": not prices.get("new") or len(kinds) < 2}
