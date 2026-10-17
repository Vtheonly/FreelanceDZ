"""Centralized engine settings (pydantic-settings).

v3 cleanup: every field here is actually consumed somewhere. Dead fields
removed: LLM_* (stack deleted), ENABLE_SOCIAL_SCRAPER, DEFAULT_COUNTRY,
TOP_LEADS_N, LLM_FALLBACK_KEYS, LLM_MAX_RETRIES. Hardware-derived defaults
(worker/concurrency limits) are computed at import from os.cpu_count() with
sanity bounds — overridable via env vars, never unbounded.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_CPUS = os.cpu_count() or 2

# Hardware-derived defaults, bounded. Personal machines range from 2 to 32+
# cores; the engine is network-bound so workers scale with cores but the
# return flattens quickly.
DEFAULT_CRAWLER_WORKERS = max(2, min(16, _CPUS * 4))
DEFAULT_MAX_CONCURRENCY = max(8, min(64, _CPUS * 8))
DEFAULT_HTTP_CONNECTIONS = max(20, min(200, _CPUS * 16))


class AppSettings(BaseSettings):
    """Deterministic, fully-wired engine configuration."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- application ------------------------------------------------------
    APP_NAME: str = "FreelanceDZ Engine"
    APP_VERSION: str = "3.1.0"
    API_HOST: str = "127.0.0.1"          # personal use: localhost by default
    API_PORT: int = Field(default=8080, ge=1, le=65535)
    ENABLE_DASHBOARD: bool = True

    # --- logging -----------------------------------------------------------
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = str(PROJECT_ROOT / "data" / "logs")
    LOG_FORMAT: Literal["console", "json"] = "console"

    # --- storage -----------------------------------------------------------
    DATABASE_PATH: str = str(PROJECT_ROOT / "data" / "leads.db")
    EXPORT_DIR: str = str(PROJECT_ROOT / "data" / "exports")
    ATTACHMENTS_DIR: str = str(PROJECT_ROOT / "data" / "attachments")

    # --- discovery -----------------------------------------------------------
    SCRAPER_TIMEOUT_SECONDS: float = Field(default=20.0, ge=3.0)
    MAX_CONCURRENT_REQUESTS: int = Field(default=_CPUS * 2, ge=1, le=128)
    RATE_LIMIT_DELAY_SECONDS: float = Field(default=1.5, ge=0.0)
    MAX_SEARCH_PAGES: int = Field(default=3, ge=1, le=20)
    MAX_CRAWL_DEPTH: int = Field(default=3, ge=0, le=10)
    ENABLE_OVERPASS_SCRAPER: bool = True
    ENABLE_DDG_SCRAPER: bool = True
    DEFAULT_QUERY_LIMIT: int = Field(default=30, ge=1, le=200)

    # --- HTTP pool -----------------------------------------------------------
    HTTP_ENABLE_HTTP2: bool = True
    HTTP_MAX_CONNECTIONS: int = Field(default=DEFAULT_HTTP_CONNECTIONS, ge=1)
    HTTP_KEEPALIVE_CONNECTIONS: int = Field(default=max(10, DEFAULT_HTTP_CONNECTIONS // 4), ge=1)
    HTTP_KEEPALIVE_EXPIRY: float = Field(default=30.0, ge=1.0)
    HTTP_CONNECT_TIMEOUT: float = Field(default=10.0, ge=1.0)
    HTTP_POOL_TIMEOUT: float = Field(default=30.0, ge=1.0)

    # --- crawler -----------------------------------------------------------
    CRAWLER_WORKERS: int = Field(default=DEFAULT_CRAWLER_WORKERS, ge=1, le=64)
    ACQ_MIN_CONCURRENCY: int = Field(default=4, ge=1, le=64)
    ACQ_MAX_CONCURRENCY: int = Field(default=DEFAULT_MAX_CONCURRENCY, ge=1, le=256)
    ACQ_DOMAIN_RATE: float = Field(default=2.0, gt=0.0)     # requests/sec/domain
    ACQ_DOMAIN_BURST: int = Field(default=4, ge=1)
    FRONTIER_POLITENESS_DELAY: float = Field(default=5.0, ge=0.0)
    FRONTIER_MAX_FAILURES: int = Field(default=5, ge=1)
    FRONTIER_IDLE_SLEEP: float = Field(default=10.0, ge=0.1)
    BLOOM_CAPACITY: int = Field(default=2_000_000, ge=10_000)
    JITTER_BASE_DELAY: float = Field(default=1.0, ge=0.0)

    # --- proxies / resilience -------------------------------------------------
    PROXY_LIST: str = ""
    PROXY_MIN_HEALTH: float = Field(default=20.0, ge=0.0, le=100.0)

    # --- entity resolution -------------------------------------------------
    # v3.0 pipeline (kept for the compat shim + prefilter tuning):
    ENTITY_NAME_THRESHOLD: float = Field(default=0.78, ge=0.0, le=1.0)
    ENTITY_COMPOSITE_THRESHOLD: float = Field(default=0.65, ge=0.0, le=1.0)
    ENTITY_MAX_BLOCK_SIZE: int = Field(default=100, ge=2)
    ENTITY_JACCARD_PREFILTER: float = Field(default=0.40, ge=0.0, le=1.0)
    ENTITY_RESOLUTION_BATCH: int = Field(default=20_000, ge=100)

    # v3.1 evidence-based entity resolution (engine/resolution/).
    # Precision-first: a false merge is worse than a temporary duplicate,
    # so auto-merge demands identity-level corroboration (shared phone,
    # matching social handle, cross references, co-location) and names
    # alone can never reach it. Ambiguous pairs land in the review queue.
    ENTITY_MERGE_IDENTITY: float = Field(default=0.70, ge=0.0, le=3.0,
        description="identity-evidence sum required to auto-merge a pair")
    ENTITY_MERGE_MAX_CONFLICT: float = Field(default=0.45, ge=0.0, le=3.0,
        description="disagreement sum above which a pair cannot auto-merge")
    ENTITY_MERGE_MIN_NAME: float = Field(default=0.45, ge=0.0, le=1.0,
        description="name similarity below which a pair never auto-merges")
    ENTITY_RELATED_MIN_ORG: float = Field(default=0.90, ge=0.0, le=3.0,
        description="organizational-evidence sum required for RELATED")
    ENTITY_RELATED_MIN_NAME: float = Field(default=0.55, ge=0.0, le=1.0,
        description="name similarity required for RELATED (branches etc.); "
                    "the org-evidence bar is the real gatekeeper")
    ENTITY_DISTINCT_TOTAL: float = Field(default=0.10, ge=-3.0, le=3.0,
        description="total at or below which a pair is confidently distinct")
    ENTITY_AUTO_RESOLVE: bool = Field(default=True,
        description="run incremental resolution after each discovery campaign")
    ENTITY_DECISION_LOG_LIMIT: int = Field(default=50_000, ge=100,
        description="max decision rows kept per resolve run (FIFO trim)")

    # --- regional defaults -------------------------------------------------
    DEFAULT_WILAYA: str = "Alger"

    @field_validator("LOG_LEVEL")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        val = v.upper()
        if val not in valid:
            raise ValueError(f"LOG_LEVEL must be one of {valid}")
        return val

    # --- resolved paths -----------------------------------------------------
    @property
    def resolved_db_path(self) -> Path:
        return Path(self.DATABASE_PATH)

    @property
    def resolved_export_dir(self) -> Path:
        p = Path(self.EXPORT_DIR)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def resolved_attachments_dir(self) -> Path:
        p = Path(self.ATTACHMENTS_DIR)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def proxy_list_parsed(self) -> list[str]:
        return [
            u.strip()
            for u in self.PROXY_LIST.replace("\n", ",").split(",")
            if u.strip()
        ]

    def ensure_directories(self) -> None:
        for p in (
            self.resolved_db_path.parent,
            self.resolved_export_dir,
            self.resolved_attachments_dir,
            Path(self.LOG_DIR),
        ):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    settings = AppSettings()
    settings.ensure_directories()
    return settings
