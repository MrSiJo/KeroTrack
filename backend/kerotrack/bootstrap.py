"""Bootstrap-only configuration loaded from `.env` before the database opens.

Per spec §5.3 only these keys live in `.env`. Everything else is a row in the
`settings` table and managed via the API/UI.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


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
    database_url: str = "sqlite+aiosqlite:////app/data/kerotrack.db"
    vite_api_url: str = "http://localhost:9176"
    app_secret_key: str = ""
    # Default deployment runs behind nginx-proxy-manager terminating TLS, so
    # the session cookie is `Secure`. Override to `false` for plain-HTTP
    # local dev or test rigs that drive the API over `http://`.
    session_cookie_secure: bool = True

    @field_validator("app_secret_key")
    @classmethod
    def _validate_secret_key(cls, value: str) -> str:
        # Empty is permitted only for tests that explicitly opt out by passing
        # a generated key via a test fixture. The auth middleware refuses to
        # start without a valid key (see `Bootstrap.require_secret`).
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

    @property
    def data_dir(self) -> Path:
        """Directory for runtime data files (price cache, …).

        Derived from `DATABASE_URL`'s SQLite file path so it follows the DB
        wherever it is configured — the previous hardcoded `/app/data` made
        every non-Docker dev run fail trying to create it (KERO-M3). Falls
        back to the Docker default for in-memory/non-file URLs.
        """
        try:
            db_path = make_url(self.database_url).database
        except Exception:  # noqa: BLE001 — malformed URL fails later, at init_engine
            db_path = None
        if db_path and db_path != ":memory:":
            return Path(db_path).resolve().parent
        return Path("/app/data")

    def require_secret(self) -> str:
        """Return a non-empty `app_secret_key` or raise.

        Called from the auth lifespan path so `pytest`-time imports without
        the env var don't fail just from defining the model.
        """
        if not self.app_secret_key:
            raise RuntimeError(
                "APP_SECRET_KEY is required. Generate one with "
                "`openssl rand -hex 32` and put it in `.env`."
            )
        return self.app_secret_key


@lru_cache(maxsize=1)
def get_bootstrap() -> Bootstrap:
    return Bootstrap()


def reset_bootstrap_cache() -> None:
    get_bootstrap.cache_clear()
