"""Email requiring quote providers: The Heating Oil Company, NWF, Western Fuel,
BoilerJuice (fixtures recorded live 2026-10-05, then scrubbed)."""

from __future__ import annotations

import json
import pathlib
from datetime import date

import httpx
import pytest
import respx

from kerotrack.quotes.boilerjuice import BoilerJuice
from kerotrack.quotes.models import QuoteRequest, quote_email
from kerotrack.quotes.nwffuels import NwfFuels
from kerotrack.quotes.registry import NO_EMAIL, poll, select_providers
from kerotrack.quotes.theheatingoilcompany import TheHeatingOilCompany
from kerotrack.quotes.westernfuel import WesternFuel

FIXTURES = pathlib.Path(__file__).parents[1] / "fixtures"
THOC_HTML = (FIXTURES / "thoc_quote.html").read_text(encoding="utf-8")
BJ_HTML = (FIXTURES / "boilerjuice_quote.html").read_text(encoding="utf-8")
NWF_COSTS = json.loads((FIXTURES / "nwf_costs.json").read_text(encoding="utf-8"))
NWF_TIERS = json.loads((FIXTURES / "nwf_delivery_options.json").read_text(encoding="utf-8"))
WF_JSON = json.loads((FIXTURES / "westernfuel_quote.json").read_text(encoding="utf-8"))

PATTERN = "{site}@example.net"
REQ = QuoteRequest("ZZ99 9ZZ", 500, "standard")
EREQ = QuoteRequest("ZZ99 9ZZ", 500, "standard", email="x@example.net")
BJ_FORM = '<form><input type="hidden" name="authenticity_token" value="tok123" /></form>'


# --- helpers --------------------------------------------------------------


def test_quote_email_pattern() -> None:
    assert quote_email(PATTERN, "westernfuel") == "westernfuel@example.net"
    assert quote_email("", "westernfuel") is None
    assert quote_email("not-an-address", "westernfuel") is None


def test_select_providers_by_cadence() -> None:
    names = ["homefuelsdirect", "westernfuel", "nwffuels", "theheatingoilcompany", "boilerjuice"]
    assert select_providers(names, "frequent") == ["homefuelsdirect"]
    assert select_providers(names, "daily") == names[1:]
    assert select_providers(names, None) == names


# --- The Heating Oil Company --------------------------------------------


def test_thoc_parse_happy_path() -> None:
    opts = TheHeatingOilCompany().parse(THOC_HTML, 500)
    assert len(opts) == 1  # "Best Price" and "10 Day Delivery" are the same offer
    o = opts[0]
    assert o.total_inc_vat == 587.27 and o.ppl_net == 111.86
    assert o.delivery_by == "2026-10-20" and o.urgent is False
    assert o.delivery_label == "Standard"  # not the site's "Best Price" banner
    assert o.fees_inc_vat == pytest.approx(0.0, abs=0.02)


def test_thoc_parse_garbage() -> None:
    assert TheHeatingOilCompany().parse("<html><p>Sorry</p></html>", 500) == []
    assert TheHeatingOilCompany().parse("", 500) == []


@respx.mock
async def test_thoc_fetch_sends_email_and_params() -> None:
    route = respx.get(TheHeatingOilCompany.BASE_URL).respond(text=THOC_HTML)
    async with httpx.AsyncClient() as c:
        opts = await TheHeatingOilCompany().fetch(c, EREQ)
    p = route.calls.last.request.url.params
    assert p["email"] == "x@example.net" and p["location"] == "ZZ99 9ZZ"
    assert (p["qty"], p["productid"], p["vehicle"], p["heardfrom"]) == ("500", "10", "4", "15")
    assert route.calls.last.request.headers["User-Agent"].startswith("KeroTrack/2")
    assert len(opts) == 1


# --- NWF -----------------------------------------------------------------


def test_nwf_parse_tiers() -> None:
    opts = NwfFuels().parse(NWF_COSTS, NWF_TIERS, 500, today=date(2026, 10, 5))
    assert [o.delivery_label for o in opts] == ["Standard", "Value", "Express"]
    assert [o.urgent for o in opts] == [False, False, True]
    assert opts[0].total_inc_vat == 656.62 and opts[0].ppl_net == 125.07
    assert opts[0].delivery_by == "2026-10-12"
    # A tier charge is ex VAT and added on top.
    assert opts[2].fees_inc_vat == 21.0 and opts[2].total_inc_vat == 677.62


def test_nwf_parse_year_rolls_over() -> None:
    tiers = [{"name": "Standard", "cost": "0", "date": "Monday 4th January"}]
    opts = NwfFuels().parse(NWF_COSTS, tiers, 500, today=date(2026, 12, 29))
    assert opts[0].delivery_by == "2027-01-04"


def test_nwf_parse_without_tiers_gives_standard() -> None:
    opts = NwfFuels().parse(NWF_COSTS, "", 500, today=date(2026, 10, 5))
    assert len(opts) == 1 and opts[0].delivery_label == "Standard" and not opts[0].urgent


def test_nwf_parse_garbage() -> None:
    assert NwfFuels().parse("<html>", NWF_TIERS, 500) == []
    assert NwfFuels().parse({"products": [{"product_id": 999}]}, NWF_TIERS, 500) == []
    assert NwfFuels().parse(False, NWF_TIERS, 500) == []


@respx.mock
async def test_nwf_fetch_sends_email_and_never_opts_in() -> None:
    costs = respx.post(NwfFuels.COSTS_URL).respond(json=NWF_COSTS)
    ajax = respx.post(NwfFuels.AJAX_URL).respond(json=NWF_TIERS)
    async with httpx.AsyncClient() as c:
        opts = await NwfFuels().fetch(c, EREQ)
    body = json.loads(costs.calls.last.request.content)
    assert body["action"] == "get_costs"
    assert body["data"]["email"] == "x@example.net" and body["data"]["quantity"] == "500"
    assert all(b"opt_in" not in call.request.content for call in ajax.calls)
    assert len(opts) == 3


@respx.mock
async def test_nwf_fetch_survives_failed_tier_call() -> None:
    respx.post(NwfFuels.COSTS_URL).respond(json=NWF_COSTS)
    respx.post(NwfFuels.AJAX_URL).respond(status_code=500)
    async with httpx.AsyncClient() as c:
        opts = await NwfFuels().fetch(c, EREQ)
    assert len(opts) == 1 and opts[0].total_inc_vat == 656.62


# --- Western Fuel --------------------------------------------------------


def test_westernfuel_parse() -> None:
    opts = WesternFuel().parse(WF_JSON, 500)
    assert [(o.delivery_label, o.urgent) for o in opts] == [("Standard", False), ("Express", True)]
    assert opts[0].total_inc_vat == 560.26 and opts[0].fees_inc_vat == 12.0
    assert opts[0].ppl_net == 104.43 and opts[0].delivery_by == "2026-10-16"


def test_westernfuel_parse_garbage() -> None:
    assert WesternFuel().parse({"ok": False, "tiers": []}, 500) == []
    assert WesternFuel().parse({"ok": True, "tiers": [{"name": "x"}]}, 500) == []
    assert WesternFuel().parse("<html>", 500) == []


@respx.mock
async def test_westernfuel_fetch_body() -> None:
    route = respx.post(WesternFuel.QUOTE_URL).respond(json=WF_JSON)
    async with httpx.AsyncClient() as c:
        await WesternFuel().fetch(c, EREQ)
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "litres": 500,
        "fuelType": "Kero",
        "tankerType": "Standard",
        "postcode": "ZZ99 9ZZ",
        "email": "x@example.net",
    }


# --- BoilerJuice ---------------------------------------------------------


def test_boilerjuice_parse() -> None:
    opts = BoilerJuice().parse(BJ_HTML, 500)
    by_date = {o.delivery_by: o for o in opts}
    assert len(opts) == len(by_date) == 5  # the recommended card duplicates one option
    std = by_date["2026-10-19"]
    assert std.delivery_label == "Standard" and not std.urgent and std.total_inc_vat == 587.49
    assert std.fees_inc_vat == pytest.approx(12.98, abs=0.02)
    assert by_date["2026-10-06"].urgent and by_date["2026-10-07"].urgent
    assert not by_date["2026-10-08"].urgent
    assert by_date["2026-10-08"].delivery_label == "Within 3 working days"


def test_boilerjuice_parse_garbage() -> None:
    assert BoilerJuice().parse("<html><div data-price='x'></div></html>", 500) == []
    assert BoilerJuice().parse("", 500) == []


@respx.mock
async def test_boilerjuice_journey_posts_token_and_opts_out() -> None:
    respx.get(BoilerJuice.FORM_URL).respond(text=BJ_FORM)
    post = respx.post(BoilerJuice.QUOTE_URL).respond(
        status_code=302, headers={"location": BoilerJuice.QUOTE_URL}
    )
    respx.get(BoilerJuice.QUOTE_URL).respond(text=BJ_HTML)
    async with httpx.AsyncClient() as c:
        opts = await BoilerJuice().fetch(c, EREQ)
    form = dict(httpx.QueryParams(post.calls.last.request.content.decode()))
    assert form["authenticity_token"] == "tok123"
    assert form["email"] == "x@example.net" and form["opt_out_email"] == "1"
    assert form["volume"] == "500" and form["theTanker"] == "Standard Tanker"
    assert len(opts) == 5


@respx.mock
async def test_boilerjuice_missing_token_is_an_error() -> None:
    respx.get(BoilerJuice.FORM_URL).respond(text="<html></html>")
    async with httpx.AsyncClient() as c:
        res = await poll(c, REQ, ["boilerjuice"], email_pattern=PATTERN)
    assert res[0].options == [] and "token" in res[0].error


# --- registry ------------------------------------------------------------


async def test_poll_without_email_skips_email_providers() -> None:
    async with httpx.AsyncClient() as c:
        res = await poll(c, REQ, ["westernfuel", "nwffuels"], email_pattern="")
    assert [(r.supplier, r.error) for r in res] == [
        ("westernfuel", NO_EMAIL),
        ("nwffuels", NO_EMAIL),
    ]


@respx.mock
async def test_poll_gives_each_supplier_its_own_address() -> None:
    route = respx.post(WesternFuel.QUOTE_URL).respond(json=WF_JSON)
    async with httpx.AsyncClient() as c:
        res = await poll(c, REQ, ["westernfuel"], email_pattern=PATTERN)
    assert json.loads(route.calls.last.request.content)["email"] == "westernfuel@example.net"
    assert len(res[0].options) == 2 and res[0].error is None


@respx.mock
async def test_poll_never_sends_email_to_email_free_provider() -> None:
    route = respx.get("https://homefuelsdirect.co.uk/index.php").respond(json={})
    async with httpx.AsyncClient() as c:
        await poll(c, EREQ, ["homefuelsdirect"], email_pattern=PATTERN)
    assert "example.net" not in str(route.calls.last.request.url)


@respx.mock
async def test_poll_error_scrubs_postcode_and_email() -> None:
    respx.get(TheHeatingOilCompany.BASE_URL).respond(status_code=500)
    async with httpx.AsyncClient() as c:
        res = await poll(c, REQ, ["theheatingoilcompany"], email_pattern=PATTERN)
    err = res[0].error
    assert "HTTPStatusError" in err
    assert "ZZ99" not in err and "example.net" not in err and "email=" not in err


@respx.mock
async def test_poll_discards_implausible_prices() -> None:
    bad = dict(WF_JSON, tiers=[dict(WF_JSON["tiers"][0], totalPence=1000)])
    respx.post(WesternFuel.QUOTE_URL).respond(json=bad)
    async with httpx.AsyncClient() as c:
        res = await poll(c, REQ, ["westernfuel"], email_pattern=PATTERN)
    assert res[0].options == [] and res[0].error == "no prices"


@respx.mock
async def test_email_providers_are_not_retried() -> None:
    route = respx.post(WesternFuel.QUOTE_URL).respond(status_code=502)
    hfd = respx.get("https://homefuelsdirect.co.uk/index.php").respond(status_code=502)
    async with httpx.AsyncClient() as c:
        res = await poll(c, REQ, ["westernfuel", "homefuelsdirect"], email_pattern=PATTERN)
    assert route.call_count == 1 and hfd.call_count == 2
    assert [r.supplier for r in res] == ["westernfuel", "homefuelsdirect"]
