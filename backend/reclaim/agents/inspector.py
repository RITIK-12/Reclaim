"""Inspector: Liquid VLM sub-agent.

A 3B VLM is much more reliable looking at one image at a time than comparing two, so identity is
checked in three steps:
  1. observe  - blind pass on the dock photo (the model is not told what was ordered): object,
                category, visible text, color, damage, condition grade
  2. profile  - the same description of the catalog photo (cached per SKU)
  3. verify   - text-only Liquid call comparing the two descriptions against the order
then code applies guard rules (non-electronic object, wrong product family, brand text on the item).
If identity is still uncertain and another photo exists, it re-inspects with the next photo.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from ..catalog import CATEGORIES, FAMILY
from ..decision import HIGH_VALUE, MIN_CONFIDENCE, classify_defect
from .base import SubAgent

GUESSES = tuple(CATEGORIES) + ("non_electronic",)
MAX_PHOTOS = 2
# Keyword sanity check for the blind category (small models sometimes pick the wrong enum value).
KEYWORDS = [("earbuds", r"earbud|earphone|in-ear"), ("headphones", r"headphone|headset"),
            ("phone", r"\bphone|smartphone|iphone"), ("tablet", r"tablet|ipad"), ("laptop", r"laptop|notebook|chromebook"),
            ("speaker", r"speaker|soundbar|boombox"), ("smartwatch", r"watch"), ("camera", r"camera|dash ?cam"),
            ("display", r"monitor|television|\btv\b"), ("cable_charger", r"cable|charger|adapter|cord"),
            ("case_protector", r"case|screen protector|cover"), ("other_accessory", r"antenna|band|strap|mount")]


Short = Annotated[str, Field(max_length=50)]


class Observation(BaseModel):
    observed_object: str = Field(max_length=60, description="What the object is, in a few words")
    category_guess: Literal[GUESSES]  # type: ignore[valid-type]
    visible_text: str = Field(max_length=60, description="Brand or model text printed on the item, or empty")
    color: str = Field(max_length=40)
    visible_damage: list[Short] = Field(max_length=4, description="Cracks, scratches, dents, fraying... [] if none")
    condition_grade: Literal["A", "B", "C", "D"] = Field(description="A like new, B light wear, C visible damage, D broken")
    photo_quality: Literal["good", "poor"]


class IdentityVerdict(BaseModel):
    same_product_type: Literal["yes", "no"]
    same_brand: Literal["yes", "no", "cannot_tell"]
    verdict: Literal["match", "mismatch", "uncertain"]
    confidence_pct: int = Field(ge=0, le=100)
    reason: str = Field(max_length=160, description="One short sentence")


class InspectState(TypedDict, total=False):
    case: dict
    photo_idx: int
    dock: dict
    catalog: dict
    verdict: dict
    result: dict
    retry: bool


OBSERVE_SYSTEM = ("You are a warehouse returns inspector looking at one photo. Describe only what is visible. "
                  "You do not know what the customer ordered.")
OBSERVE_TEXT = ("Describe the object in this photo. category_guess must be one of: " + ", ".join(GUESSES) +
                ". Use non_electronic only for things that are not electronic products at all (food, fruit, "
                "rocks, bricks, clothing, toys). Grade its condition: A like new, B light wear, C visible "
                "damage such as cracks, D broken or unusable.")
VERIFY_SYSTEM = ("You check whether a returned item is the product that was ordered, from two descriptions. "
                 "Judge only product type, shape and brand/model text. Ignore damage and condition (a cracked "
                 "unit of the same model is the same product), and ignore angle, lighting, background and "
                 "whatever is shown on a screen.")
NO_DAMAGE = re.compile(r"^(none|no|n/?a|nothing|no damage|no visible damage|like new|a like new|good|intact)\.?$", re.I)


def infer_category(text: str) -> str | None:
    t = text.lower()
    return next((cat for cat, pattern in KEYWORDS if re.search(pattern, t)), None)


class Inspector(SubAgent):
    name = "inspector"

    def __init__(self, *args, **kw):
        self._profiles: dict[str, dict] = {}
        super().__init__(*args, **kw)

    def build(self) -> StateGraph:
        g = StateGraph(InspectState)
        g.add_node("observe", self.observe)
        g.add_node("profile", self.profile)
        g.add_node("verify", self.verify)
        g.add_node("guard", self.guard)
        g.add_node("next_photo", self.next_photo)
        g.add_edge(START, "observe")
        g.add_edge("observe", "profile")
        g.add_edge("profile", "verify")
        g.add_edge("verify", "guard")
        g.add_conditional_edges("guard", lambda s: "next_photo" if s["retry"] else END,
                                {"next_photo": "next_photo", END: END})
        g.add_edge("next_photo", "observe")
        return g

    def run(self, case: dict, **inputs) -> dict:
        return self.graph.invoke({"case": case, "photo_idx": 0, **inputs})["result"]

    # --- nodes ------------------------------------------------------------------------------------
    def observe(self, s: InspectState) -> dict:
        case = s["case"]
        photo = self.image(case["return"]["photos"][s["photo_idx"]])
        obs = self.ask(case, Observation, OBSERVE_SYSTEM, OBSERVE_TEXT, [photo], node="observe").model_dump()
        obs = self._sanity(obs)
        self.log(case, "inspector.blind", f"Photo {s['photo_idx'] + 1} (blind): {obs['observed_object']} "
                 f"[{obs['category_guess']}], grade {obs['condition_grade']}"
                 + (f", text \"{obs['visible_text']}\"" if obs["visible_text"] else "")
                 + (f", damage: {', '.join(obs['visible_damage'])}" if obs["visible_damage"] else ""), obs)
        return {"dock": obs}

    def profile(self, s: InspectState) -> dict:
        """Describe the catalog photo once per SKU (reused by later cases for the same product)."""
        case, sku = s["case"], s["case"]["product"]["sku"]
        if sku not in self._profiles:
            obs = self.ask(case, Observation, OBSERVE_SYSTEM, OBSERVE_TEXT, [self.image(f"cat_{sku}.jpg")],
                           node="profile").model_dump()
            self._profiles[sku] = self._sanity(obs)
            self.log(case, "inspector.profile", f"Catalog photo: {obs['observed_object']} ({obs['color']})", obs)
        return {"catalog": self._profiles[sku]}

    def verify(self, s: InspectState) -> dict:
        case, dock, cat = s["case"], s["dock"], s["catalog"]
        p = case["product"]
        text = (f"Ordered product: \"{p['title'][:140]}\" (brand {p['brand']}, category {p['category']}).\n"
                f"Catalog photo of the ordered product shows: {cat['observed_object']}; color {cat['color']}; "
                f"text on item: \"{cat['visible_text']}\".\n"
                f"Item received at the dock shows: {dock['observed_object']}; color {dock['color']}; "
                f"text on item: \"{dock['visible_text']}\".\nIs the received item the same product as ordered?")
        v = self.ask(case, IdentityVerdict, VERIFY_SYSTEM, text, node="verify").model_dump()
        v["confidence"] = v.pop("confidence_pct") / 100
        self.log(case, "inspector.verify", f"{v['verdict']} ({v['confidence']:.2f}): {v['reason']}", v)
        return {"verdict": v}

    def guard(self, s: InspectState) -> dict:
        case, dock, v = s["case"], s["dock"], s["verdict"]
        p, r = case["product"], case["return"]
        identity, conf, guard = self.identity(v, dock, p, s["catalog"])
        defects = dock["visible_damage"]
        result = {
            "identity": identity, "confidence": round(conf, 2), "grade": dock["condition_grade"],
            "visible_defects": defects, "defect_visible": "yes" if defects else "not_visible",
            "defect_class": classify_defect(r["reason_category"], r["reason_text"], defects, dock["condition_grade"],
                                            p["category"]),
            "observed": dock["observed_object"], "observed_category": dock["category_guess"],
            "visible_text": dock["visible_text"], "guard": guard, "photos_used": s["photo_idx"] + 1,
            "notes": v["reason"], "brand_text_seen": self.brand_seen(dock, p),
        }
        if guard:
            self.log(case, "inspector.guard", f"Guard rule: {guard}", {"guard": guard})
        weak = identity == "uncertain" or conf < MIN_CONFIDENCE
        retry = weak and s["photo_idx"] + 1 < min(MAX_PHOTOS, len(r["photos"]))
        if not retry:
            self.log(case, "inspector.completed", f"{identity} ({conf:.2f}), grade {result['grade']}, "
                     f"defect {result['defect_class']}", result)
        return {"result": result, "retry": retry}

    def next_photo(self, s: InspectState) -> dict:
        self.log(s["case"], "inspector.reinspect", f"Low confidence ({s['result']['confidence']:.2f}); "
                 "inspecting the next photo", {"confidence": s["result"]["confidence"]})
        return {"photo_idx": s["photo_idx"] + 1}

    # --- rules ------------------------------------------------------------------------------------
    @staticmethod
    def _sanity(obs: dict) -> dict:
        """Clean up small-model quirks: 'none' listed as damage, a crack graded as B, a wrong enum value."""
        obs["visible_damage"] = [d for d in obs["visible_damage"] if len(d.strip()) > 2 and not NO_DAMAGE.match(d.strip())]
        seen = " ".join(obs["visible_damage"]).lower()
        if re.search(r"crack|shatter|broken|smash", seen) and obs["condition_grade"] in ("A", "B"):
            obs["condition_grade"] = "C"
        elif seen and obs["condition_grade"] == "A":
            obs["condition_grade"] = "B"
        if obs["visible_text"].strip().lower() in ("none", "n/a", "null"):
            obs["visible_text"] = ""
        guess = infer_category(obs["observed_object"])
        if guess and (obs["category_guess"] == "non_electronic" or
                      FAMILY.get(obs["category_guess"]) != FAMILY.get(guess)):
            obs["category_guess"] = guess
        return obs

    @staticmethod
    def brand_seen(dock: dict, product: dict) -> bool:
        """Did the blind pass read the product's brand (or a distinctive title word) on the item?
        OCR-tolerant: blurry dock photos turn AINOPE into ANKO, so near-matches of 4+ letters count."""
        tokens = [t for t in re.findall(r"[a-z0-9]+", dock.get("visible_text", "").lower()) if len(t) >= 3]
        words = {w for w in re.findall(r"[a-z0-9]+", " ".join([product.get("brand", ""),
                                                               *product["title"].split()[:4]]).lower())
                 if len(w) >= 3 and w not in {"the", "for", "with", "and", "new", "generic", "2023"}}
        return any(t in w or w in t or (min(len(t), len(w)) >= 4 and SequenceMatcher(None, t, w).ratio() >= 0.6)
                   for t in tokens for w in words)

    @staticmethod
    def same_text(dock: dict, catalog: dict) -> bool:
        """The same text printed on the received item and on the catalog product."""
        norm = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())  # noqa: E731
        a, b = norm(dock.get("visible_text", "")), norm(catalog.get("visible_text", ""))
        return len(a) >= 3 and len(b) >= 3 and (a in b or b in a)

    @classmethod
    def identity(cls, v: dict, dock: dict, product: dict, catalog: dict | None = None) -> tuple[str, float, str | None]:
        catalog = catalog or {}
        conf = float(v["confidence"])
        seen, expected = dock["category_guess"], product["category"]
        if seen == "non_electronic":
            return "mismatch", max(conf, 0.95), f"blind pass saw a non-electronic object ({dock['observed_object']})"
        evidence = cls.brand_seen(dock, product) or cls.same_text(dock, catalog)
        if FAMILY.get(seen) != FAMILY.get(expected, "accessory"):
            guard = f"blind pass saw a {seen}, the order is a {expected}"
            return ("uncertain", 0.5, guard) if evidence else ("mismatch", max(conf, 0.85), guard)
        if cls.brand_seen(dock, product):
            return "match", max(conf, 0.85), None
        if cls.same_text(dock, catalog):
            return "match", max(min(conf, 0.8), 0.75), None
        if float(product.get("list_price") or 0) >= HIGH_VALUE:  # expensive: the model's say-so is not enough
            return "uncertain", 0.5, (f"${float(product['list_price']):.0f} item: no brand or model text confirms "
                                      "identity, so a human should verify")
        if v["verdict"] == "match" and v["same_brand"] == "no":
            return "uncertain", min(conf, 0.5), None
        if v["verdict"] == "match":
            return "match", max(conf, 0.7), None
        if v["verdict"] == "mismatch":
            return "mismatch", max(conf, 0.7), None
        return "uncertain", min(conf, 0.5), None
