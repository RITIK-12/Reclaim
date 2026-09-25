"""Synthetic reference data (clearly labelled as ours, not from the dataset): vendor RTV terms + cost model."""
from __future__ import annotations

# Vendor return-to-vendor terms by brand (lowercase): credit as a share of price paid, window in days.
VENDOR_TERMS: dict[str, tuple[float, int]] = {
    "apple": (0.90, 90), "bose": (0.90, 90), "sony": (0.85, 60), "samsung": (0.80, 60), "lg": (0.75, 60),
    "xiaomi": (0.70, 45), "poco": (0.70, 45), "acer": (0.60, 60), "lenovo": (0.60, 60), "hp": (0.65, 60),
    "dell": (0.65, 60), "asus": (0.60, 60), "msi": (0.60, 45), "jbl": (0.80, 60), "marshall": (0.80, 60),
    "garmin": (0.85, 60), "amazfit": (0.60, 45), "tcl": (0.60, 45), "wyze": (0.50, 30), "anker": (0.80, 90),
    "otterbox": (0.50, 30), "logitech": (0.80, 60),
}

# Cost model per category: handling/repack/shipping in USD, fees as fractions, repair cost per defect class.
# A defect class missing from `repair` means "not repairable for this category".
COST_MODEL: dict[str, dict] = {
    "phone":      dict(handling=8, repack=4, channel_fee=0.12, liquidation_pct=0.15, rtv_shipping=12,
                       repair={"screen_crack": 55, "cosmetic": 15, "battery": 35, "functional": 70}),
    "tablet":     dict(handling=8, repack=4, channel_fee=0.12, liquidation_pct=0.15, rtv_shipping=14,
                       repair={"screen_crack": 65, "cosmetic": 15, "battery": 40, "functional": 75}),
    "laptop":     dict(handling=12, repack=6, channel_fee=0.12, liquidation_pct=0.12, rtv_shipping=25,
                       repair={"screen_crack": 110, "cosmetic": 25, "battery": 60, "functional": 120}),
    "computer":   dict(handling=15, repack=8, channel_fee=0.12, liquidation_pct=0.12, rtv_shipping=35,
                       repair={"cosmetic": 25, "functional": 90}),
    "headphones": dict(handling=6, repack=3, channel_fee=0.15, liquidation_pct=0.12, rtv_shipping=10,
                       repair={"cosmetic": 12, "battery": 30, "functional": 40}),
    "earbuds":    dict(handling=5, repack=2, channel_fee=0.15, liquidation_pct=0.10, rtv_shipping=8,
                       repair={"cosmetic": 15}),  # charging-case shell / ear tips
    "speaker":    dict(handling=6, repack=3, channel_fee=0.15, liquidation_pct=0.12, rtv_shipping=12,
                       repair={"cosmetic": 10, "functional": 35}),
    "smartwatch": dict(handling=6, repack=3, channel_fee=0.12, liquidation_pct=0.15, rtv_shipping=8,
                       repair={"screen_crack": 45, "cosmetic": 10, "battery": 30, "functional": 50}),
    "camera":     dict(handling=6, repack=3, channel_fee=0.15, liquidation_pct=0.12, rtv_shipping=10,
                       repair={"screen_crack": 50, "cosmetic": 12, "functional": 45}),
    "display":    dict(handling=15, repack=10, channel_fee=0.12, liquidation_pct=0.10, rtv_shipping=40,
                       repair={"cosmetic": 20, "functional": 80}),
    "cable_charger":      dict(handling=3, repack=1, channel_fee=0.15, liquidation_pct=0.05, rtv_shipping=6, repair={}),
    "case_protector":     dict(handling=2, repack=1, channel_fee=0.15, liquidation_pct=0.05, rtv_shipping=5, repair={}),
    "computer_accessory": dict(handling=4, repack=2, channel_fee=0.15, liquidation_pct=0.08, rtv_shipping=8, repair={}),
    "other_accessory":    dict(handling=3, repack=1, channel_fee=0.15, liquidation_pct=0.06, rtv_shipping=6, repair={}),
}
