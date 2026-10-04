"""Home Fuels Direct quote provider (public JSON endpoint behind their quote form)."""

from __future__ import annotations

import re

import httpx

from kerotrack.quotes.models import USER_AGENT, QuoteOption, QuoteRequest


def _window_n(key: str) -> int:
    m = re.search(r"(\d+)$", key)
    return int(m.group(1)) if m else 0


class HomeFuelsDirect:
    name = "homefuelsdirect"
    BASE_URL = "https://homefuelsdirect.co.uk/index.php"

    def parse(self, payload: object, litres: int) -> list[QuoteOption]:
        """Turn the locateJS payload into options; garbage gives an empty list."""
        if not isinstance(payload, dict):
            return []
        prices = payload.get("prices")
        if not isinstance(prices, dict):
            return []
        kept: list[tuple[str, dict]] = []
        for key in sorted(prices, key=_window_n):
            w = prices[key]
            if not isinstance(w, dict):
                continue
            try:
                if float(w.get("orderTotal", 0)) > 0:
                    kept.append((key, w))
            except (TypeError, ValueError):
                continue
        options: list[QuoteOption] = []
        for i, (key, w) in enumerate(kept):
            last = i == len(kept) - 1
            try:
                ppl_net = round(float(w["ppl_total_net"]) * 100, 2)
            except (KeyError, TypeError, ValueError):
                ppl_net = None
            options.append(
                QuoteOption(
                    supplier=self.name,
                    litres=litres,
                    delivery_by=None,
                    delivery_label="Standard" if last else f"Faster ({key})",
                    urgent=not last,
                    ppl_net=ppl_net,
                    total_inc_vat=float(w["orderTotal"]),
                    fees_inc_vat=0.0,
                )
            )
        return options

    async def fetch(self, client: httpx.AsyncClient, req: QuoteRequest) -> list[QuoteOption]:
        """Fetch live quotes. HTTP and JSON errors propagate to the caller."""
        params = {
            "option": "com_virtuemart",
            "view": "cart",
            "task": "locateJS",
            "format": "json",
            "ftype": "1",
            "customer_uniqid": "",
            "customer_county": "",
            "pcode": req.postcode,
            "qty": str(req.litres),
            "async": "true",
        }
        r = await client.get(
            self.BASE_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=15.0
        )
        r.raise_for_status()
        return self.parse(r.json(), req.litres)
