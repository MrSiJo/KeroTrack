"""Timezone-aware clock helpers.

Everything that timestamps a reading, runs an analysis, or writes a notifier
summary goes through here. v1 stored naive local-time strings (the LXC ran
in Europe/London), so v2 keeps that on-disk representation — but generates
the strings from `Bootstrap.tz` instead of UTC so BST/GMT transitions are
respected automatically.

`parse_local` attaches the configured zone to a stored naive string so age
and delta calculations against `local_now()` produce the right answer.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from kerotrack.bootstrap import get_bootstrap

_DEFAULT_TZ = "Europe/London"


def _zone(tz: str | None = None) -> ZoneInfo:
    if tz:
        return ZoneInfo(tz)
    try:
        return ZoneInfo(get_bootstrap().tz or _DEFAULT_TZ)
    except Exception:
        return ZoneInfo(_DEFAULT_TZ)


def local_now(tz: str | None = None) -> datetime:
    """Timezone-aware current time in the configured zone."""
    return datetime.now(tz=_zone(tz))


def local_now_str(tz: str | None = None) -> str:
    """v1-compatible 'YYYY-MM-DD HH:MM:SS' string in the configured zone.

    Naive on purpose — matches the format already in the readings table so
    string comparisons and ORDER BY stay correct.
    """
    return local_now(tz).strftime("%Y-%m-%d %H:%M:%S")


def parse_local(value: str | None, tz: str | None = None) -> datetime | None:
    """Parse a stored naive timestamp and attach the configured zone.

    Returns None if `value` is empty or unparseable. Multiple input formats
    are accepted to tolerate v1 + v2 + ISO variants found in the wild.
    """
    if not value:
        return None
    candidates = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%f",
    )
    zone = _zone(tz)
    for fmt in candidates:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=zone)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=zone)
        return dt
    except ValueError:
        return None
