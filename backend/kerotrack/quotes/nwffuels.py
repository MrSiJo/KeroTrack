"""NWF Fuels quote provider (the JSON endpoints behind their quote page).

Prices come from the theme's ``quote-update`` REST endpoint; delivery tiers
(names, dates and any per tier charge ex VAT) from ``get_delivery_options``.
Marketing consent is a separate call that is never made.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import httpx

from kerotrack.clock import local_now
from kerotrack.quotes.models import (
    USER_AGENT,
    VAT_RATE,
    QuoteOption,
    QuoteRequest,
    is_urgent_label,
)

_ORDINAL = re.compile(r"(\d{1,2})(st|nd|rd|th)\b", re.I)


def _delivery_by(text: object, today: date) -> str | None:
    """'Monday 12th October' (no year) to an ISO date on or after about today."""
    if not isinstance(text, str):
        return None
    cleaned = _ORDINAL.sub(r"\1", text).strip()
    for fmt in ("%A %d %B", "%d %B"):
        try:
            parsed = datetime.strptime(f"{cleaned} {today.year}", f"{fmt} %Y").date()
        except ValueError:
            continue
        if parsed < today - timedelta(days=30):
            parsed = parsed.replace(year=today.year + 1)
        return parsed.isoformat()
    return None


class NwfFuels:
    name = "nwffuels"
    requires_email = True
    cadence = "daily"
    AJAX_URL = "https://www.nwffuels.co.uk/wp-admin/admin-ajax.php"
    COSTS_URL = "https://www.nwffuels.co.uk/wp-json/nwf-fuels/v1/quote-update"
    PRODUCT_STANDARD_KEROSENE = 182
    VEHICLE_STANDARD = "1"
    SECTOR = "residential"

    def parse(
        self,
        costs: object,
        deliveries: object,
        litres: int,
        today: date | None = None,
    ) -> list[QuoteOption]:
        """Standard kerosene price per delivery tier; garbage gives an empty list."""
        today = today or local_now().date()
        if not isinstance(costs, dict) or not isinstance(costs.get("products"), list):
            return []
        product = next(
            (
                p
                for p in costs["products"]
                if isinstance(p, dict)
                and str(p.get("product_id")) == str(self.PRODUCT_STANDARD_KEROSENE)
            ),
            None,
        )
        if product is None:
            return []
        try:
            base_total = float(str(product["total_incvat"]).replace(",", ""))
            ppl_net = float(product["total_ppl"])
        except (KeyError, TypeError, ValueError):
            return []

        tiers = [d for d in deliveries if isinstance(d, dict)] if isinstance(deliveries, list) else []
        if not tiers:
            tiers = [{"name": "Standard", "cost": "0", "date": None}]
        options: list[QuoteOption] = []
        for tier in tiers:
            label = str(tier.get("name") or "Standard")
            try:
                charge = float(tier.get("cost") or 0) * (1 + VAT_RATE)
            except (TypeError, ValueError):
                continue
            options.append(
                QuoteOption(
                    supplier=self.name,
                    litres=litres,
                    delivery_by=_delivery_by(tier.get("date"), today),
                    delivery_label=label,
                    urgent=is_urgent_label(label),
                    ppl_net=ppl_net,
                    total_inc_vat=round(base_total + charge, 2),
                    fees_inc_vat=round(charge, 2),
                )
            )
        return options

    async def fetch(self, client: httpx.AsyncClient, req: QuoteRequest) -> list[QuoteOption]:
        """Fetch live quotes. HTTP and JSON errors propagate to the caller."""
        headers = {"User-Agent": USER_AGENT}
        r = await client.post(
            self.COSTS_URL,
            json={
                "action": "get_costs",
                "data": {
                    "postcode": req.postcode,
                    "email": req.email or "",
                    "sector": self.SECTOR,
                    "quantity": str(req.litres),
                    "product": str(self.PRODUCT_STANDARD_KEROSENE),
                    "vehicle": self.VEHICLE_STANDARD,
                    "delivery": "Standard",
                },
            },
            headers=headers,
            timeout=20.0,
        )
        r.raise_for_status()
        costs = r.json()
        deliveries: object = []
        try:
            d = await client.post(
                self.AJAX_URL,
                data={
                    "action": "get_delivery_options",
                    "postcode": req.postcode,
                    "sector": self.SECTOR,
                    "product": str(self.PRODUCT_STANDARD_KEROSENE),
                },
                headers=headers,
                timeout=20.0,
            )
            d.raise_for_status()
            deliveries = d.json()
        except (httpx.HTTPError, ValueError):
            # Prices without tiers still give a usable standard quote.
            deliveries = []
        return self.parse(costs, deliveries, req.litres)
