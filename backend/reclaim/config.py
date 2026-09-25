"""Settings loaded once from the repo-level .env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    # RawTree (shared workspace, so every table gets our prefix)
    rawtree_url: str = _env("RAWTREE_URL", "https://api.rawtree.com")
    rawtree_key: str = _env("RAWTREE_API_KEY")
    table_prefix: str = _env("RECLAIM_TABLE_PREFIX", "reclaim_")
    # Nimble
    nimble_url: str = _env("NIMBLE_URL", "https://sdk.nimbleway.com")
    nimble_key: str = _env("NIMBLE_API_KEY")
    # Black Forest Labs (FLUX.2) for synthetic dock photos
    bfl_url: str = _env("BFL_URL", "https://api.bfl.ai")
    bfl_key: str = _env("BFL_API_KEY")
    # Liquid via LM Studio (one model for vision + text)
    llm_url: str = _env("LLM_URL", "http://localhost:1234/v1")
    llm_model: str = _env("LLM_MODEL", "lfm2.5-vl-3b")
    image_max_side: int = int(_env("IMAGE_MAX_SIDE", "768"))
    # Local paths
    data_dir: Path = ROOT / "data"
    images_dir: Path = field(default_factory=lambda: ROOT / "data" / "images")
    checkpoint_db: Path = field(default_factory=lambda: ROOT / "data" / "checkpoints.sqlite")
    scenarios_file: Path = field(default_factory=lambda: ROOT / "backend" / "scenarios" / "returns.json")
    # Agent knobs
    price_ttl_hours: int = 6
    max_steps: int = 12
    watcher_interval_s: float = 1.5

    def table(self, name: str) -> str:
        return f"{self.table_prefix}{name}"


settings = Settings()
settings.images_dir.mkdir(parents=True, exist_ok=True)
