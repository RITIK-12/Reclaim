"""Catalog cleaning: milistu/AMAZON-Products-2023 (Electronics + Cell Phones) -> reclaim_products rows."""
from __future__ import annotations

import ast
import re
from datetime import datetime

HF_PARQUET = [f"https://huggingface.co/api/datasets/milistu/AMAZON-Products-2023/parquet/default/train/{i}.parquet"
              for i in range(4)]
SOURCE_FILES = ("meta_Electronics", "meta_Cell_Phones_and_Accessories")

# Our taxonomy. Families group categories a VLM may confuse with each other (used by the identity guard).
DEVICE_CATEGORIES = {
    "phone": "handheld", "tablet": "handheld", "laptop": "computer", "computer": "computer",
    "headphones": "audio", "earbuds": "audio", "speaker": "audio", "smartwatch": "wearable",
    "camera": "camera", "display": "display",
}
ACCESSORY_CATEGORIES = {
    "cable_charger": "accessory", "case_protector": "accessory",
    "computer_accessory": "accessory", "other_accessory": "accessory",
}
FAMILY = {**DEVICE_CATEGORIES, **ACCESSORY_CATEGORIES}
CATEGORIES = list(FAMILY)
REPAIRABLE = {"phone", "tablet", "laptop", "computer", "headphones", "smartwatch", "camera", "display", "speaker"}

def _has(path: list[str], *keys: str) -> bool:
    return any(k in seg for seg in path for k in keys)


def _tail(path: list[str]) -> str:
    return " > ".join(path[2:])


# (category, test on the category path) in priority order; first match wins.
_PATH_RULES: list[tuple[str, callable]] = [
    ("case_protector", lambda p: _has(p, "Cases", "Screen Protectors", "Skins", "Covers", "Sleeves", "Holsters",
                                      "Maintenance, Upkeep")),
    ("cable_charger", lambda p: _has(p, "Cables", "Chargers", "Power Adapters", "Power Accessories", "Power Banks")),
    ("phone", lambda p: p[1:2] == ["Cell Phones"]),
    ("tablet", lambda p: p[-1:] == ["Tablets"]),
    ("laptop", lambda p: _has(p, "Laptops") and not _has(p, "Laptop Accessories")),
    ("computer", lambda p: _has(p, "Desktops", "Minis", "Towers", "All-in-Ones")),
    ("earbuds", lambda p: _has(p, "Earbud Headphones")),
    ("headphones", lambda p: _has(p, "Headphones & Earbuds")),
    ("smartwatch", lambda p: p[-1:] == ["Smartwatches"]),
    ("speaker", lambda p: _has(p, "Speakers", "Sound Bars") and "Accessories" not in _tail(p)),
    ("camera", lambda p: _has(p, "Cameras", "Camcorders") and "Accessories" not in _tail(p)),
    ("display", lambda p: _has(p, "Monitors", "Televisions") and "Accessories" not in _tail(p)
     and "Mounts" not in _tail(p)),
    ("computer_accessory", lambda p: _has(p, "Computers & Accessories")),
]


def categorize(path: list[str] | None) -> str:
    path = list(path or [])
    for name, test in _PATH_RULES:
        if test(path):
            return name
    return "other_accessory"


_WEIGHT_RE = re.compile(r"([\d.]+)\s*(pounds?|lbs?|ounces?|oz|kilograms?|kg|grams?|g)\b", re.I)
_TO_LB = {"p": 1.0, "l": 1.0, "o": 1 / 16, "k": 2.2046, "g": 0.0022046}


def parse_weight_lb(text: str | None) -> float | None:
    m = _WEIGHT_RE.search(text or "")
    if not m:
        return None
    unit = m.group(2).lower()
    factor = 2.2046 if unit.startswith("k") else _TO_LB[unit[0]]
    return round(float(m.group(1)) * factor, 3)


def parse_details(raw: str | None) -> dict:
    try:
        d = ast.literal_eval(raw or "{}")
        return d if isinstance(d, dict) else {}
    except (ValueError, SyntaxError):
        return {}


def _clip(text: str | None, n: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def clean_row(r: dict) -> dict:
    """One raw dataset row -> one reclaim_products row (see docs for the column decisions)."""
    details = parse_details(r.get("details"))
    store = (r.get("store") or "").strip()
    title = r.get("title") or ""
    brand = str(details.get("Brand") or details.get("Manufacturer") or "").strip()
    if not brand or brand.lower() in {"generic", "unbranded"}:
        brand = "" if store.lower() in {"generic", "amazon renewed"} else store
    if not brand and title.lower().startswith("apple "):
        brand = "Apple"
    renewed = store == "Amazon Renewed" or "renewed" in title.lower()
    category = categorize(r.get("categories"))
    first = r.get("date_first_available")
    return {
        "sku": r["parent_asin"],
        "title": _clip(title, 200),
        "brand": brand or "Generic",
        "seller": store or "Unknown",
        "model": _clip(str(details.get("Item model number") or details.get("Model Name") or ""), 60),
        "category": category,
        "family": FAMILY[category],
        "is_device": category in DEVICE_CATEGORIES,
        "repairable": category in REPAIRABLE,
        "category_path": " > ".join(r.get("categories") or []),
        "list_price": round(float(r["price"]), 2),
        "image_url": r["image"],
        "rating": r.get("average_rating"),
        "rating_count": int(r.get("rating_number") or 0),
        "weight_lb": parse_weight_lb(str(details.get("Item Weight") or "")),
        "condition_at_sale": "renewed" if renewed else "new",
        "first_available": first.strftime("%Y-%m-%d") if isinstance(first, datetime) else str(first or "")[:10],
        "features": [_clip(f, 150) for f in (r.get("features") or [])[:3]],
        "source": "milistu/AMAZON-Products-2023",
    }
