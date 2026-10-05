"""Buying job: quotes, projection, signal, MQTT payload and alerts (Part D)."""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.buying.service import build_summary, run_buying
from kerotrack.models.buying_state import BuyingState
from kerotrack.models.hdd import HddDatum
from kerotrack.models.price_quote import PriceQuote
from kerotrack.models.reading import Reading
from kerotrack.quotes.store import save_index
from kerotrack.scheduler import jobs
from kerotrack.scheduler.service import _JOB_TO_SETTING

FIX = json.loads((pathlib.Path(__file__).parents[1] / "fixtures" / "hfd_quote.json").read_text())
HFD_URL = "https://homefuelsdirect.co.uk/index.php"
NOW = datetime(2026, 8, 31, 18, 0)
PAYLOAD_KEYS = {
    "state",
    "best_total",
    "best_supplier",
    "best_ppl_effective",
    "trigger_ppl",
    "headroom_l",
    "order_by",
    "run_out",
    "scenario",
    "fetched_at",
}


class FakePublisher:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def publish_buying(self, payload: dict[str, Any]) -> None:
        self.payloads.append(payload)


class FakeApprise:
    def __init__(self, sent: list[dict[str, Any]], ok: bool = True) -> None:
        self._sent = sent
        self._ok = ok

    def notify(self, *, body: str, title: str, body_format: Any = None) -> bool:
        if self._ok:
            self._sent.append({"title": title, "body": body})
        return self._ok


def _factory(sent: list[dict[str, Any]], ok: bool = True):
    return lambda urls: FakeApprise(sent, ok)


async def _seed_readings(sf: async_sessionmaker, now: datetime, ppl: float | None = None) -> None:
    """90 days falling 1 L/day from 600 to a latest 403 L; HDD 0."""
    first = now.date() - timedelta(days=90)
    async with sf() as session:
        for i in range(90):
            d = first + timedelta(days=i)
            session.add(
                Reading(
                    date=datetime(d.year, d.month, d.day, 12).strftime("%Y-%m-%d %H:%M:%S"),
                    id="probe",
                    litres_remaining=600.0 - i,
                    refill_detected="n",
                    leak_detected="n",
                    current_ppl=(ppl + i % 10) if ppl is not None else None,
                )
            )
            session.add(HddDatum(date=d.isoformat(), hdd=0.0))
        session.add(
            Reading(
                date=now.replace(hour=12, minute=0).strftime("%Y-%m-%d %H:%M:%S"),
                id="probe",
                litres_remaining=403.0,
                refill_detected="n",
                leak_detected="n",
            )
        )
        await session.commit()


async def _configure(svc, *, postcode: str = "ZZ99 9ZZ") -> None:
    await svc.set("buying.postcode", postcode)
    await svc.set("buying.trigger_ppl", 120.0)
    await svc.set("notifications.apprise_urls", ["tgram://123456:testtoken/42"])


@respx.mock
async def test_run_buying_writes_quotes_alerts_and_publishes(
    sf: async_sessionmaker, seeded_settings
) -> None:
    route = respx.get(HFD_URL).respond(json=FIX)
    await _seed_readings(sf, NOW)
    await _configure(seeded_settings)
    pub, sent = FakePublisher(), []

    summary = await run_buying(
        sf=sf,
        settings_service=seeded_settings,
        publisher=pub,
        now=NOW,
        apprise_factory=_factory(sent),
    )

    assert route.called
    async with sf() as session:
        n = (
            await session.execute(
                select(func.count()).select_from(PriceQuote).where(PriceQuote.kind == "quote")
            )
        ).scalar_one()
    assert n == 3
    assert summary["state"] == "buy_now"
    assert summary["best"]["supplier"] == "homefuelsdirect"
    assert summary["best"]["total_inc_vat"] == pytest.approx(551.25)
    assert summary["best"]["ppl_effective"] == pytest.approx(105.0)
    assert len(summary["quotes"]) == 3
    assert "normal" in summary["scenarios"]
    assert summary["active_scenario"] == "normal"
    assert len(sent) == 1
    assert sent[0]["title"] == "KeroTrack: Buy now"
    assert "homefuelsdirect" in sent[0]["body"]
    assert len(pub.payloads) == 1
    payload = pub.payloads[0]
    assert set(payload) == PAYLOAD_KEYS
    assert payload["state"] == "buy_now"
    assert payload["best_total"] == pytest.approx(551.25)
    assert payload["best_ppl_effective"] == pytest.approx(105.0)
    assert payload["trigger_ppl"] == 120.0
    assert payload["headroom_l"] == pytest.approx(1225.0 * 0.95 - 403.0, abs=0.1)
    assert payload["scenario"] == "normal"
    async with sf() as session:
        row = (await session.execute(select(BuyingState))).scalar_one()
    assert row.state == "buy_now" and row.last_alerted_state == "buy_now"


@respx.mock
async def test_second_run_same_state_does_not_realert(
    sf: async_sessionmaker, seeded_settings
) -> None:
    respx.get(HFD_URL).respond(json=FIX)
    await _seed_readings(sf, NOW)
    await _configure(seeded_settings)
    sent: list[dict[str, Any]] = []
    await run_buying(
        sf=sf,
        settings_service=seeded_settings,
        publisher=FakePublisher(),
        now=NOW,
        apprise_factory=_factory(sent),
    )
    # Fresh call, as after a restart: state must come from the DB.
    pub2 = FakePublisher()
    summary = await run_buying(
        sf=sf,
        settings_service=seeded_settings,
        publisher=pub2,
        now=NOW + timedelta(hours=6),
        apprise_factory=_factory(sent),
    )
    assert summary["state"] == "buy_now"
    assert len(sent) == 1
    assert pub2.payloads[0]["state"] == "buy_now"


async def _run(sf, svc, now, sent, ok=True):
    return await run_buying(
        sf=sf,
        settings_service=svc,
        publisher=FakePublisher(),
        now=now,
        apprise_factory=_factory(sent, ok),
    )


async def _state_row(sf) -> BuyingState:
    async with sf() as session:
        return (await session.execute(select(BuyingState))).scalar_one()


@respx.mock
async def test_failed_send_is_retried_on_next_run(sf: async_sessionmaker, seeded_settings) -> None:
    respx.get(HFD_URL).respond(json=FIX)
    await _seed_readings(sf, NOW)
    await _configure(seeded_settings)
    sent: list[dict[str, Any]] = []

    first = await _run(sf, seeded_settings, NOW, sent, ok=False)
    assert first["state"] == "buy_now"
    assert sent == []
    row = await _state_row(sf)
    assert row.state == "buy_now" and row.last_alerted_state is None

    await _run(sf, seeded_settings, NOW + timedelta(hours=6), sent)
    assert len(sent) == 1
    assert (await _state_row(sf)).last_alerted_state == "buy_now"

    await _run(sf, seeded_settings, NOW + timedelta(hours=12), sent)
    assert len(sent) == 1


@respx.mock
async def test_leaving_and_reentering_alert_state_alerts_again(
    sf: async_sessionmaker, seeded_settings
) -> None:
    respx.get(HFD_URL).respond(json=FIX)
    await _seed_readings(sf, NOW)
    await _configure(seeded_settings)
    sent: list[dict[str, Any]] = []

    assert (await _run(sf, seeded_settings, NOW, sent))["state"] == "buy_now"
    await seeded_settings.set("buying.trigger_ppl", 100.0)
    assert (await _run(sf, seeded_settings, NOW + timedelta(hours=6), sent))["state"] == "wait"
    assert (await _state_row(sf)).last_alerted_state is None
    await seeded_settings.set("buying.trigger_ppl", 120.0)
    assert (await _run(sf, seeded_settings, NOW + timedelta(hours=12), sent))["state"] == "buy_now"
    assert len(sent) == 2


async def test_no_urls_counts_as_not_sent(sf: async_sessionmaker, seeded_settings) -> None:
    await _seed_readings(sf, NOW)
    await _configure(seeded_settings, postcode="")
    await seeded_settings.set("notifications.apprise_urls", [])
    async with sf() as session:
        session.add(
            PriceQuote(
                fetched_at=NOW.strftime("%Y-%m-%d %H:%M:%S"),
                supplier="homefuelsdirect",
                kind="quote",
                litres=500,
                urgent=0,
                total_inc_vat=551.25,
                fees_inc_vat=0.0,
                ppl_effective=105.0,
                ok=1,
            )
        )
        await session.commit()
    summary = await _run(sf, seeded_settings, NOW, [])
    assert summary["state"] == "buy_now"
    assert (await _state_row(sf)).last_alerted_state is None


@respx.mock(assert_all_called=False)
async def test_empty_postcode_makes_no_http_call(
    respx_mock, sf: async_sessionmaker, seeded_settings
) -> None:
    route = respx_mock.get(HFD_URL).respond(json=FIX)
    await _seed_readings(sf, NOW)
    await _configure(seeded_settings, postcode="")
    sent: list[dict[str, Any]] = []
    pub = FakePublisher()

    summary = await run_buying(
        sf=sf,
        settings_service=seeded_settings,
        publisher=pub,
        now=NOW,
        apprise_factory=_factory(sent),
    )

    assert not route.called
    assert summary["state"] in {"wait", "unknown"}
    assert summary["best"] is None
    assert sent == []
    assert pub.payloads[0]["best_total"] is None


@respx.mock(assert_all_called=False)
async def test_prices_refresh_saves_index_and_gives_wait(
    respx_mock, sf: async_sessionmaker, seeded_settings
) -> None:
    respx_mock.get(HFD_URL).respond(json=FIX)
    await _seed_readings(sf, NOW, ppl=100.0)
    await _configure(seeded_settings, postcode="")

    class FakePrices:
        async def refresh(self):
            return SimpleNamespace(boilerjuice_ppl=104.5)

    summary = await run_buying(
        sf=sf,
        settings_service=seeded_settings,
        publisher=FakePublisher(),
        prices=FakePrices(),
        now=NOW,
        apprise_factory=_factory([]),
    )
    assert summary["state"] == "wait"
    # current_ppl seeded as 100..109 repeating; 104.5 sits above 100..104.
    assert summary["context"]["index_percentile_365d"] == 50


async def test_build_summary_without_data(sf: async_sessionmaker, seeded_settings) -> None:
    summary = await build_summary(sf, seeded_settings, now=NOW)
    assert summary["best"] is None
    assert summary["quotes"] == []
    assert summary["scenarios"] == {}
    assert summary["context"]["index_percentile_365d"] is None
    assert summary["context"]["best_change_30d"] is None
    assert summary["context"]["spread_today"] is None


async def test_build_summary_index_percentile_uses_latest_index(
    sf: async_sessionmaker, seeded_settings
) -> None:
    await _seed_readings(sf, NOW, ppl=100.0)
    await save_index(sf, "2026-08-30 07:00:00", 200.0, "boilerjuice")
    await save_index(sf, "2026-08-31 07:00:00", 101.5, "boilerjuice")
    await save_index(sf, "2026-08-31 13:00:00", None, "boilerjuice")
    summary = await build_summary(sf, seeded_settings, now=NOW)
    # 100 and 101 of each 100..109 cycle are <= 101.5.
    assert summary["context"]["index_percentile_365d"] == 20


def test_scheduler_maps_buying_job() -> None:
    assert "buying" in jobs.JOB_NAMES
    assert _JOB_TO_SETTING["buying"] == "schedule.buying_cron"


async def test_run_job_dispatches_buying(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_run_buying(**kwargs):
        calls.append(kwargs)
        return {"state": "wait"}

    monkeypatch.setattr(jobs, "run_buying", fake_run_buying)
    state = SimpleNamespace(
        session_factory="sf", settings_service="svc", publisher="pub", prices="prices"
    )
    assert await jobs.run_job("buying", app_state=state) == {"state": "wait"}
    assert calls == [
        {"sf": "sf", "settings_service": "svc", "publisher": "pub", "prices": "prices"}
    ]


def _quote(fetched: datetime, ppl_eff: float) -> PriceQuote:
    return PriceQuote(
        fetched_at=fetched.strftime("%Y-%m-%d %H:%M:%S"),
        supplier="homefuelsdirect",
        kind="quote",
        litres=500,
        urgent=0,
        total_inc_vat=round(ppl_eff * 1.05 * 5, 2),
        fees_inc_vat=0.0,
        ppl_effective=ppl_eff,
        ok=1,
    )


async def _add(sf, *rows) -> None:
    async with sf() as session:
        session.add_all(rows)
        await session.commit()


async def test_best_change_30d_positive_when_dearer_today(
    sf: async_sessionmaker, seeded_settings
) -> None:
    await _add(sf, _quote(NOW - timedelta(days=30, hours=6), 100.0), _quote(NOW, 105.0))
    summary = await build_summary(sf, seeded_settings, now=NOW)
    assert summary["context"]["best_change_30d"] == pytest.approx(5.0)


async def test_best_change_30d_negative_when_cheaper_today(
    sf: async_sessionmaker, seeded_settings
) -> None:
    await _add(sf, _quote(NOW - timedelta(days=30, hours=6), 110.0), _quote(NOW, 105.0))
    summary = await build_summary(sf, seeded_settings, now=NOW)
    assert summary["context"]["best_change_30d"] == pytest.approx(-5.0)


async def test_best_change_30d_none_without_month_ago_quote(
    sf: async_sessionmaker, seeded_settings
) -> None:
    # Only quotes from the last few days: nothing in the 30 day window.
    await _add(sf, _quote(NOW - timedelta(days=3), 99.0), _quote(NOW, 105.0))
    summary = await build_summary(sf, seeded_settings, now=NOW)
    assert summary["context"]["best_change_30d"] is None


@respx.mock(assert_all_called=False)
async def test_transient_unknown_does_not_cause_duplicate_alert(
    respx_mock, sf: async_sessionmaker, seeded_settings
) -> None:
    respx_mock.get(HFD_URL).respond(json=FIX)
    await _seed_readings(sf, NOW)
    await _configure(seeded_settings)
    sent: list[dict[str, Any]] = []

    assert (await _run(sf, seeded_settings, NOW, sent))["state"] == "buy_now"
    # Quotes go stale and the poll is skipped: no best, no index.
    await seeded_settings.set("buying.postcode", "")
    later = NOW + timedelta(hours=48)
    assert (await _run(sf, seeded_settings, later, sent))["state"] == "unknown"
    assert (await _state_row(sf)).last_alerted_state == "buy_now"
    await seeded_settings.set("buying.postcode", "ZZ99 9ZZ")
    assert (await _run(sf, seeded_settings, later + timedelta(hours=6), sent))["state"] == "buy_now"
    assert len(sent) == 1


async def test_trigger_read_failure_publishes_none(
    sf: async_sessionmaker, seeded_settings, monkeypatch
) -> None:
    await _seed_readings(sf, NOW)
    await _configure(seeded_settings, postcode="")
    real_get = seeded_settings.get

    async def failing_get(key: str):
        if key == "buying.trigger_ppl":
            raise RuntimeError("boom")
        return await real_get(key)

    monkeypatch.setattr(seeded_settings, "get", failing_get)
    pub = FakePublisher()
    await run_buying(sf=sf, settings_service=seeded_settings, publisher=pub, now=NOW)
    assert pub.payloads[0]["trigger_ppl"] is None


async def test_best_comes_from_the_latest_poll_not_the_36h_window(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """07:00 was cheap, 13:00 is dearer: the 13:00 price is the best now."""
    await _seed_readings(sf, NOW)
    await _configure(seeded_settings, postcode="")
    morning = NOW.replace(hour=7)
    afternoon = NOW.replace(hour=13)
    await _add(sf, _quote(morning, 110.0), _quote(afternoon, 125.0))
    sent: list[dict[str, Any]] = []
    pub = FakePublisher()

    summary = await run_buying(
        sf=sf,
        settings_service=seeded_settings,
        publisher=pub,
        now=NOW,
        apprise_factory=_factory(sent),
    )

    assert summary["best"]["ppl_effective"] == pytest.approx(125.0)
    assert summary["best"]["fetched_at"] == afternoon.strftime("%Y-%m-%d %H:%M:%S")
    assert pub.payloads[0]["best_ppl_effective"] == pytest.approx(125.0)
    assert pub.payloads[0]["fetched_at"] == afternoon.strftime("%Y-%m-%d %H:%M:%S")
    assert summary["state"] != "buy_now"
    assert sent == []


async def test_latest_poll_older_than_36h_gives_no_best(
    sf: async_sessionmaker, seeded_settings
) -> None:
    await _add(sf, _quote(NOW - timedelta(hours=40), 105.0))
    summary = await build_summary(sf, seeded_settings, now=NOW)
    assert summary["best"] is None


async def test_latest_poll_best_skips_urgent_and_failed_rows(
    sf: async_sessionmaker, seeded_settings
) -> None:
    urgent = _quote(NOW, 90.0)
    urgent.urgent = 1
    failed = _quote(NOW, 80.0)
    failed.ok = 0
    await _add(sf, urgent, failed, _quote(NOW, 105.0), _quote(NOW, 107.0))
    summary = await build_summary(sf, seeded_settings, now=NOW)
    assert summary["best"]["ppl_effective"] == pytest.approx(105.0)


async def test_undelivered_alert_warns_only_on_entering_the_state(
    sf: async_sessionmaker, seeded_settings, caplog
) -> None:
    import logging

    await _seed_readings(sf, NOW)
    await _configure(seeded_settings, postcode="")
    await seeded_settings.set("notifications.apprise_urls", [])
    await _add(sf, _quote(NOW, 105.0))
    caplog.set_level(logging.INFO, logger="kerotrack.buying.service")

    def undelivered(level: int) -> list[logging.LogRecord]:
        return [
            r
            for r in caplog.records
            if r.name == "kerotrack.buying.service"
            and "not delivered" in r.getMessage()
            and r.levelno == level
        ]

    assert (await _run(sf, seeded_settings, NOW, []))["state"] == "buy_now"
    assert len(undelivered(logging.WARNING)) == 1
    caplog.clear()
    await _run(sf, seeded_settings, NOW + timedelta(hours=1), [])
    assert undelivered(logging.WARNING) == []
    assert len(undelivered(logging.INFO)) == 1


async def test_summary_reports_hdd_model_without_nest_data(
    sf: async_sessionmaker, seeded_settings
) -> None:
    summary = await build_summary(sf, seeded_settings, now=NOW)
    assert summary["heating_model"] == "hdd"
    assert summary["l_per_heating_hour"] is None

    await _seed_readings(sf, NOW)
    await _configure(seeded_settings, postcode="")
    summary = await run_buying(
        sf=sf, settings_service=seeded_settings, publisher=FakePublisher(), now=NOW
    )
    assert summary["heating_model"] == "hdd"
    assert summary["l_per_heating_hour"] is None
    assert summary["k"] is not None


async def test_summary_reports_nest_model_when_active(
    sf: async_sessionmaker, seeded_settings
) -> None:
    from tests.unit.test_projection_service import NEST_A, _seed_nest

    now = datetime(2026, 10, 4, 18, 0)
    await _seed_nest(sf, seeded_settings, now, months=24)
    await _configure(seeded_settings, postcode="")
    publisher = FakePublisher()
    summary = await run_buying(
        sf=sf, settings_service=seeded_settings, publisher=publisher, now=now
    )
    assert summary["heating_model"] == "nest"
    assert summary["l_per_heating_hour"] == pytest.approx(NEST_A, abs=0.02)
    # The HDD k is still reported (and persisted) for the HDD model.
    assert summary["k"] is not None
    # The retained MQTT payload keeps its contract.
    assert set(publisher.payloads[-1]) == PAYLOAD_KEYS
    # build_summary reads the persisted model back.
    again = await build_summary(sf, seeded_settings, now=now)
    assert again["heating_model"] == "nest"
    assert again["l_per_heating_hour"] == summary["l_per_heating_hour"]
