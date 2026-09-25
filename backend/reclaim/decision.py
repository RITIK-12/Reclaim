"""Deterministic disposition policy: expected value per action, hard constraints, escalation rules.

Rules decide what is legal and when a human must look; money maths picks among legal actions.
Pure functions only, so the policy is unit-tested and never depends on LLM mood.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

ACTIONS = ("RESTOCK", "REFURBISH", "RETURN_TO_VENDOR", "LIQUIDATE")
ESCALATE = "ESCALATE"
HIGH_VALUE = 300.0
CLOSE_CALL = 0.10
MIN_CONFIDENCE = 0.6


def classify_defect(reason_category: str, reason_text: str, visible_defects: list[str], grade: str) -> str:
    """Map what the customer said + what the inspector saw to a repair-cost class."""
    seen = " ".join(visible_defects).lower()
    said = reason_text.lower()
    if re.search(r"crack|shatter|broken (screen|glass)|smashed", seen + " " + said):
        return "screen_crack"
    if reason_category == "functional":
        return "battery" if re.search(r"batter|charg|power|dies", said) else "functional"
    if re.search(r"scratch|dent|scuff|fray|chip|worn|damage", seen) or reason_category == "physical_damage":
        return "cosmetic"
    if reason_category == "packaging_damage":
        return "packaging_only"
    return "none" if grade in ("A", "B") else "cosmetic"


def precedent_key(category: str, defect_class: str, reason_category: str, grade: str) -> str:
    band = "AB" if grade in ("A", "B") else "CD"
    return f"{category}|{defect_class}|{reason_category}|{band}"


@dataclass
class DecisionInput:
    category: str
    repairable: bool
    condition_at_sale: str
    price_paid: float
    list_price: float
    days_since_purchase: int
    reason_category: str
    identity: str                 # match | mismatch | uncertain
    match_confidence: float
    grade: str                    # A-D
    defect_class: str
    defect_visible: str           # yes | no | not_visible
    market: dict                  # new / used / refurb / open_box (float or None)
    cost: dict                    # handling, repack, channel_fee, liquidation_pct, rtv_shipping, repair{}
    vendor: dict | None = None    # credit_pct, window_days, rtv_allowed
    precedent: dict | None = None  # {"case_id", "action"} from a human decision with the same key


@dataclass
class Decision:
    action: str
    ev: dict[str, float]
    allowed: list[str]
    rules_fired: list[str] = field(default_factory=list)
    escalation_reason: str | None = None
    suggested_action: str | None = None
    precedent_ref: str | None = None
    confidence: float = 0.0
    uplift_vs_liquidate: float = 0.0
    basis: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def resale_basis(market: dict, list_price: float) -> dict:
    new = market.get("new") or list_price
    return {
        "new": round(new, 2),
        "open_box": round(market.get("open_box") or market.get("used") or 0.75 * new, 2),
        "refurb": round(market.get("refurb") or 0.65 * new, 2),
        "estimated": [k for k in ("new", "open_box", "refurb") if not market.get(k)],
    }


def expected_values(x: DecisionInput, basis: dict) -> dict[str, float]:
    c = x.cost
    fee = c["channel_fee"]
    repair = c["repair"].get(x.defect_class, 0.0) * (1.3 if x.grade == "D" else 1.0)  # badly broken: more work
    credit = (x.vendor or {}).get("credit_pct", 0.0)
    return {
        "RESTOCK": basis["open_box"] * (1 - fee) - c["handling"] - c["repack"],
        "REFURBISH": basis["refurb"] * (1 - fee) - repair - c["handling"] - c["repack"],
        "RETURN_TO_VENDOR": x.price_paid * credit - c["rtv_shipping"] - c["handling"],
        "LIQUIDATE": basis["new"] * c["liquidation_pct"] - c["handling"],
    }


def allowed_actions(x: DecisionInput) -> tuple[list[str], list[str]]:
    """Hard constraints. Returns (allowed, reasons for each excluded action)."""
    why_not = []
    ok = ["LIQUIDATE"]
    if x.identity == "match" and x.grade in ("A", "B") and x.reason_category in ("packaging_damage", "cosmetic") \
            and x.defect_class in ("none", "packaging_only", "cosmetic"):
        ok.append("RESTOCK")
    else:
        why_not.append("RESTOCK needs an intact, matching item returned for packaging/cosmetic reasons")
    if x.repairable and x.defect_class in x.cost["repair"]:
        ok.append("REFURBISH")
    else:
        why_not.append(f"REFURBISH: no repair path for {x.defect_class} on {x.category}")
    v = x.vendor
    if v and v.get("rtv_allowed", True) and x.condition_at_sale == "new" and x.reason_category == "functional" \
            and x.days_since_purchase <= v.get("window_days", 0):
        ok.append("RETURN_TO_VENDOR")
    else:
        why_not.append("RETURN_TO_VENDOR needs vendor terms, a new item, a functional defect and the window")
    return [a for a in ACTIONS if a in ok], why_not


def decide(x: DecisionInput) -> Decision:
    basis = resale_basis(x.market, x.list_price)
    ev_all = {k: round(v, 2) for k, v in expected_values(x, basis).items()}
    allowed, why_not = allowed_actions(x)
    ev = {k: ev_all[k] for k in allowed}
    ranked = sorted(ev, key=ev.get, reverse=True)
    best = ranked[0]
    liquidate = ev_all["LIQUIDATE"]
    confidence = round(x.match_confidence * (0.8 if basis["estimated"] else 1.0), 2)
    d = Decision(action=best, ev=ev_all, allowed=allowed, rules_fired=[f"excluded: {w}" for w in why_not],
                 suggested_action=best, confidence=confidence, basis=basis,
                 uplift_vs_liquidate=round(ev_all[best] - liquidate, 2))

    def escalate(rule: str, reason: str) -> Decision:
        d.action, d.escalation_reason = ESCALATE, reason
        d.rules_fired.append(rule)
        return d

    if x.identity == "mismatch":
        return escalate("R1 identity_mismatch", "The returned item does not match the ordered product (possible return fraud).")
    if x.identity == "uncertain" or x.match_confidence < MIN_CONFIDENCE:
        return escalate("R2 identity_unverified", f"Identity could not be verified (confidence {x.match_confidence:.2f}).")

    judgment = None
    if x.price_paid >= HIGH_VALUE and x.reason_category == "functional" and x.defect_visible != "yes":
        judgment = ("R3a unverifiable_high_value_claim",
                    f"${x.price_paid:.0f} functional claim that photos cannot verify; needs a human bench check.")
    elif x.price_paid >= HIGH_VALUE and len(ranked) > 1 and \
            ev[ranked[1]] >= ev[best] - abs(ev[best]) * CLOSE_CALL:
        judgment = ("R3b close_call", f"Top two options within {CLOSE_CALL:.0%} on a ${x.price_paid:.0f} item.")
    if judgment:
        p = x.precedent
        if p and p.get("action") in allowed:
            d.action, d.precedent_ref = p["action"], p.get("case_id")
            d.rules_fired.append(f"{judgment[0]} resolved by human precedent {p.get('case_id')}")
            d.uplift_vs_liquidate = round(ev_all[d.action] - liquidate, 2)
            return d
        return escalate(*judgment)
    d.rules_fired.append(f"max EV among allowed: {best}")
    return d
