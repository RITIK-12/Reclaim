"""Inspector: Liquid VLM sub-agent. Blind pass, then compare pass, category guard, re-inspect loop."""
from __future__ import annotations

from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from ..catalog import CATEGORIES, FAMILY
from ..decision import MIN_CONFIDENCE, classify_defect
from .base import SubAgent

GUESSES = tuple(CATEGORIES) + ("non_electronic",)
MAX_PHOTOS = 2


class BlindObservation(BaseModel):
    observed_object: str = Field(description="What the object is, in a few words")
    category_guess: Literal[GUESSES]  # type: ignore[valid-type]
    visible_text: str = Field(description="Brand or model text visible on the item, or empty")
    visible_damage: list[str] = Field(description="Cracks, scratches, dents, fraying... [] if none")
    packaging: Literal["sealed", "opened", "damaged", "none"]
    photo_quality: Literal["good", "poor"]


class CompareVerdict(BaseModel):
    observations: str = Field(description="One sentence comparing type, brand/logo, shape and color")
    same_product_type: Literal["yes", "no"]
    same_brand_and_model: Literal["yes", "no", "cannot_tell"]
    same_color: Literal["yes", "no", "cannot_tell"]
    condition_grade: Literal["A", "B", "C", "D"]
    visible_defects: list[str]
    defect_consistent_with_reason: Literal["yes", "no", "not_visible"]
    match_confidence: float = Field(ge=0, le=1)


class InspectState(TypedDict, total=False):
    case: dict
    photo_idx: int
    blind: dict
    compare: dict
    result: dict
    retry: bool


BLIND_SYSTEM = ("You are a warehouse returns inspector looking at one photo taken at the receiving dock. "
                "Describe only what is visible. You do not know what the customer ordered.")
COMPARE_SYSTEM = ("You are a warehouse returns inspector. Compare the catalog photo of the ordered product with "
                  "the photo of the item that actually arrived. Identity is about WHAT the item is (type, brand, "
                  "model, shape, color), never about its condition: a cracked or scratched unit of the same model "
                  "is still the same product. Grade condition separately.")


class Inspector(SubAgent):
    name = "inspector"

    def build(self) -> StateGraph:
        g = StateGraph(InspectState)
        g.add_node("blind", self.blind)
        g.add_node("compare", self.compare)
        g.add_node("guard", self.guard)
        g.add_node("next_photo", self.next_photo)
        g.add_edge(START, "blind")
        g.add_edge("blind", "compare")
        g.add_edge("compare", "guard")
        g.add_conditional_edges("guard", lambda s: "next_photo" if s["retry"] else END)
        g.add_edge("next_photo", "blind")
        return g

    def run(self, case: dict, **inputs) -> dict:
        return self.graph.invoke({"case": case, "photo_idx": 0, **inputs})["result"]

    def _photo(self, s: InspectState):
        return self.image(s["case"]["return"]["photos"][s["photo_idx"]])

    def blind(self, s: InspectState) -> dict:
        case = s["case"]
        obs = self.ask(case, BlindObservation, BLIND_SYSTEM,
                       "What object is in this photo? category_guess must be one of: " + ", ".join(GUESSES) +
                       ". Use non_electronic for anything that is not an electronic product (food, fruit, rocks, "
                       "bricks, clothing, toys).", [self._photo(s)], node="blind")
        self.log(case, "inspector.blind", f"Photo {s['photo_idx'] + 1}: sees {obs.observed_object} "
                 f"({obs.category_guess})", obs.model_dump())
        return {"blind": obs.model_dump()}

    def compare(self, s: InspectState) -> dict:
        case = s["case"]
        p, r = case["product"], case["return"]
        text = (f"Image 1 is the catalog photo of the ordered product: \"{p['title'][:150]}\" "
                f"(brand {p['brand']}, category {p['category']}). Image 2 is the item received at the dock. "
                f"A blind inspection of image 2 said: {s['blind']}. Customer's return reason: \"{r['reason_text']}\". "
                "Answer: is it the same product type? the same brand and model? the same color? Then grade the "
                "condition of image 2 (A like new, B light wear, C visible damage, D broken or unusable) and say "
                "whether the visible condition is consistent with the customer's reason.")
        v = self.ask(case, CompareVerdict, COMPARE_SYSTEM, text,
                     [self.image(f"cat_{p['sku']}.jpg"), self._photo(s)], node="compare")
        self.log(case, "inspector.compare", f"type {v.same_product_type}, brand/model {v.same_brand_and_model}, "
                 f"color {v.same_color}, grade {v.condition_grade}: {v.observations}", v.model_dump())
        return {"compare": v.model_dump()}

    def guard(self, s: InspectState) -> dict:
        """Code decides identity from the VLM's sub-answers, plus a category guard from the blind pass."""
        case, blind, v = s["case"], s["blind"], s["compare"]
        p = case["product"]
        identity, conf, guard = self.identity(v, blind, p)
        expected = FAMILY.get(p["category"], "accessory")
        seen = FAMILY.get(blind["category_guess"], "non_electronic")
        if blind["category_guess"] == "non_electronic":
            identity, conf = "mismatch", max(conf, 0.95)
            guard = f"blind pass saw a non-electronic object ({blind['observed_object']})"
        elif seen != expected:
            identity, conf = ("mismatch", max(conf, 0.85)) if v["same_product_type"] == "no" else \
                ("uncertain", min(conf, 0.5))
            guard = f"blind pass saw a {blind['category_guess']}, order is a {p['category']}"
        r = case["return"]
        defects = list(dict.fromkeys(blind["visible_damage"] + v["visible_defects"]))
        result = {
            "identity": identity, "confidence": round(conf, 2),
            "grade": v["condition_grade"], "visible_defects": defects,
            "defect_visible": v["defect_consistent_with_reason"],
            "defect_class": classify_defect(r["reason_category"], r["reason_text"], defects, v["condition_grade"]),
            "observed": blind["observed_object"], "guard": guard, "photos_used": s["photo_idx"] + 1,
            "notes": v["observations"], "brand_text_seen": self.brand_seen(blind, p),
        }
        if guard:
            self.log(case, "inspector.guard", f"Guard rule: {guard}", {"guard": guard})
        weak = result["identity"] == "uncertain" or result["confidence"] < MIN_CONFIDENCE
        retry = weak and s["photo_idx"] + 1 < min(MAX_PHOTOS, len(r["photos"]))
        if not retry:
            self.log(case, "inspector.completed", f"{result['identity']} ({result['confidence']:.2f}), grade "
                     f"{result['grade']}, defect {result['defect_class']}", result)
        return {"result": result, "retry": retry}

    @staticmethod
    def brand_seen(blind: dict, product: dict) -> bool:
        """Did the blind pass read the product's brand (or a distinctive title word) on the item?"""
        text = blind.get("visible_text", "").lower()
        words = {w for w in [product.get("brand", "").lower(), *product["title"].lower().split()[:4]]
                 if len(w) >= 3 and w not in {"the", "for", "with", "and", "new", "generic"}}
        return bool(text) and any(w in text for w in words)

    @classmethod
    def identity(cls, v: dict, blind: dict, product: dict) -> tuple[str, float, str | None]:
        conf = float(v["match_confidence"])
        same_family = FAMILY.get(blind["category_guess"]) == FAMILY.get(product["category"], "accessory")
        if cls.brand_seen(blind, product) and same_family:
            if v["same_brand_and_model"] == "yes":
                return "match", max(conf, 0.9), None
            return "match", 0.75, "brand text read on the item confirms identity despite the visual comparison"
        if v["same_product_type"] == "no" or v["same_brand_and_model"] == "no":
            return "mismatch", max(conf, 0.8), None
        if v["same_brand_and_model"] == "yes":
            return "match", max(conf, 0.7), None
        return ("match", 0.65, None) if v["same_color"] == "yes" else ("uncertain", min(conf, 0.5), None)

    def next_photo(self, s: InspectState) -> dict:
        self.log(s["case"], "inspector.reinspect", f"Low confidence ({s['result']['confidence']:.2f}); "
                 "inspecting the next photo", {"confidence": s["result"]["confidence"]})
        return {"photo_idx": s["photo_idx"] + 1}
