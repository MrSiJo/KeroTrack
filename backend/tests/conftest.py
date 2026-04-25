"""Shared pytest fixtures for the KeroTrack v2 backend test suite."""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "kerotrack-test.db"


@pytest.fixture
def temp_app_secret_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = "0" * 64
    monkeypatch.setenv("APP_SECRET_KEY", key)
    return key
