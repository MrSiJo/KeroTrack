"""Home Fuels Direct provider and registry poll (mocked via respx)."""

from __future__ import annotations

import json
import pathlib

import httpx
import respx

from kerotrack.quotes.homefuelsdirect import HomeFuelsDirect
from kerotrack.quotes.models import QuoteRequest
from kerotrack.quotes.registry import poll

FIX = json.loads((pathlib.Path(__file__).parents[1] / "fixtures" / "hfd_quote.json").read_text())
REQ = QuoteRequest("ZZ99 9ZZ", 500, "standard")


def test_parse_skips_zero_windows_and_marks_last_non_urgent():
    opts = HomeFuelsDirect().parse(FIX, 500)
    assert [o.total_inc_vat for o in opts] == [577.71, 577.71, 551.25]
    assert [o.urgent for o in opts] == [True, True, False]
    assert opts[-1].ppl_net == 105.0


def test_parse_garbage_returns_empty():
    assert HomeFuelsDirect().parse("<html>", 500) == []
    assert HomeFuelsDirect().parse({"prices": {}}, 500) == []


@respx.mock
async def test_fetch_sends_postcode_qty_and_user_agent():
    route = respx.get("https://homefuelsdirect.co.uk/index.php").respond(json=FIX)
    async with httpx.AsyncClient() as c:
        opts = await HomeFuelsDirect().fetch(c, REQ)
    req = route.calls.last.request
    assert req.url.params["pcode"] == "ZZ99 9ZZ" and req.url.params["qty"] == "500"
    assert req.headers["User-Agent"].startswith("KeroTrack/2")
    assert len(opts) == 3


@respx.mock
async def test_poll_records_errors_not_numbers():
    respx.get("https://homefuelsdirect.co.uk/index.php").respond(status_code=500)
    async with httpx.AsyncClient() as c:
        res = await poll(c, REQ, ["homefuelsdirect", "nope"])
    assert res[0].options == [] and res[0].error
    assert res[1].error == "unknown provider"


@respx.mock
async def test_poll_html_body_is_no_prices():
    respx.get("https://homefuelsdirect.co.uk/index.php").respond(text="<html></html>")
    async with httpx.AsyncClient() as c:
        res = await poll(c, REQ, ["homefuelsdirect"])
    assert res[0].options == [] and res[0].error


@respx.mock
async def test_poll_error_never_contains_postcode():
    respx.get("https://homefuelsdirect.co.uk/index.php").respond(status_code=500)
    async with httpx.AsyncClient() as c:
        res = await poll(c, REQ, ["homefuelsdirect"])
    err = res[0].error
    assert "HTTPStatusError" in err
    assert "ZZ99" not in err and "pcode" not in err
