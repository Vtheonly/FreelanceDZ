"""Application settings, loaded from environment / .env file via pydantic-settings.

Usage:
    from config.settings import settings
    print(settings.LLM_API_KEY)
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from domain.exceptions import ConfigurationError


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class AppSettings(BaseSettings):
    """All runtime configuration lives here.

    Values can be overridden via environment variables or a `.env` file
    at the project root.
    """

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -------- LLM --------
    LLM_PROVIDER: Literal["groq", "openrouter"] = "groq"
    LLM_API_KEY: str = Field(default="", description="Free-tier API key (Groq or OpenRouter)")
    LLM_API_BASE: str = "https://api.groq.com/openai/v1"
    LLM_MODEL: str = "llama-3.1-8b-instant"

    # -------- Operational --------
    LOG_LEVEL: str = "INFO"
    MAX_CONCURRENT_REQUESTS: int = 2
    RATE_LIMIT_DELAY_SECONDS: float = 3.0
    LLM_MAX_RETRIES: int = 4
    LLM_TIMEOUT_SECONDS: int = 45
    ENABLE_LLM_CACHE: bool = True
    CACHE_DIR: str = str(PROJECT_ROOT / "data" / "cache")

    # -------- Scraping --------
    SCRAPER_TIMEOUT_SECONDS: int = 20
    SCRAPER_USER_AGENT: str = "DZ-SalesIntel/1.0 (+https://github.com/local)"
    ENABLE_OVERPASS_SCRAPER: bool = True
    ENABLE_DDG_SCRAPER: bool = True
    ENABLE_MOCK_SCRAPER: bool = True

    # -------- Storage --------
    DATABASE_PATH: str = str(PROJECT_ROOT / "data" / "leads.db")
    EXPORT_DIR: str = str(PROJECT_ROOT / "data" / "exports")

    # -------- Pipeline defaults --------
    DEFAULT_WILAYA: str = "Algiers"
    DEFAULT_COUNTRY: str = "Algeria"
    DEFAULT_QUERY_LIMIT: int = 10
    TOP_LEADS_N: int = 20

    # -------- API / Dashboard --------
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8080
    ENABLE_DASHBOARD: bool = True

    # -------- Validators --------

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

    # -------- Derived helpers --------

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

    def ensure_directories(self) -> None:
        """Create every directory the app expects to write to."""
        for p in [
            Path(self.DATABASE_PATH).parent,
            Path(self.CACHE_DIR),
            self.llm_cache_path,
            Path(self.EXPORT_DIR),
            PROJECT_ROOT / "data" / "logs",
        ]:
            p.mkdir(parents=True, exist_ok=True)

    def validate_for_llm(self) -> None:
        """Raise ConfigurationError if LLM cannot be used (missing key, etc.)."""
        if not self.LLM_API_KEY:
            raise ConfigurationError(
                "LLM_API_KEY is missing. Add it to your .env file."
            )


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Cached singleton accessor."""
    s = AppSettings()
    s.ensure_directories()
    return s


# Convenience module-level instance.
settings = get_settings()
