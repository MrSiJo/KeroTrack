"""JSON-on-disk price cache.

The cache lives at `<DATA_DIR>/price_cache.json` and is consulted before each
scrape. TTL controlled by `prices.cache_ttl_seconds`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class PriceCache:
    path: Path
    ttl_seconds: int = 86400

    def load(self) -> dict[str, Any] | None:
        try:
            return json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2))

    def is_fresh(self, payload: dict[str, Any] | None) -> bool:
        if not payload or not payload.get("fetched_at"):
            return False
        try:
            fetched = datetime.fromisoformat(payload["fetched_at"])
        except ValueError:
            return False
        age = (datetime.utcnow() - fetched).total_seconds()
        return age < self.ttl_seconds
