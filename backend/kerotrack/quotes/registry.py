"""Provider registry and polling."""

from __future__ import annotations

import dataclasses
import re

import httpx

from kerotrack.quotes.boilerjuice import BoilerJuice
from kerotrack.quotes.homefuelsdirect import HomeFuelsDirect
from kerotrack.quotes.models import PollResult, QuoteRequest, is_sane, quote_email
from kerotrack.quotes.nwffuels import NwfFuels
from kerotrack.quotes.theheatingoilcompany import TheHeatingOilCompany
from kerotrack.quotes.westernfuel import WesternFuel

PROVIDERS: dict[str, object] = {
    p.name: p
    for p in (
        HomeFuelsDirect(),
        TheHeatingOilCompany(),
        NwfFuels(),
        WesternFuel(),
        BoilerJuice(),
    )
}

# Cadences: "frequent" providers poll with the main buying run; "daily" ones
# (those that need an email address) poll once a day on their own cron.
FREQUENT = "frequent"
DAILY = "daily"

NO_EMAIL = "no email configured"

_QUERY = re.compile(r"\?[^\s'\"]*")


def cadence_of(name: str) -> str:
    provider = PROVIDERS.get(name)
    return str(getattr(provider, "cadence", FREQUENT))


def select_providers(names: list[str], cadence: str | None) -> list[str]:
    """The configured provider names that poll at `cadence` (None keeps all)."""
    if cadence is None:
        return list(names)
    return [n for n in names if cadence_of(n) == cadence]


def _err(e: Exception, req: QuoteRequest) -> str:
    """Error text for storage.

    URL query strings (which carry the postcode and email) are scrubbed, and
    so is any literal postcode or email left in the message.
    """
    text = _QUERY.sub("?<redacted>", str(e))
    for secret in (req.postcode, req.email):
        if secret:
            text = text.replace(secret, "<redacted>")
    return type(e).__name__ + ": " + text[:120]


async def poll(
    client: httpx.AsyncClient,
    req: QuoteRequest,
    names: list[str],
    *,
    email_pattern: str = "",
) -> list[PollResult]:
    """Poll each named provider once, retrying once on failure.

    Providers that need an email get their own address from `email_pattern`;
    without one they are skipped and recorded as an error. Options outside
    the plausible price range are discarded.
    """
    results: list[PollResult] = []
    for name in names:
        provider = PROVIDERS.get(name)
        if provider is None:
            results.append(PollResult(name, [], "unknown provider"))
            continue
        preq = req
        if getattr(provider, "requires_email", False):
            email = quote_email(email_pattern, name)
            if email is None:
                results.append(PollResult(name, [], NO_EMAIL))
                continue
            preq = dataclasses.replace(req, email=email)
        else:
            preq = dataclasses.replace(req, email=None)
        error: str | None = None
        options = []
        for _attempt in range(2):
            try:
                fetched = await provider.fetch(client, preq)  # type: ignore[attr-defined]
                options = [o for o in fetched if is_sane(o)]
                error = None if options else "no prices"
                break
            except Exception as e:  # noqa: BLE001 - any provider failure is recorded, not raised
                error = _err(e, preq)
        results.append(PollResult(name, options, error))
    return results
