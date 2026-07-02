"""Disk-based LLM response cache.

Avoids re-calling the LLM for identical prompts during development and
integration testing. The cache is content-addressed (SHA-256 of the
prompt) so identical prompts always hit the same file.

The cache is *best-effort*: any I/O error is swallowed and treated as
a cache miss. This means a corrupted cache file never breaks the
pipeline — it just causes one extra LLM call.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from config.settings import AppSettings, get_settings


_logger = logging.getLogger("infrastructure.llm.cache")


class LLMCache:
    """File-based, content-addressed cache for LLM responses."""

    def __init__(self, cache_dir: Optional[Path] = None, enabled: bool = True) -> None:
        self._enabled = enabled
        if not enabled:
            self._cache_dir = None
            return
        settings = get_settings()
        self._cache_dir = cache_dir or settings.llm_cache_path
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def enabled(self) -> bool:
        return self._enabled and self._cache_dir is not None

    def get(self, prompt: str, model: str) -> Optional[dict[str, Any]]:
        """Return the cached response for ``prompt``+``model``, or None."""
        if not self.enabled:
            return None
        path = self._path_for(prompt, model)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            _logger.debug("LLM cache hit: %s", path.name)
            return payload
        except (json.JSONDecodeError, OSError) as exc:
            _logger.warning("Corrupt cache file %s, ignoring: %s", path, exc)
            return None

    def set(self, prompt: str, model: str, response: dict[str, Any]) -> None:
        """Persist a response. Failures are logged but never raised."""
        if not self.enabled:
            return
        path = self._path_for(prompt, model)
        try:
            payload = {
                "model": model,
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "response": response,
            }
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            _logger.warning("Failed to write LLM cache %s: %s", path, exc)

    def clear(self) -> int:
        """Delete every cache file. Returns the number of files removed."""
        if not self.enabled or self._cache_dir is None:
            return 0
        removed = 0
        for f in self._cache_dir.rglob("*.json"):
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
        _logger.info("Cleared %d LLM cache files", removed)
        return removed

    # ------------------------------------------------------------------

    def _path_for(self, prompt: str, model: str) -> Path:
        """Return the cache file path for a given prompt+model.

        Files are sharded into a 2-level directory tree (first 2 hex chars
        / next 2 hex chars) to avoid having thousands of files in a
        single directory.
        """
        key = f"{model}::{prompt}"
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        shard = self._cache_dir / digest[:2] / digest[2:4]
        shard.mkdir(parents=True, exist_ok=True)
        return shard / f"{digest}.json"
