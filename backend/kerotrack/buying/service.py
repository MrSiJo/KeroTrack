"""Daily buying job (spec Part D).

``run_buying`` refreshes the inputs (daily HDD, supplier quotes, the national
index, the runway projection), computes the buy signal, alerts through
Apprise on a transition into an alert state, publishes the retained
``oiltank/buying`` MQTT topic and returns the summary. Each step is isolated
so one failure doesn't stop the rest.

``build_summary`` reads persisted tables only and backs the API.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.analysis.hdd_rollup import aggregate_daily_hdd
from kerotrack.buying.signal import ALERT_STATES, SignalInputs, compute_state
from kerotrack.clock import local_now
from kerotrack.models.buying_state import BuyingState
from kerotrack.models.price_quote import PriceQuote
from kerotrack.models.reading import Reading, trusted_readings_clause
from kerotrack.models.runway_projection import RunwayProjection
from kerotrack.notifier.send import send
from kerotrack.projection.service import NORMAL, persist_projection, project
from kerotrack.quotes.models import QuoteRequest, all_in_ppl
from kerotrack.quotes.registry import poll, select_providers
from kerotrack.quotes.store import best_recent, latest_per_supplier, save_index, save_poll
from kerotrack.settings.service import SettingsService

logger = logging.getLogger(__name__)

_FMT = "%Y-%m-%d %H:%M:%S"
STATE_ROW_ID = 1
FRESH_HOURS = 36
ALERT_LABELS = {"buy_now": "Buy now", "deadline": "Order soon", "overdue": "Order overdue"}
_QUOTE_FIELDS = (
    "id",
    "fetched_at",
    "supplier",
    "kind",
    "litres",
    "delivery_by",
    "delivery_label",
    "urgent",
    "ppl_net",
    "total_inc_vat",
    "fees_inc_vat",
    "ppl_effective",
    "ok",
    "error",
)


def _round(value: float | None, digits: int) -> float | None:
    return round(value, digits) if value is not None else None


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d is not None else None


async def _trigger_ppl(svc: SettingsService) -> float | None:
    try:
        return float(await svc.get("buying.trigger_ppl"))
    except Exception:  # noqa: BLE001
        logger.exception("buying: could not read buying.trigger_ppl")
        return None


async def _latest_litres(sf: async_sessionmaker) -> float | None:
    async with sf() as session:
        value = (
            await session.execute(
                select(Reading.litres_remaining)
                .where(trusted_readings_clause(), Reading.litres_remaining.is_not(None))
                .order_by(desc(Reading.date))
                .limit(1)
            )
        ).scalar_one_or_none()
    return float(value) if value is not None else None


async def _headroom(sf: async_sessionmaker, svc: SettingsService) -> float | None:
    litres = await _latest_litres(sf)
    if litres is None:
        return None
    capacity = float(await svc.get("tank.capacity_l"))
    safe = float(await svc.get("buying.safe_fill_pct"))
    return capacity * safe - litres


async def _latest_index(sf: async_sessionmaker) -> PriceQuote | None:
    async with sf() as session:
        return (
            await session.execute(
                select(PriceQuote)
                .where(PriceQuote.kind == "index", PriceQuote.ok == 1)
                .order_by(desc(PriceQuote.fetched_at), desc(PriceQuote.id))
                .limit(1)
            )
        ).scalar_one_or_none()


def _index_ppl(row: PriceQuote | None) -> float | None:
    # save_index stores the reading in ppl_effective; prefer ppl_net if set.
    if row is None:
        return None
    return row.ppl_net if row.ppl_net is not None else row.ppl_effective


async def _has_fresh_index(sf: async_sessionmaker, now: datetime) -> bool:
    row = await _latest_index(sf)
    if row is None or _index_ppl(row) is None:
        return False
    return row.fetched_at >= (now - timedelta(hours=FRESH_HOURS)).strftime(_FMT)


def _best_of_poll(rows: list[PriceQuote], now: datetime) -> PriceQuote | None:
    """Cheapest ok, non urgent quote among `rows`.

    `rows` are each supplier's latest poll (``latest_per_supplier``), so a
    cheaper once a day quote is not hidden by a later poll of another
    supplier. Quotes older than ``FRESH_HOURS`` are ignored; with none left
    the signal falls back to the index or ``unknown``.
    """
    cutoff = (now - timedelta(hours=FRESH_HOURS)).strftime(_FMT)
    candidates = [
        r
        for r in rows
        if r.ok == 1
        and not r.urgent
        and r.ppl_effective is not None
        and r.total_inc_vat is not None
        and r.fetched_at >= cutoff
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda r: (r.total_inc_vat, r.id))


async def _best_latest(sf: async_sessionmaker, now: datetime) -> PriceQuote | None:
    return _best_of_poll(await latest_per_supplier(sf, now=now, max_age_h=FRESH_HOURS), now)


def _row_all_in(row: PriceQuote | None) -> float | None:
    """All in pence per litre for a stored quote row, or None."""
    if row is None or row.total_inc_vat is None or not row.litres:
        return None
    return all_in_ppl(row.total_inc_vat, row.litres)


def _alert_body(payload: dict[str, Any]) -> str:
    def money(v: float | None) -> str:
        return f"£{v:.2f}" if v is not None else "n/a"

    def ppl(v: float | None) -> str:
        return f"{v:.2f}p" if v is not None else "n/a"

    headroom = payload["headroom_l"]
    return "\n".join(
        [
            f"**Best supplier:** {payload['best_supplier'] or 'none'}",
            f"**Total (inc VAT):** {money(payload['best_total'])}",
            f"**Price per litre:** {ppl(payload['best_ppl'])} (VAT, delivery and fees included)",
            f"**Order by:** {payload['order_by'] or 'n/a'}",
            f"**Headroom:** {f'{headroom:.0f} L' if headroom is not None else 'n/a'}",
        ]
    )


async def run_buying(
    *,
    sf: async_sessionmaker,
    settings_service: SettingsService,
    publisher: Any,
    prices: Any = None,
    http_client: httpx.AsyncClient | None = None,
    now: datetime | None = None,
    apprise_factory: Any = None,
    cadence: str | None = None,
) -> dict:
    """Run the buying job once and return the summary.

    `cadence` limits the quote poll to providers of that cadence
    ("frequent" or "daily"); None polls every configured provider.
    """
    svc = settings_service
    now = now or local_now()
    now_str = now.strftime(_FMT)

    # 1. Daily HDD, so the projection's calibration sees today's values.
    try:
        await aggregate_daily_hdd(sf)
    except Exception:  # noqa: BLE001
        logger.exception("buying: HDD roll-up failed")

    # 2. Supplier quotes. The postcode is never logged.
    try:
        postcode = str(await svc.get("buying.postcode") or "").strip()
        if postcode:
            logger.info("buying: postcode set; polling supplier quotes")
            litres = int(await svc.get("buying.order_litres"))
            tanker = str(await svc.get("buying.tanker"))
            providers = await svc.get("buying.providers")
            names = [str(p) for p in providers] if isinstance(providers, list) else []
            names = select_providers(names, cadence)
            pattern = str(await svc.get("buying.quote_email_pattern") or "")
            req = QuoteRequest(postcode, litres, tanker)
            if names:
                if http_client is not None:
                    results = await poll(http_client, req, names, email_pattern=pattern)
                else:
                    async with httpx.AsyncClient() as client:
                        results = await poll(client, req, names, email_pattern=pattern)
                await save_poll(sf, now_str, litres, results)
        else:
            logger.info("buying: postcode empty; skipping supplier quotes")
    except Exception:  # noqa: BLE001
        logger.exception("buying: supplier quote poll failed")

    # 3. National index.
    if prices is not None:
        try:
            result = await prices.refresh()
            await save_index(sf, now_str, result.boilerjuice_ppl, "boilerjuice")
        except Exception:  # noqa: BLE001
            logger.exception("buying: index refresh failed")

    # 4. Runway projection.
    bundle = None
    try:
        bundle = await project(sf, svc, now=now)
        if bundle is not None:
            await persist_projection(sf, bundle)
    except Exception:  # noqa: BLE001
        logger.exception("buying: projection failed")

    # 5. Signal.
    state = "unknown"
    best: PriceQuote | None = None
    headroom: float | None = None
    trigger = await _trigger_ppl(svc)
    order_by: date | None = None
    run_out: date | None = None
    scenario = NORMAL
    try:
        headroom = await _headroom(sf, svc)
        best = await _best_latest(sf, now)
        if bundle is not None:
            scenario = bundle.active_scenario
            outcome = bundle.outcomes.get(scenario) or bundle.outcomes.get(NORMAL)
            if outcome is not None:
                order_by, run_out = outcome.order_by, outcome.run_out
        else:
            scenario = str(await svc.get("projection.active_scenario") or NORMAL)
        if headroom is not None:
            state = compute_state(
                SignalInputs(
                    today=now.date(),
                    headroom_l=headroom,
                    min_order_l=float(await svc.get("buying.min_order_litres")),
                    order_by=order_by,
                    warn_days=int(await svc.get("buying.warn_days")),
                    trigger_ppl=trigger if trigger is not None else 0.0,
                    best_ppl=_row_all_in(best),
                    has_index=await _has_fresh_index(sf, now),
                )
            )
    except Exception:  # noqa: BLE001
        logger.exception("buying: signal computation failed")

    payload: dict[str, Any] = {
        "state": state,
        "best_total": _round(best.total_inc_vat, 2) if best is not None else None,
        "best_supplier": best.supplier if best is not None else None,
        # All in (VAT, delivery, fees): the trigger's basis.
        "best_ppl": _round(_row_all_in(best), 2),
        # Ex VAT, kept for existing MQTT consumers.
        "best_ppl_effective": _round(best.ppl_effective, 2) if best is not None else None,
        "trigger_ppl": trigger,
        "headroom_l": _round(headroom, 1),
        "order_by": _iso(order_by),
        "run_out": _iso(run_out),
        "scenario": scenario,
        "fetched_at": best.fetched_at if best is not None else None,
    }

    # 6. Persist the state and alert when entering an alert state that has
    # not been successfully alerted yet. A failed or unconfigured send stays
    # retryable; leaving the alert states clears the memory so re-entry
    # alerts again.
    try:
        async with sf() as session:
            row = await session.get(BuyingState, STATE_ROW_ID)
            previous_state = row.state if row is not None else None
            if row is None:
                row = BuyingState(id=STATE_ROW_ID, state=state, updated_at=now_str)
                session.add(row)
            row.state = state
            row.updated_at = now_str
            row.summary_json = json.dumps(payload)
            if bundle is not None:
                row.heating_model = bundle.heating_model
                row.l_per_heating_hour = bundle.l_per_heating_hour
            # "unknown" is usually a transient failure (no fresh data), so
            # it keeps the memory: the next good run must not re-alert.
            if state not in ALERT_STATES and state != "unknown":
                row.last_alerted_state = None
            already_alerted = row.last_alerted_state
            await session.commit()
        if state in ALERT_STATES and already_alerted != state:
            sent = False
            try:
                urls = await svc.get("notifications.apprise_urls") or []
                sent = await send(
                    list(urls),
                    f"KeroTrack: {ALERT_LABELS[state]}",
                    _alert_body(payload),
                    apprise_factory=apprise_factory,
                )
            except Exception:  # noqa: BLE001
                logger.exception("buying: alert send failed")
            if sent:
                async with sf() as session:
                    row = await session.get(BuyingState, STATE_ROW_ID)
                    if row is not None:
                        row.last_alerted_state = state
                        await session.commit()
                logger.info("buying: alert sent for state %s", state)
            else:
                # Warn once on entering the state; the retries that follow
                # (e.g. no Apprise URLs configured) log at INFO.
                log = logger.warning if previous_state != state else logger.info
                log("buying: alert for state %s not delivered; will retry", state)
    except Exception:  # noqa: BLE001
        logger.exception("buying: state persistence failed")

    # 7. Retained MQTT topic.
    if publisher is not None:
        try:
            await publisher.publish_buying(payload)
        except Exception:  # noqa: BLE001
            logger.exception("buying: MQTT publish failed")

    # 8. Summary from the persisted tables.
    return await build_summary(sf, svc, now=now)


async def _index_percentile(
    sf: async_sessionmaker, index_ppl: float | None, now: datetime
) -> int | None:
    if index_ppl is None:
        return None
    since = (now - timedelta(days=365)).strftime(_FMT)
    base = (Reading.current_ppl > 0, Reading.date >= since)
    async with sf() as session:
        total = (
            await session.execute(select(func.count()).select_from(Reading).where(*base))
        ).scalar_one()
        if not total:
            return None
        at_or_below = (
            await session.execute(
                select(func.count())
                .select_from(Reading)
                .where(*base, Reading.current_ppl <= index_ppl)
            )
        ).scalar_one()
    return round(at_or_below / total * 100)


def _spread_today(rows: list[PriceQuote], now: datetime) -> float | None:
    """Gap in all in ppl between the cheapest and dearest supplier today."""
    today = now.strftime("%Y-%m-%d")
    per_supplier: dict[str, float] = {}
    for r in rows:
        value = _row_all_in(r)
        if r.ok != 1 or r.urgent or value is None or not r.fetched_at.startswith(today):
            continue
        cur = per_supplier.get(r.supplier)
        per_supplier[r.supplier] = value if cur is None else min(cur, value)
    if len(per_supplier) < 2:
        return None
    return round(max(per_supplier.values()) - min(per_supplier.values()), 2)


def _quote_dict(row: PriceQuote) -> dict[str, Any]:
    return {name: getattr(row, name) for name in _QUOTE_FIELDS}


async def build_summary(sf: async_sessionmaker, svc: SettingsService, *, now: datetime) -> dict:
    """Assemble the buying summary from persisted rows (no network calls)."""
    async with sf() as session:
        state_row = await session.get(BuyingState, STATE_ROW_ID)
        latest_run = (
            await session.execute(select(func.max(RunwayProjection.run_at)))
        ).scalar()
        projections: list[RunwayProjection] = []
        if latest_run is not None:
            projections = list(
                (
                    await session.execute(
                        select(RunwayProjection)
                        .where(RunwayProjection.run_at == latest_run)
                        .order_by(RunwayProjection.id)
                    )
                )
                .scalars()
                .all()
            )

    scenarios: dict[str, dict[str, Any]] = {}
    for p in projections:
        try:
            series = json.loads(p.series_json)
        except ValueError:
            series = []
        scenarios[p.scenario] = {
            "run_out": p.run_out_date,
            "order_by": p.order_by_date,
            "next_order_by": p.next_order_by_date,
            "series": series,
        }
    active = str(await svc.get("projection.active_scenario") or NORMAL)
    if scenarios and active not in scenarios:
        active = NORMAL

    quotes = await latest_per_supplier(sf, now=now, max_age_h=FRESH_HOURS)
    best = _best_of_poll(quotes, now)
    best_dict = (
        {
            "supplier": best.supplier,
            "total_inc_vat": best.total_inc_vat,
            "ppl": _round(_row_all_in(best), 2),
            "ppl_effective": _round(best.ppl_effective, 2),
            "delivery_label": best.delivery_label,
            "fetched_at": best.fetched_at,
        }
        if best is not None
        else None
    )

    # The 30 day change compares like with like: the 36 h window best now
    # against the same window a month ago.
    recent = await best_recent(sf, now=now, max_age_h=FRESH_HOURS)
    month_ago_at = now - timedelta(days=30)
    month_ago = await best_recent(
        sf, now=month_ago_at, max_age_h=FRESH_HOURS, until=month_ago_at
    )
    recent_ppl, month_ago_ppl = _row_all_in(recent), _row_all_in(month_ago)
    best_change = (
        round(recent_ppl - month_ago_ppl, 2)
        if recent_ppl is not None and month_ago_ppl is not None
        else None
    )

    headroom = await _headroom(sf, svc)
    return {
        "state": state_row.state if state_row is not None else "unknown",
        "updated_at": state_row.updated_at if state_row is not None else None,
        "trigger_ppl": await _trigger_ppl(svc),
        "headroom_l": _round(headroom, 1),
        "best": best_dict,
        "quotes": [_quote_dict(q) for q in quotes],
        "scenarios": scenarios,
        "active_scenario": active,
        "k": projections[0].k if projections else None,
        "hw_l_per_day": projections[0].hw_l_per_day if projections else None,
        "heating_model": (
            state_row.heating_model if state_row is not None and state_row.heating_model else "hdd"
        ),
        "l_per_heating_hour": _round(
            state_row.l_per_heating_hour
            if state_row is not None and state_row.heating_model == "nest"
            else None,
            3,
        ),
        "context": {
            "index_percentile_365d": await _index_percentile(
                sf, _index_ppl(await _latest_index(sf)), now
            ),
            "best_change_30d": best_change,
            "spread_today": _spread_today(quotes, now),
        },
    }
