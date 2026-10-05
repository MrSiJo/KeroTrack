"""The Heating Oil Company quote provider (server rendered quote page)."""

from __future__ import annotations

import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from kerotrack.quotes.models import USER_AGENT, QuoteOption, QuoteRequest, is_urgent_label

_PPL = re.compile(r"([\d.]+)p per litre \(exc VAT\)", re.I)
_TOTAL = re.compile(r"£\s*([\d,]+\.\d{2})\s*inc VAT", re.I)
_DATE = re.compile(r"(\d{1,2} [A-Z][a-z]+ \d{4})")


def _delivery_by(text: str) -> str | None:
    m = _DATE.search(text)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%d %B %Y").date().isoformat()
    except ValueError:
        return None


class TheHeatingOilCompany:
    name = "theheatingoilcompany"
    requires_email = True
    cadence = "daily"
    BASE_URL = "https://www.theheatingoilcompany.co.uk/Quote"
    # Form values seen on the live quote form (2026-10-05).
    PRODUCT_STANDARD_DOMESTIC = "10"
    VEHICLE_STANDARD = "4"
    HEARD_FROM_GOOGLE = "15"

    def parse(self, html: str, litres: int) -> list[QuoteOption]:
        """One option per priced card; a changed page shape gives an empty list."""
        if not isinstance(html, str) or not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        options: list[QuoteOption] = []
        seen: set[tuple[str | None, float]] = set()
        for ppl_p in soup.find_all("p", string=_PPL):
            card = ppl_p.parent
            if card is None:
                continue
            text = card.get_text(" ", strip=True)
            total_m = _TOTAL.search(text)
            ppl_m = _PPL.search(text)
            if not total_m or not ppl_m:
                continue
            try:
                total = float(total_m.group(1).replace(",", ""))
                ppl_net = float(ppl_m.group(1))
            except ValueError:
                continue
            strong = card.find("strong")
            label = strong.get_text(" ", strip=True) if strong else "Best Price"
            delivery_by = _delivery_by(text)
            if (delivery_by, total) in seen:
                continue
            seen.add((delivery_by, total))
            options.append(
                QuoteOption(
                    supplier=self.name,
                    litres=litres,
                    delivery_by=delivery_by,
                    delivery_label=label,
                    urgent=is_urgent_label(label),
                    ppl_net=ppl_net,
                    total_inc_vat=total,
                    fees_inc_vat=max(0.0, round(total - ppl_net * litres / 100 * 1.05, 2)),
                )
            )
        return options

    async def fetch(self, client: httpx.AsyncClient, req: QuoteRequest) -> list[QuoteOption]:
        """Fetch live quotes. The site returns HTTP 500 without the email."""
        params = {
            "productid": self.PRODUCT_STANDARD_DOMESTIC,
            "qty": str(req.litres),
            "vehicle": self.VEHICLE_STANDARD,
            "location": req.postcode,
            "heardfrom": self.HEARD_FROM_GOOGLE,
            "email": req.email or "",
            "usage": "domestic",
            "getQuote": "Get a Quote",
        }
        r = await client.get(
            self.BASE_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=20.0
        )
        r.raise_for_status()
        return self.parse(r.text, req.litres)
