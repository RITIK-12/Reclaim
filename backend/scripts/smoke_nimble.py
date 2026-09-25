"""Smoke test: Nimble standard search for new and secondary-market prices."""
from _path import *  # noqa: F401,F403
from reclaim.nimble import nimble

for q, domains in [("Apple AirPods Pro 2 price", None),
                   ("Apple AirPods Pro 2 used refurbished open box price",
                    ["ebay.com", "backmarket.com", "bestbuy.com", "amazon.com"])]:
    res = nimble.search(q, include_domains=domains)
    print(f"\n{q!r}: {len(res.hits)} hits in {res.latency_ms} ms")
    for h in res.hits:
        print(f"  {h.url[:70]:70} prices={h.prices[:6]}")
