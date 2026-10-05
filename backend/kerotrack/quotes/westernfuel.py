"""Western Fuel quote provider (the JSON API behind their instant quote form)."""

from __future__ import annotations

import httpx

from kerotrack.quotes.models import USER_AGENT, QuoteOption, QuoteRequest, is_urgent_label

_TANKERS = {"standard": "Standard", "4 wheeler": "4 Wheeler", "baby": "Baby"}


class WesternFuel:
    name = "westernfuel"
    requires_email = True
    cadence = "daily"
    QUOTE_URL = "https://www.westernfuel.co.uk/api/quote"
    FUEL_KEROSENE = "Kero"

    def parse(self, payload: object, litres: int) -> list[QuoteOption]:
        """One option per delivery tier; garbage gives an empty list."""
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            return []
        tiers = payload.get("tiers")
        if not isinstance(tiers, list):
            return []
        options: list[QuoteOption] = []
        for t in tiers:
            if not isinstance(t, dict):
                continue
            try:
                total = int(t["totalPence"]) / 100
                fees = int(t.get("serviceChargePence") or 0) / 100
            except (KeyError, TypeError, ValueError):
                continue
            try:
                ppl_net = float(t["pricePerLitrePence"])
            except (KeyError, TypeError, ValueError):
                ppl_net = None
            label = str(t.get("name") or t.get("id") or "Standard")
            delivery_by = t.get("deliveryDate")
            options.append(
                QuoteOption(
                    supplier=self.name,
                    litres=litres,
                    delivery_by=delivery_by if isinstance(delivery_by, str) else None,
                    delivery_label=label,
                    urgent=is_urgent_label(label),
                    ppl_net=ppl_net,
                    total_inc_vat=total,
                    fees_inc_vat=fees,
                )
            )
        return options

    async def fetch(self, client: httpx.AsyncClient, req: QuoteRequest) -> list[QuoteOption]:
        """Fetch live quotes. HTTP and JSON errors propagate to the caller."""
        r = await client.post(
            self.QUOTE_URL,
            json={
                "litres": req.litres,
                "fuelType": self.FUEL_KEROSENE,
                "tankerType": _TANKERS.get(req.tanker.strip().lower(), "Standard"),
                "postcode": req.postcode,
                "email": req.email or "",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=20.0,
        )
        r.raise_for_status()
        return self.parse(r.json(), req.litres)
