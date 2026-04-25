"""Bootstrap validator behaviour around APP_SECRET_KEY."""

from __future__ import annotations

import pytest

from kerotrack.bootstrap import Bootstrap


def test_empty_secret_is_allowed_for_eager_construction() -> None:
    boot = Bootstrap(app_secret_key="")
    assert boot.app_secret_key == ""


def test_require_secret_raises_when_empty() -> None:
    boot = Bootstrap(app_secret_key="")
    with pytest.raises(RuntimeError):
        boot.require_secret()


@pytest.mark.parametrize(
    "value",
    ["changeme", "your-secret-key", "secret", "placeholder"],
)
def test_placeholder_secret_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        Bootstrap(app_secret_key=value)


def test_short_secret_rejected() -> None:
    with pytest.raises(ValueError):
        Bootstrap(app_secret_key="abc")


def test_long_secret_accepted() -> None:
    boot = Bootstrap(app_secret_key="a" * 64)
    assert boot.require_secret() == "a" * 64
