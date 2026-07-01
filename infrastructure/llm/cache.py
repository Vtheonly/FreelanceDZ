"""Disk cache for LLM responses — saves free-tier quota.

Keyed by a SHA-256 of (provider, model, business fingerprint, prompt version).
Stored as JSON files under `<CACHE_DIR>/llm/`.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

from config.settings import settings


class LLMCache:
    """Filesystem-backed JSON cache for LLM analysis responses."""

    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        self._dir = Path(cache_dir) if cache_dir else settings.llm_cache_path
        self._dir.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger("llm.cache")
        self._enabled = settings.ENABLE_LLM_CACHE

    @staticmethod
    def _make_key(provider: str, model: str, business_fingerprint: str, prompt_version: str) -> str:
        raw = f"{provider}|{model}|{business_fingerprint}|{prompt_version}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        # Use 2-level sharding to avoid huge flat directories.
        return self._dir / key[:2] / f"{key}.json"

    def get(self, provider: str, model: str, business_fingerprint: str, prompt_version: str) -> Optional[dict]:
        if not self._enabled:
            return None
        key = self._make_key(provider, model, business_fingerprint, prompt_version)
        path = self._path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._logger.debug("Cache HIT: %s", key[:12])
            return data
        except Exception as e:
            self._logger.warning("Failed reading cache file %s: %s", path, e)
            return None

    def set(
        self,
        provider: str,
        model: str,
        business_fingerprint: str,
        prompt_version: str,
        payload: dict,
    ) -> None:
        if not self._enabled:
            return
        key = self._make_key(provider, model, business_fingerprint, prompt_version)
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self._logger.debug("Cache SET: %s", key[:12])
        except Exception as e:
            self._logger.warning("Failed writing cache file %s: %s", path, e)

    def clear(self) -> int:
        """Delete every cached entry. Returns the number of files removed."""
        count = 0
        if not self._dir.exists():
            return 0
        for f in self._dir.rglob("*.json"):
            try:
                f.unlink()
                count += 1
            except OSError:
                pass
        self._logger.info("Cleared %d cache files.", count)
        return count
