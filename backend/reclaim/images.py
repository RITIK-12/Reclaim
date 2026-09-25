"""Image cache + synthetic dock photos.

The catalog has one clean product shot per SKU and no photos of damaged units, so dock photos are
generated from catalog images: product cut out, placed on a warehouse surface, rotated, relit,
optionally with a crack or scratch overlay. Deterministic per (key, index) so ground truth is stable.
"""
from __future__ import annotations

import hashlib
import math
import random
from pathlib import Path

import httpx
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from .config import settings

UA = {"User-Agent": "Reclaim-hackathon/0.1 (https://github.com/RITIK-12/Reclaim)"}
SURFACES = [(150, 118, 82), (122, 122, 128), (96, 88, 76), (170, 160, 140)]  # cardboard, steel, wood, bench


def _seed(*parts: object) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


class ImageStore:
    """Downloads and caches images under data/images."""

    def __init__(self, root: Path = settings.images_dir):
        self.root = root
        self._http = httpx.Client(timeout=30, follow_redirects=True, headers=UA)

    def path(self, name: str) -> Path:
        return self.root / name

    def fetch(self, name: str, url: str) -> Path:
        dest = self.path(name)
        if not dest.exists():
            r = self._http.get(url)
            r.raise_for_status()
            if not r.headers.get("content-type", "").startswith("image/"):
                raise ValueError(f"{url} did not return an image")
            dest.write_bytes(r.content)
        return dest

    def catalog(self, sku: str, url: str) -> Path:
        return self.fetch(f"cat_{sku}.jpg", url)


class DockPhotoFactory:
    def __init__(self, store: ImageStore):
        self.store = store

    def make(self, key: str, index: int, src: Path, effect: str = "none", cutout: bool = True) -> Path:
        rng = random.Random(_seed(key, index))
        img = Image.open(src).convert("RGB")
        if cutout:
            product, mask = self._cutout(img)
        else:  # real photo: keep it whole, like a snapshot laid on the bench
            img.thumbnail((900, 900))
            product, mask = img, Image.new("L", img.size, 255)
        if effect == "crack":
            product = self._overlay(product, mask, rng, self._draw_crack)
        elif effect == "scratch":
            product = self._overlay(product, mask, rng, self._draw_scratches)
        out = self._compose(product, mask, rng)
        dest = self.store.path(f"dock_{key}_{index}.jpg")
        out.save(dest, "JPEG", quality=rng.randint(68, 80))
        return dest

    # --- steps -----------------------------------------------------------------------------------
    @staticmethod
    def _cutout(img: Image.Image) -> tuple[Image.Image, Image.Image]:
        """Mask = everything not connected to the (near-white) border background."""
        img.thumbnail((900, 900))
        work = ImageOps.expand(img, border=4, fill=(255, 255, 255))
        for xy in [(0, 0), (work.width - 1, 0), (0, work.height - 1), (work.width - 1, work.height - 1)]:
            ImageDraw.floodfill(work, xy, (255, 0, 255), thresh=28)
        r, g, b = work.split()
        bg = ImageChops.multiply(ImageChops.multiply(r.point(lambda v: 255 if v > 250 else 0),
                                                     g.point(lambda v: 255 if v < 6 else 0)),
                                 b.point(lambda v: 255 if v > 250 else 0))
        mask = ImageOps.invert(bg).crop((4, 4, work.width - 4, work.height - 4)).filter(ImageFilter.MaxFilter(3))
        if mask.getbbox() is None or sum(mask.histogram()[128:]) < 0.05 * mask.width * mask.height:
            mask = Image.new("L", img.size, 255)  # not a white-background shot (e.g. real photo)
        return img, mask

    @staticmethod
    def _overlay(product: Image.Image, mask: Image.Image, rng: random.Random, painter) -> Image.Image:
        layer = Image.new("RGBA", product.size, (0, 0, 0, 0))
        painter(ImageDraw.Draw(layer), mask.getbbox() or (0, 0, *product.size), rng)
        alpha = ImageChops.multiply(layer.getchannel("A"), mask)
        layer.putalpha(alpha)
        base = product.convert("RGBA")
        base.alpha_composite(layer)
        return base.convert("RGB")

    @staticmethod
    def _draw_crack(d: ImageDraw.ImageDraw, box: tuple, rng: random.Random) -> None:
        x0, y0, x1, y1 = box
        w, h = x1 - x0, y1 - y0
        cx, cy = x0 + w * rng.uniform(0.35, 0.65), y0 + h * rng.uniform(0.3, 0.6)
        size = max(w, h)
        rays = []
        for i in range(rng.randint(11, 16)):
            ang = 2 * math.pi * i / 14 + rng.uniform(-0.25, 0.25)
            pts, (px, py) = [(cx, cy)], (cx, cy)
            for _ in range(rng.randint(4, 7)):
                step = size * rng.uniform(0.05, 0.12)
                ang += rng.uniform(-0.35, 0.35)
                px, py = px + step * math.cos(ang), py + step * math.sin(ang)
                pts.append((px, py))
            rays.append(pts)
        for pts in rays:  # dark shadow, then bright glass edge
            d.line([(x + 1.5, y + 1.5) for x, y in pts], fill=(20, 20, 20, 170), width=2)
            d.line(pts, fill=(245, 245, 245, 235), width=2)
        for ring in (1, 2, 3):  # concentric fracture rings
            ring_pts = [pts[min(ring, len(pts) - 1)] for pts in rays]
            d.line(ring_pts + ring_pts[:1], fill=(235, 235, 235, 200), width=1)
        r = size * 0.025
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(250, 250, 250, 220))

    @staticmethod
    def _draw_scratches(d: ImageDraw.ImageDraw, box: tuple, rng: random.Random) -> None:
        x0, y0, x1, y1 = box
        w, h = x1 - x0, y1 - y0
        for _ in range(rng.randint(9, 14)):
            sx, sy = x0 + rng.uniform(0.1, 0.9) * w, y0 + rng.uniform(0.1, 0.9) * h
            ang, ln = rng.uniform(0, math.pi), max(w, h) * rng.uniform(0.1, 0.35)
            ex, ey = sx + ln * math.cos(ang), sy + ln * math.sin(ang)
            d.line([(sx, sy), (ex, ey)], fill=(230, 230, 225, rng.randint(170, 230)), width=rng.choice([1, 2, 2, 3]))
        for _ in range(rng.randint(1, 3)):  # dents / scuffs
            sx, sy = x0 + rng.uniform(0.2, 0.8) * w, y0 + rng.uniform(0.2, 0.8) * h
            r = max(w, h) * rng.uniform(0.03, 0.06)
            d.ellipse((sx - r, sy - r * 0.6, sx + r, sy + r * 0.6), fill=(35, 30, 25, 150))

    @staticmethod
    def _compose(product: Image.Image, mask: Image.Image, rng: random.Random) -> Image.Image:
        W, H = 1024, 768
        base = Image.new("RGB", (W, H), rng.choice(SURFACES))
        noise = Image.effect_noise((W, H), rng.uniform(18, 30)).convert("RGB")
        base = Image.blend(base, ImageChops.multiply(base, noise), 0.35)
        grad = Image.linear_gradient("L").resize((W, H)).rotate(rng.choice([0, 90, 180, 270]))
        base = Image.composite(base, ImageEnhance.Brightness(base).enhance(0.7), grad)

        scale = rng.uniform(0.62, 0.8) * min(W / product.width, H / product.height)
        size = (max(1, int(product.width * scale)), max(1, int(product.height * scale)))
        prod, m = product.resize(size), mask.resize(size)
        angle = rng.uniform(-12, 12)
        prod, m = prod.rotate(angle, expand=True, resample=Image.BICUBIC), m.rotate(angle, expand=True)
        ox = (W - prod.width) // 2 + rng.randint(-40, 40)
        oy = (H - prod.height) // 2 + rng.randint(-30, 30)
        shadow = Image.new("RGB", prod.size, (15, 12, 10))
        base.paste(shadow, (ox + 12, oy + 14), m.filter(ImageFilter.GaussianBlur(10)).point(lambda v: v * 0.55))
        base.paste(prod, (ox, oy), m)

        base = ImageEnhance.Brightness(base).enhance(rng.uniform(0.82, 1.08))
        base = ImageEnhance.Contrast(base).enhance(rng.uniform(0.88, 1.1))
        base = ImageEnhance.Color(base).enhance(rng.uniform(0.85, 1.1))
        return base.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 0.8)))
