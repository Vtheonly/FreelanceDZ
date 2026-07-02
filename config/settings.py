"""Centralised, validated application settings.

Uses ``pydantic-settings`` so every value can be overridden via environment
variables or a ``.env`` file at the project root. All values have sensible
defaults so the engine runs out of the box with no configuration.

Design rules
------------
* No hardcoded secrets — every credential defaults to an empty string and
  is only validated when the corresponding feature is actually used.
* All filesystem paths are stored as strings and converted to ``Path``
  via the ``resolved_*`` properties, so callers always get a ``Path``
  object back.
* The singleton is cached via ``lru_cache`` so importing the module is
  cheap and configuration changes between tests require an explicit
  ``get_settings.cache_clear()`` call.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.constants import APP_DESCRIPTION, APP_NAME, APP_VERSION
from core.exceptions import ConfigurationError


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class AppSettings(BaseSettings):
    """All runtime configuration lives here.

    Values can be overridden via environment variables or a ``.env`` file
    at the project root. Variable names are case-insensitive.
    """

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -------- Application metadata (read-only, used for logging/OpenAPI) --------
    APP_NAME: str = APP_NAME
    APP_VERSION: str = APP_VERSION
    APP_DESCRIPTION: str = APP_DESCRIPTION

    # -------- LLM --------
    LLM_PROVIDER: Literal["groq", "openrouter"] = "groq"
    LLM_API_KEY: str = Field(default="", description="Primary API key")
    LLM_FALLBACK_KEYS: str = Field(
        default="",
        description="Comma-separated fallback keys tried in order if the primary key fails",
    )
    LLM_API_BASE: str = "https://api.groq.com/openai/v1"
    LLM_MODELS: str = Field(
        default="llama-3.1-8b-instant,llama-3.1-70b-versatile",
        description="Comma-separated model IDs tried in order",
    )
    LLM_MAX_RETRIES: int = Field(default=4, ge=0)
    LLM_TIMEOUT_SECONDS: int = Field(default=45, ge=5)
    ENABLE_LLM_CACHE: bool = True

    # -------- Logging --------
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = str(PROJECT_ROOT / "data" / "logs")
    LOG_FORMAT: Literal["console", "json"] = "console"

    # -------- Scraping --------
    SCRAPER_TIMEOUT_SECONDS: int = Field(default=20, ge=5)
    MAX_CONCURRENT_REQUESTS: int = Field(default=10, ge=1)
    RATE_LIMIT_DELAY_SECONDS: float = Field(default=2.0, ge=0.0)
    MAX_CRAWL_DEPTH: int = Field(default=3, ge=0, le=10)
    MAX_SEARCH_PAGES: int = Field(default=3, ge=1, le=20)

    ENABLE_OVERPASS_SCRAPER: bool = True
    ENABLE_DDG_SCRAPER: bool = True
    ENABLE_SOCIAL_SCRAPER: bool = False

    # -------- HTTP client --------
    HTTP_ENABLE_HTTP2: bool = True
    HTTP_MAX_CONNECTIONS: int = Field(default=50, ge=1)
    HTTP_KEEPALIVE_CONNECTIONS: int = Field(default=10, ge=1)
    HTTP_KEEPALIVE_EXPIRY: float = Field(default=30.0, ge=1.0)
    HTTP_CONNECT_TIMEOUT: float = Field(default=10.0, ge=1.0)
    HTTP_POOL_TIMEOUT: float = Field(default=30.0, ge=1.0)

    # -------- Proxies --------
    PROXY_LIST: str = Field(default="", description="Comma-separated proxy URLs")
    PROXY_MIN_HEALTH: float = Field(default=20.0, ge=0.0, le=100.0)

    # -------- Anti-blocking --------
    JITTER_BASE_DELAY: float = Field(default=1.5, ge=0.0)

    # -------- Storage --------
    DATABASE_PATH: str = str(PROJECT_ROOT / "data" / "deephuntr.db")
    EXPORT_DIR: str = str(PROJECT_ROOT / "data" / "exports")
    CACHE_DIR: str = str(PROJECT_ROOT / "data" / "cache")

    # -------- Pipeline defaults --------
    DEFAULT_WILAYA: str = "Algiers"
    DEFAULT_COUNTRY: str = "Algeria"
    DEFAULT_QUERY_LIMIT: int = Field(default=30, ge=1)
    TOP_LEADS_N: int = Field(default=50, ge=1)

    # -------- API / Dashboard --------
    API_HOST: str = "0.0.0.0"
    API_PORT: int = Field(default=8080, ge=1, le=65535)
    ENABLE_DASHBOARD: bool = True

    # -------- Entity Resolution --------
    # The name threshold is the minimum Levenshtein similarity for two names
    # to be considered "similar" (0.78 ≈ "Pharmacie Centrale" vs "Pharmacie Centrale Oran").
    ENTITY_NAME_THRESHOLD: float = Field(default=0.78, ge=0.0, le=1.0)
    # The composite threshold is the minimum weighted score to merge two records.
    # At 0.65, two records with identical name (0.40) + identical website (0.25)
    # score exactly 0.65 and will merge — which is the desired behaviour for the
    # common case of the same business discovered by multiple scrapers.
    ENTITY_COMPOSITE_THRESHOLD: float = Field(default=0.65, ge=0.0, le=1.0)
    ENTITY_MAX_BLOCK_SIZE: int = Field(default=100, ge=2)

    # -------- Infinite Crawler --------
    FRONTIER_POLITENESS_DELAY: int = Field(default=5, ge=0)
    FRONTIER_MAX_FAILURES: int = Field(default=5, ge=1)
    FRONTIER_IDLE_SLEEP: int = Field(default=10, ge=1)

    # ============================================================
    #  Validators
    # ============================================================

    @field_validator("LOG_LEVEL")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ConfigurationError(
                f"LOG_LEVEL must be one of {allowed}, got '{v}'."
            )
        return upper

    @field_validator("LLM_PROVIDER")
    @classmethod
    def _validate_provider(cls, v: str) -> str:
        v = v.lower()
        if v not in {"groq", "openrouter"}:
            raise ConfigurationError(
                f"LLM_PROVIDER must be 'groq' or 'openrouter', got '{v}'."
            )
        return v

    # ============================================================
    #  Derived helpers
    # ============================================================

    @property
    def llm_cache_path(self) -> Path:
        return Path(self.CACHE_DIR) / "llm"

    @property
    def resolved_db_path(self) -> Path:
        return Path(self.DATABASE_PATH)

    @property
    def resolved_export_dir(self) -> Path:
        p = Path(self.EXPORT_DIR)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def resolved_log_dir(self) -> Path:
        return Path(self.LOG_DIR)

    @property
    def llm_models_list(self) -> list[str]:
        return [m.strip() for m in self.LLM_MODELS.split(",") if m.strip()]

    @property
    def llm_fallback_keys_list(self) -> list[str]:
        return [k.strip() for k in self.LLM_FALLBACK_KEYS.split(",") if k.strip()]

    @property
    def proxy_list_parsed(self) -> list[str]:
        return [p.strip() for p in self.PROXY_LIST.split(",") if p.strip()]

    def ensure_directories(self) -> None:
        """Create every directory the app expects to write to."""
        for p in [
            Path(self.DATABASE_PATH).parent,
            Path(self.CACHE_DIR),
            self.llm_cache_path,
            Path(self.EXPORT_DIR),
            Path(self.LOG_DIR),
        ]:
            p.mkdir(parents=True, exist_ok=True)

    def validate_for_llm(self) -> None:
        """Raise ``ConfigurationError`` if LLM cannot be used."""
        if not self.LLM_API_KEY:
            raise ConfigurationError(
                "LLM_API_KEY is missing. Add it to your .env file or set the env var."
            )


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Cached singleton accessor."""
    s = AppSettings()
    s.ensure_directories()
    return s


# Module-level convenience instance. Tests that need a different config
# should call ``get_settings.cache_clear()`` after mutating the env.
settings = get_settings()
