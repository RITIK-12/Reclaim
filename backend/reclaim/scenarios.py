"""Scenario book: the labelled returns in scenarios/returns.json and their dock photos."""
from __future__ import annotations

import json
from functools import cached_property

from .config import settings
from .images import DockPhotoFactory, ImageStore
from .warehouse import Warehouse, warehouse

PHOTOS_PER_RETURN = 2


class ScenarioBook:
    def __init__(self, store: Warehouse = warehouse, images: ImageStore | None = None):
        self.store = store
        self.images = images or ImageStore()
        self.factory = DockPhotoFactory(self.images)

    @cached_property
    def spec(self) -> dict:
        return json.loads(settings.scenarios_file.read_text())

    def returns(self, which: str = "all") -> list[dict]:
        """which: all | demo | eval | or a demo stage: shift | live | classic."""
        return [r for r in self.spec["returns"] if which in ("all", r["set"], r.get("stage"))]

    @staticmethod
    def photo_names(key: str) -> list[str]:
        return [f"dock_{key}_{i}.jpg" for i in range(1, PHOTOS_PER_RETURN + 1)]

    def photos_for(self, s: dict) -> list[str]:
        """FLUX dataset returns carry their own photo files; the rest use generated dock photos."""
        return s.get("photos") or self.photo_names(s["key"])

    def prepare_images(self, which: str = "all") -> list[str]:
        """Download catalog/external images and build dock photos. Returns the file names made."""
        items = self.returns(which)
        skus = {r["sku"] for r in items} | {r["photo"]["source"][4:] for r in items
                                            if r["photo"]["source"].startswith("sku:")}
        products = self.store.products(sorted(skus))
        missing = skus - products.keys()
        if missing:
            raise KeyError(f"SKUs not in reclaim_products: {sorted(missing)}")
        for sku, p in products.items():
            self.images.catalog(sku, p["image_url"])
        made = []
        for r in items:
            src = r["photo"]["source"]
            if r.get("photos"):  # FLUX photos already on disk (scripts/build_dataset.py)
                continue
            if src == "catalog":
                path = self.images.path(f"cat_{r['sku']}.jpg")
            elif src.startswith("sku:"):
                path = self.images.path(f"cat_{src[4:]}.jpg")
            else:
                ext = self.spec["external_images"][src[4:]]
                path = self.images.fetch(f"ext_{src[4:]}.jpg", ext["url"])
            for i in range(1, PHOTOS_PER_RETURN + 1):
                made.append(self.factory.make(r["key"], i, path, r["photo"]["effect"],
                                               cutout=not src.startswith("ext:")).name)
        return made
