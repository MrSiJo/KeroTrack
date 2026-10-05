"""Persistence for supplier quotes and index readings (`price_quotes`)."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.models.price_quote import PriceQuote
from kerotrack.quotes.models import PollResult, effective_ppl

_FMT = "%Y-%m-%d %H:%M:%S"


async def save_poll(
    sf: async_sessionmaker, fetched_at: str, litres: int, results: list[PollResult]
) -> int:
    """Write one row per option, or one ok=0 row for an option-less result."""
    rows: list[PriceQuote] = []
    for result in results:
        if not result.options:
            rows.append(
                PriceQuote(
                    fetched_at=fetched_at,
                    supplier=result.supplier,
                    kind="quote",
                    litres=litres,
                    urgent=0,
                    fees_inc_vat=0.0,
                    ok=0,
                    error=result.error or "no options returned",
                )
            )
            continue
        for o in result.options:
            rows.append(
                PriceQuote(
                    fetched_at=fetched_at,
                    supplier=o.supplier,
                    kind="quote",
                    litres=o.litres,
                    delivery_by=o.delivery_by,
                    delivery_label=o.delivery_label,
                    urgent=int(o.urgent),
                    ppl_net=o.ppl_net,
                    total_inc_vat=o.total_inc_vat,
                    fees_inc_vat=o.fees_inc_vat,
                    ppl_effective=effective_ppl(o.total_inc_vat, o.litres),
                    ok=1,
                )
            )
    async with sf() as session:
        session.add_all(rows)
        await session.commit()
    return len(rows)


async def save_index(
    sf: async_sessionmaker, fetched_at: str, ppl: float | None, source: str
) -> None:
    """Record a national index reading (ok=0 when the scrape gave nothing)."""
    row = PriceQuote(
        fetched_at=fetched_at,
        supplier=source,
        kind="index",
        litres=0,
        urgent=0,
        fees_inc_vat=0.0,
        ppl_effective=ppl,
        ok=0 if ppl is None else 1,
        error="no price" if ppl is None else None,
    )
    async with sf() as session:
        session.add(row)
        await session.commit()


async def latest_poll(sf: async_sessionmaker) -> list[PriceQuote]:
    """All quote rows sharing the newest quote fetched_at."""
    async with sf() as session:
        newest = (
            await session.execute(
                select(func.max(PriceQuote.fetched_at)).where(PriceQuote.kind == "quote")
            )
        ).scalar()
        if newest is None:
            return []
        res = await session.execute(
            select(PriceQuote)
            .where(PriceQuote.kind == "quote", PriceQuote.fetched_at == newest)
            .order_by(PriceQuote.id)
        )
        return list(res.scalars().all())


async def latest_per_supplier(
    sf: async_sessionmaker, *, now: datetime, max_age_h: int = 36
) -> list[PriceQuote]:
    """Each supplier's newest quote poll within `max_age_h` of `now`.

    Suppliers poll at different times (some once a day), so "the latest
    poll" is per supplier. A supplier's newest poll with an ok row wins; a
    supplier with only failures in the window gives its newest failed poll,
    so the error is still visible. Falls back to the overall latest poll
    when nothing is inside the window.
    """
    cutoff = (now - timedelta(hours=max_age_h)).strftime(_FMT)
    async with sf() as session:
        res = await session.execute(
            select(PriceQuote)
            .where(PriceQuote.kind == "quote", PriceQuote.fetched_at >= cutoff)
            .order_by(PriceQuote.id)
        )
        rows = list(res.scalars().all())
    if not rows:
        return await latest_poll(sf)
    newest_ok: dict[str, str] = {}
    newest_any: dict[str, str] = {}
    for r in rows:
        if r.fetched_at > newest_any.get(r.supplier, ""):
            newest_any[r.supplier] = r.fetched_at
        if r.ok == 1 and r.fetched_at > newest_ok.get(r.supplier, ""):
            newest_ok[r.supplier] = r.fetched_at
    pick = {s: newest_ok.get(s, at) for s, at in newest_any.items()}
    return [r for r in rows if r.fetched_at == pick[r.supplier]]


async def best_recent(
    sf: async_sessionmaker,
    *,
    now: datetime,
    max_age_h: int = 36,
    until: datetime | None = None,
) -> PriceQuote | None:
    """Cheapest ok, non urgent quote fetched within `max_age_h` of `now`.

    `until`, when given, also caps `fetched_at` (inclusive) so a past window
    can be queried; None leaves the window open ended.
    """
    cutoff = (now - timedelta(hours=max_age_h)).strftime(_FMT)
    conditions = [
        PriceQuote.kind == "quote",
        PriceQuote.ok == 1,
        PriceQuote.urgent == 0,
        PriceQuote.ppl_effective.is_not(None),
        PriceQuote.fetched_at >= cutoff,
    ]
    if until is not None:
        conditions.append(PriceQuote.fetched_at <= until.strftime(_FMT))
    async with sf() as session:
        res = await session.execute(
            select(PriceQuote)
            .where(*conditions)
            .order_by(PriceQuote.ppl_effective, PriceQuote.id)
            .limit(1)
        )
        return res.scalar_one_or_none()


async def history(sf: async_sessionmaker, *, since: datetime) -> list[PriceQuote]:
    """All rows (quotes and index) since `since`, oldest first."""
    async with sf() as session:
        res = await session.execute(
            select(PriceQuote)
            .where(PriceQuote.fetched_at >= since.strftime(_FMT))
            .order_by(PriceQuote.fetched_at, PriceQuote.id)
        )
        return list(res.scalars().all())
