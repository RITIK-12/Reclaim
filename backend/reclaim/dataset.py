"""Synthetic returns dataset: 100 real catalog products (5 categories x 20), each with a return reason,
a FLUX.2 [max] edit prompt that turns the catalog photo into the photo of the returned unit, and the
labels the agent should produce. Balanced: every category has 4 returns per final action."""
from __future__ import annotations

import csv
import random
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .config import ROOT
from .decision import classify_defect
from .rawtree import RawTree, db

CATEGORIES = ("phone", "laptop", "headphones", "earbuds", "smartwatch")
ACTIONS = ("RESTOCK", "REFURBISH", "RETURN_TO_VENDOR", "LIQUIDATE", "ESCALATE")
CSV_PATH = ROOT / "backend" / "dataset" / "returns_100.csv"
IMAGES_DIR = ROOT / "data" / "dataset"
APPLE_SKU = "B0BZ9N1QQC"  # Apple iPhone 14 (renewed): the one surprise return
JUNK = re.compile(r"\b(sleep|headband|kids?|replacement|compatible|case for|band for|straps?|chargers?|cables?|"
                  r"protectors?|cleaner|cleaning|kit|tips|covers?|adapters?|holders?|stand|pen|dust|skins?|beanie|hat|glasses|earmuffs|mask)\b", re.I)

NOUN = {"phone": "smartphone", "laptop": "laptop", "headphones": "pair of headphones",
        "earbuds": "pair of wireless earbuds with its charging case", "smartwatch": "smartwatch"}
SURFACES = ["a grey steel inspection table", "a scuffed stainless-steel workbench", "a flattened brown cardboard box",
            "a white plastic returns tote", "an anti-static blue mat on a workbench"]

# What the returned unit looks like, per scenario (appended to the base prompt).
LOOKS = {
    "intact": "The {noun} itself is clean and undamaged.",
    "boxed": "It sits next to its crushed, torn retail box; the {noun} itself is clean and undamaged.",
    "screen_crack": {
        "phone": "The front glass has a large spiderweb crack spreading from one corner; the phone is otherwise intact.",
        "laptop": "The laptop is open and its display has a spiderweb crack across one corner; the body is intact.",
        "smartwatch": "The watch face glass is cracked across the display; the case and strap are intact.",
    },
    "cosmetic": {
        "headphones": "One ear cushion is torn open exposing the foam and the headband padding is scuffed.",
        "earbuds": "The charging case lid is cracked and deeply scratched; the earbuds themselves look fine.",
    },
    "wrecked": {
        "phone": "The phone is destroyed: shattered glass front and back, a bent frame and a chunk missing from a corner.",
        "laptop": "The laptop is wrecked: shattered screen, a snapped hinge and a dented, cracked bottom case.",
        "headphones": "The headband is snapped in two and one ear cup hangs loose by its wire.",
        "earbuds": "One earbud is cracked open showing its insides and the charging case is filthy and chipped.",
        "smartwatch": "The screen is shattered, the strap is torn and the case is gouged.",
    },
    "swap": ("Replace the {noun} with a cheap unbranded knock-off {noun} of a clearly different design and color, "
             "so it is obviously not the product in the reference image."),
    "apple": "Replace the phone with a single shiny red apple lying where the phone would be. No phone in the photo.",
}

REASONS = {
    ("RESTOCK", "packaging_damage"): ["The box arrived crushed but the item inside is fine.",
                                      "Outer packaging was torn in shipping, never used.",
                                      "Box was dented on arrival, product untouched."],
    ("RESTOCK", "cosmetic"): ["Changed my mind, opened but never used.", "Ordered the wrong color, it's like new.",
                              "Didn't need it after all, still in perfect shape."],
    ("REFURBISH", "physical_damage"): {
        "phone": ["Dropped it and the screen cracked, still works fine.", "Screen cracked after a fall but it turns on."],
        "laptop": ["The display cracked in my backpack, laptop still boots.", "Screen corner cracked after a small drop."],
        "smartwatch": ["Knocked it on a door frame and the glass cracked.", "Screen cracked, watch still works."],
        "headphones": ["The ear cushion ripped and the headband is scuffed.", "Cushion tore after a week of use."],
        "earbuds": ["The charging case lid cracked when I dropped it.", "Case is cracked, buds still work."],
    },
    ("RETURN_TO_VENDOR", "functional"): {
        "phone": ["Stopped charging after a few days.", "Speaker crackles and then cuts out.",
                  "Won't connect to any mobile network."],
        "laptop": ["Keyboard stopped responding after a week.", "Trackpad doesn't work at all.",
                   "Won't charge anymore."],
        "headphones": ["Left side has no sound.", "Bluetooth keeps disconnecting every few minutes."],
        "earbuds": ["Right earbud won't charge.", "One earbud has no sound."],
        "smartwatch": ["Heart rate sensor doesn't read anything.", "Won't hold a charge for more than an hour."],
    },
    ("LIQUIDATE", "physical_damage"): ["It was run over, completely smashed.", "Dropped from a height, it's destroyed.",
                                       "Fell down the stairs and broke apart.", "Crushed in a car door, totally broken."],
    ("ESCALATE", "functional"): ["Won't turn on at all.", "Battery dies within an hour.", "Randomly shuts down.",
                                 "Screen goes black after a few minutes."],
    ("SWAP", "functional"): ["Doesn't work properly, want a refund.", "Defective, stopped working.",
                             "Not working as described."],
}


@dataclass
class Row:
    id: str
    split: str
    demo: bool
    category: str
    sku: str
    title: str
    brand: str
    list_price: float
    condition_at_sale: str
    catalog_image_url: str
    scenario: str
    reason_category: str
    reason_text: str
    days_since_purchase: int
    edit_prompt: str
    expected_identity: str
    expected_grade: str
    expected_defect: str
    expected_action: str
    expected_rule: str
    image_file: str = ""
    bfl_request_id: str = ""


class DatasetBuilder:
    def __init__(self, store: RawTree = db, seed: int = 7):
        self.db, self.rng = store, random.Random(seed)

    def candidates(self) -> dict[str, list[dict]]:
        cats = ", ".join(f"'{c}'" for c in CATEGORIES)
        rows = self.db.query(
            f"SELECT toString(sku) AS sku, toString(title) AS title, toString(brand) AS brand, "
            f"toString(category) AS category, toFloat64(list_price) AS price, toInt64(rating_count) AS rc, "
            f"toString(condition_at_sale) AS cond, toString(image_url) AS image FROM {{t:products}} "
            f"WHERE toString(category) IN ({cats}) AND toInt64(rating_count) >= 5 AND toString(brand) != 'Generic' "
            f"ORDER BY rc DESC LIMIT 1 BY sku")
        out: dict[str, list[dict]] = {c: [] for c in CATEGORIES}
        for r in rows:
            if not JUNK.search(r["title"]) and r["price"] >= 10 and len(r["title"].split()) >= 4:
                out[r["category"]].append(r)
        return out

    def plan_category(self, cat: str, pool: list[dict]) -> list[tuple[dict, str, str]]:
        """Pick 20 products for one category: 4 per action, chosen by price band so the policy's answer is clear."""
        used: set[str] = set()

        def take(n: int, pred) -> list[dict]:
            got = [p for p in pool if p["sku"] not in used and pred(p)][:n]
            used.update(p["sku"] for p in got)
            if len(got) < n:
                raise ValueError(f"{cat}: not enough products for a slot ({len(got)}/{n})")
            return got

        plan: list[tuple[dict, str, str]] = []
        high = [p for p in pool if p["price"] >= 300]
        esc_budget = 4
        if cat == "phone":
            apple = next(p for p in pool if p["sku"] == APPLE_SKU)
            used.add(apple["sku"])
            plan.append((apple, "ESCALATE", "apple"))
            esc_budget -= 1
        n_r3a = min(len([p for p in high if p["sku"] not in used]), 2 if cat != "laptop" else 3, esc_budget)
        plan += [(p, "ESCALATE", "unverifiable_claim") for p in take(n_r3a, lambda p: p["price"] >= 300)]
        plan += [(p, "ESCALATE", "swap") for p in take(esc_budget - n_r3a, lambda p: 60 <= p["price"])]
        refurb_floor = {"phone": 200, "laptop": 450, "headphones": 40, "earbuds": 60, "smartwatch": 90}[cat]
        refurb_look = "screen_crack" if cat in ("phone", "laptop", "smartwatch") else "cosmetic"
        plan += [(p, "REFURBISH", refurb_look) for p in take(4, lambda p: p["price"] >= refurb_floor)]
        cheap = sorted([p for p in pool if p["sku"] not in used], key=lambda p: p["price"])
        liquidate = [p for p in cheap if (p["price"] < 45 or cat in ("phone", "laptop"))][:4]
        used.update(p["sku"] for p in liquidate)
        plan += [(p, "LIQUIDATE", "wrecked") for p in liquidate]
        plan += [(p, "RETURN_TO_VENDOR", "intact") for p in
                 take(4, lambda p: p["price"] < 300 and p["cond"] == "new" and p["price"] >= 20)]
        restock = take(4, lambda p: p["price"] < 300) if len([p for p in pool if p["sku"] not in used
                                                               and p["price"] < 300]) >= 4 else take(4, lambda p: True)
        plan += [(p, "RESTOCK", "boxed" if i % 2 == 0 else "intact") for i, p in enumerate(restock)]
        return plan

    def make_row(self, idx: int, p: dict, action: str, look: str) -> Row:
        cat, noun = p["category"], NOUN[p["category"]]
        surface = self.rng.choice(SURFACES)
        if action == "RESTOCK":
            reason_cat = "packaging_damage" if look == "boxed" else "cosmetic"
            reason = self.rng.choice(REASONS[("RESTOCK", reason_cat)])
        elif action == "REFURBISH":
            reason_cat, reason = "physical_damage", self.rng.choice(REASONS[("REFURBISH", "physical_damage")][cat])
        elif action == "RETURN_TO_VENDOR":
            reason_cat, reason = "functional", self.rng.choice(REASONS[("RETURN_TO_VENDOR", "functional")][cat])
        elif action == "LIQUIDATE":
            reason_cat, reason = "physical_damage", self.rng.choice(REASONS[("LIQUIDATE", "physical_damage")])
        elif look == "apple":
            reason_cat, reason = "functional", "Phone won't turn on."
        elif look == "swap":
            reason_cat, reason = "functional", self.rng.choice(REASONS[("SWAP", "functional")])
        else:
            reason_cat, reason = "functional", self.rng.choice(REASONS[("ESCALATE", "functional")])

        detail = LOOKS["intact"] if look in ("intact", "unverifiable_claim") else LOOKS[look]
        if isinstance(detail, dict):
            detail = detail[cat]
        subject = {"swap": f"a cheap unbranded knock-off {noun} of a clearly different design and color (not the "
                           f"product in the reference image)",
                   "apple": "a single shiny red apple, where a returned phone should have been"}.get(
            look, f"the exact same {noun} from the reference image (same brand, model, shape and color)")
        detail = "" if look in ("swap", "apple") else " " + detail.format(noun=noun)
        prompt = (f"Photo taken at a warehouse returns dock: {subject} lying on {surface} under harsh fluorescent "
                  f"light, shot slightly from above with a smartphone camera, realistic, natural shadows, no text "
                  f"overlays.{detail}" + (" No phone anywhere in the photo." if look == "apple" else ""))
        mismatch = look in ("swap", "apple")
        grade = {"intact": "A", "boxed": "A", "unverifiable_claim": "A", "screen_crack": "C", "cosmetic": "C",
                 "wrecked": "D", "swap": "-", "apple": "-"}[look]
        seen = {"screen_crack": ["cracked screen"], "cosmetic": ["cracked case" if cat == "earbuds" else "torn cushion"],
                "wrecked": ["shattered", "broken"]}.get(look, [])
        rule = {"ESCALATE": "R1 identity_mismatch" if mismatch else "R3a unverifiable_high_value_claim"}.get(
            action, "max EV among allowed")
        return Row(
            id=f"DS{idx:03d}", split="train", demo=False, category=cat, sku=p["sku"], title=p["title"][:160],
            brand=p["brand"], list_price=round(p["price"], 2), condition_at_sale=p["cond"],
            catalog_image_url=p["image"], scenario=f"{action.lower()}/{look}", reason_category=reason_cat,
            reason_text=reason, days_since_purchase=self.rng.randint(4, 25) if action == "RETURN_TO_VENDOR"
            else self.rng.randint(3, 60), edit_prompt=prompt, expected_identity="mismatch" if mismatch else "match",
            expected_grade=grade, expected_defect="-" if mismatch else classify_defect(reason_cat, reason, seen, grade, cat),
            expected_action=action, expected_rule=rule)

    def build(self) -> list[Row]:
        pools = self.candidates()
        rows: list[Row] = []
        for cat in CATEGORIES:
            for p, action, look in self.plan_category(cat, pools[cat]):
                rows.append(self.make_row(len(rows) + 1, p, action, look))
        self._split(rows)
        return rows

    def _split(self, rows: list[Row]) -> None:
        """Stratified 90/10: two test items per action; one of them (a different category each) is the demo."""
        demo_category = {"RESTOCK": "smartwatch", "REFURBISH": "laptop", "RETURN_TO_VENDOR": "headphones",
                         "LIQUIDATE": "earbuds", "ESCALATE": "phone"}  # the apple; all five categories on stage
        for action in ACTIONS:
            group = [r for r in rows if r.expected_action == action]
            demo_cat = demo_category[action]
            demo = next((r for r in group if r.scenario == "escalate/apple"), None) if action == "ESCALATE" else None
            demo = demo or next(r for r in group if r.category == demo_cat)
            other = self.rng.choice([r for r in group if r is not demo and r.category != demo.category])
            for r in (demo, other):
                r.split = "test"
            demo.demo = True


def write_csv(rows: list[Row], path: Path = CSV_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[x.name for x in fields(Row)])
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))


def read_csv(path: Path = CSV_PATH) -> list[Row]:
    with path.open() as f:
        out = []
        for d in csv.DictReader(f):
            d["demo"] = d["demo"] == "True"
            d["list_price"] = float(d["list_price"])
            d["days_since_purchase"] = int(d["days_since_purchase"])
            out.append(Row(**d))
        return out


# --- vendors, generation and storage --------------------------------------------------------------------
def seed_vendor_terms(rows: list[Row], store: RawTree = db) -> int:
    """Synthetic RTV terms for dataset brands that have none yet (deterministic per brand)."""
    from .reference import VENDOR_TERMS
    from .rawtree import now_ms
    existing = {r["b"] for r in store.query("SELECT DISTINCT toString(brand) AS b FROM {t:vendors}")}
    new = sorted({r.brand.lower() for r in rows} - existing - set(VENDOR_TERMS))
    ts = now_ms()
    out = [{"brand": b, "rtv_allowed": True, "credit_pct": [0.5, 0.6, 0.7, 0.8][hash(b) % 4 if False else
                                                                               sum(map(ord, b)) % 4],
            "window_days": [30, 45, 60, 90][sum(map(ord, b)) % 4], "synthetic": True, "source": "dataset",
            "seeded_at_ms": ts} for b in new]
    if out:
        store.insert("vendors", out)
    return len(out)


def generate_images(rows: list[Row], workers: int = 8, out_dir: Path | None = None) -> list[str]:
    """FLUX.2 [max] edits in parallel; skips rows whose image already exists. Returns error messages."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from .config import settings
    from .flux import Flux
    out_dir = out_dir or settings.images_dir
    flux, errors = Flux(), []

    def one(r: Row) -> None:
        name = f"ds_{r.id}.jpg"
        if (out_dir / name).exists():
            r.image_file = r.image_file or name
            return
        req_id, data = flux.edit(r.edit_prompt, r.catalog_image_url, seed=int(r.id[2:]))
        (out_dir / name).write_bytes(data)
        r.image_file, r.bfl_request_id = name, req_id

    with ThreadPoolExecutor(workers) as pool:
        futures = {pool.submit(one, r): r for r in rows}
        for n, f in enumerate(as_completed(futures), 1):
            r = futures[f]
            try:
                f.result()
                print(f"[{n}/{len(rows)}] {r.id} ok", flush=True)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{r.id}: {e}")
                print(f"[{n}/{len(rows)}] {r.id} FAILED {e}", flush=True)
    return errors


def store_rows(rows: list[Row], store: RawTree = db, max_side: int = 768) -> None:
    """RawTree: reclaim_dataset (labels + metadata) and reclaim_dataset_images (base64 JPEG per row)."""
    import base64
    import io

    from PIL import Image

    from .config import settings
    from .rawtree import now_ms
    ts = now_ms()
    store.insert("dataset", [asdict(r) | {"model": "flux-2-max", "stored_at_ms": ts} for r in rows])
    images = []
    for r in rows:
        if not r.image_file:
            continue
        img = Image.open(settings.images_dir / r.image_file).convert("RGB")
        img.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=82)
        images.append({"id": r.id, "sku": r.sku, "image_file": r.image_file, "width": img.width, "height": img.height,
                       "image_b64": base64.b64encode(buf.getvalue()).decode(), "stored_at_ms": ts})
    for i in range(0, len(images), 20):
        store.insert("dataset_images", images[i:i + 20])
