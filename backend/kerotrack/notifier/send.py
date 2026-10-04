"""Generic Apprise send, shared by the weekly digest and the buy planner."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import apprise


def build_apprise(urls: list[str]) -> apprise.Apprise:
    """Build an Apprise instance; Gotify URLs are auto-tagged `format=markdown`."""
    instance = apprise.Apprise()
    for url in urls:
        if url.startswith("gotify://") and "format=markdown" not in url:
            sep = "&" if "?" in url else "?"
            instance.add(f"{url}{sep}format=markdown")
        else:
            instance.add(url)
    return instance


async def send(
    urls: list[str],
    title: str,
    body: str,
    *,
    apprise_factory: Callable[[list[str]], Any] | None = None,
) -> bool:
    """Send a Markdown notification. Returns False when no URLs are given.

    `apprise.notify()` is synchronous network I/O, so it runs in a worker
    thread to keep the event loop free (KERO-M1).
    """
    if not urls:
        return False
    instance = (apprise_factory or build_apprise)(urls)
    return bool(
        await asyncio.to_thread(
            instance.notify,
            body=body,
            title=title,
            body_format=apprise.NotifyFormat.MARKDOWN,
        )
    )
