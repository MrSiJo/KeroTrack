"""Bootstrap-only configuration loaded from `.env` before the database opens.

Per spec §5.3 only these keys live in `.env`. Everything else is a row in the
`settings` table and managed via the API/UI.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_PLACEHOLDERS = {
    "",
    "changeme",
    "change-me",
    "change_me",
    "your-secret-key",
    "your-secret",
    "secret",
    "placeholder",
}


class Bootstrap(BaseSettings):
    """Minimal env-driven configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    tz: str = "Europe/London"
    log_level: str = "INFO"
    backend_port: int = 9176
    frontend_port: int = 9177
    database_url: str = Field(
        default="sqlite+aiosqlite:////app/data/kerotrack.db",
        validation_alias="DATABASE_URL",
    )
    vite_api_url: str = "http://localhost:9176"
    app_secret_key: str = Field(default="", validation_alias="APP_SECRET_KEY")

    @field_validator("app_secret_key")
    @classmethod
    def _validate_secret_key(cls, value: str) -> str:
        # Allow empty during early phases — Phase 2.5 hardens this.
        if value == "":
            return value
        normalised = value.strip()
        if normalised.lower() in _PLACEHOLDERS:
            raise ValueError(
                "APP_SECRET_KEY must not be a placeholder value. "
                "Generate one with `openssl rand -hex 32`."
            )
        if len(normalised) < 32:
            raise ValueError(
                "APP_SECRET_KEY must be at least 32 characters. "
                "Generate one with `openssl rand -hex 32`."
            )
        return normalised


@lru_cache(maxsize=1)
def get_bootstrap() -> Bootstrap:
    return Bootstrap()


def reset_bootstrap_cache() -> None:
    get_bootstrap.cache_clear()
