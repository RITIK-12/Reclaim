from reclaim.decision import DecisionInput, classify_defect, decide, precedent_key
from reclaim.reference import COST_MODEL, VENDOR_TERMS


def vendor(brand):
    credit, window = VENDOR_TERMS[brand]
    return {"credit_pct": credit, "window_days": window, "rtv_allowed": True}


def make(**kw) -> DecisionInput:
    base = dict(category="phone", repairable=True, condition_at_sale="new", price_paid=280.0, list_price=295.0,
                days_since_purchase=9, reason_category="physical_damage", identity="match", match_confidence=0.9,
                grade="C", defect_class="screen_crack", defect_visible="yes",
                market={"new": 210.0, "used": 150.0, "refurb": 160.0}, cost=COST_MODEL["phone"], vendor=vendor("xiaomi"))
    base.update(kw)
    return DecisionInput(**base)


def test_cracked_phone_refurbish():
    d = decide(make())
    assert d.action == "REFURBISH" and "RETURN_TO_VENDOR" not in d.allowed


def test_functional_earbuds_rtv():
    d = decide(make(category="earbuds", repairable=False, price_paid=240, list_price=249, reason_category="functional",
                    grade="B", defect_class="battery", defect_visible="not_visible", cost=COST_MODEL["earbuds"],
                    vendor=vendor("bose"), market={"new": 199.0}))
    assert d.action == "RETURN_TO_VENDOR"


def test_cheap_cable_liquidate():
    d = decide(make(category="cable_charger", repairable=False, price_paid=18, list_price=18.99, grade="D",
                    defect_class="cosmetic", cost=COST_MODEL["cable_charger"], vendor=None, market={}))
    assert d.action == "LIQUIDATE" and d.allowed == ["LIQUIDATE"]


def test_packaging_restock():
    d = decide(make(category="headphones", price_paid=390, list_price=398, reason_category="packaging_damage", grade="A",
                    defect_class="packaging_only", defect_visible="no", cost=COST_MODEL["headphones"], vendor=vendor("sony"),
                    market={"new": 330.0, "open_box": 280.0, "refurb": 250.0}))
    assert d.action == "RESTOCK"


def test_mismatch_escalates():
    d = decide(make(identity="mismatch", match_confidence=0.95))
    assert d.action == "ESCALATE" and d.rules_fired[-1].startswith("R1")


def test_low_confidence_escalates():
    assert decide(make(match_confidence=0.4)).action == "ESCALATE"


def test_unverifiable_high_value_claim_then_precedent():
    kw = dict(category="laptop", price_paid=430, list_price=439.99, reason_category="functional", grade="B",
              defect_class="battery", defect_visible="not_visible", cost=COST_MODEL["laptop"], vendor=vendor("acer"),
              market={"new": 380.0, "refurb": 260.0})
    first = decide(make(**kw))
    assert first.action == "ESCALATE" and first.rules_fired[-1].startswith("R3a")
    second = decide(make(**kw, precedent={"case_id": "RMA-D6", "action": "RETURN_TO_VENDOR"}))
    assert second.action == "RETURN_TO_VENDOR" and second.precedent_ref == "RMA-D6"


def test_classify_defect():
    assert classify_defect("physical_damage", "screen is cracked", [], "C") == "screen_crack"
    assert classify_defect("functional", "stopped charging", [], "B") == "battery"
    assert classify_defect("packaging_damage", "box crushed", [], "A") == "packaging_only"
    assert precedent_key("laptop", "battery", "functional", "B") == "laptop|battery|functional|AB"
