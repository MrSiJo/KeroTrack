"""BoilerJuice quote provider (their quote journey, plain HTTP).

One GET of the quote form gives a session cookie and CSRF token, the form
POST redirects, and the quote page is server rendered with one card per
delivery date. The national average index (``prices/scraper.py``) is a
separate thing and stays as it is.
"""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from kerotrack.quotes.models import USER_AGENT, QuoteOption, QuoteRequest

_PPL = re.compile(r"([\d.]+)\s*ppl", re.I)
_KEY = re.compile(r"^(standard|delivery(\d+))_", re.I)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TOKEN = re.compile(r'name="authenticity_token"\s+value="([^"]+)"')

# deliveryN means "within N working days"; one or two days are the premium
# fast windows.
URGENT_MAX_DAYS = 2


class BoilerJuice:
    name = "boilerjuice"
    requires_email = True
    cadence = "daily"
    FORM_URL = "https://www.boilerjuice.com/uk/heating-oil-quote/"
    QUOTE_URL = "https://www.boilerjuice.com/uk/journeys/core/quote"
    OIL_TYPE = "Heating Oil (Kerosene28)"
    TANKERS = {"standard": "Standard Tanker", "4 wheeler": "4 Wheeler", "baby": "Baby Tanker"}

    def parse(self, html: str, litres: int) -> list[QuoteOption]:
        """One option per delivery card; a changed page shape gives an empty list."""
        if not isinstance(html, str) or not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        options: list[QuoteOption] = []
        seen: set[tuple[str, float]] = set()
        for card in soup.select("[data-delivery-date][data-price]"):
            delivery_by = str(card.get("data-delivery-date") or "")
            try:
                total = float(str(card.get("data-price")))
            except ValueError:
                continue
            if not _DATE.match(delivery_by) or (delivery_by, total) in seen:
                continue
            seen.add((delivery_by, total))
            label, urgent = "Standard", False
            test = card.find(attrs={"data-test": _KEY})
            if test is not None:
                m = _KEY.match(str(test.get("data-test")))
                if m and m.group(2):
                    days = int(m.group(2))
                    label = f"Within {days} working day{'s' if days != 1 else ''}"
                    urgent = days <= URGENT_MAX_DAYS
            ppl_m = _PPL.search(card.get_text(" ", strip=True))
            ppl_net = float(ppl_m.group(1)) if ppl_m else None
            fees = (
                max(0.0, round(total - ppl_net * litres / 100 * 1.05, 2))
                if ppl_net is not None
                else 0.0
            )
            options.append(
                QuoteOption(
                    supplier=self.name,
                    litres=litres,
                    delivery_by=delivery_by,
                    delivery_label=label,
                    urgent=urgent,
                    ppl_net=ppl_net,
                    total_inc_vat=total,
                    fees_inc_vat=fees,
                )
            )
        return options

    async def fetch(self, client: httpx.AsyncClient, req: QuoteRequest) -> list[QuoteOption]:
        """Run the quote journey. HTTP errors propagate; a missing token raises."""
        headers = {"User-Agent": USER_AGENT}
        form = await client.get(self.FORM_URL, headers=headers, timeout=20.0)
        form.raise_for_status()
        m = _TOKEN.search(form.text)
        if not m:
            raise ValueError("quote form token not found")
        post = await client.post(
            self.QUOTE_URL,
            data={
                "authenticity_token": m.group(1),
                "volume": str(req.litres),
                "postcode": req.postcode,
                "email": req.email or "",
                "oil_type": self.OIL_TYPE,
                "theTanker": self.TANKERS.get(req.tanker.strip().lower(), "Standard Tanker"),
                # "Don't send me offers" ticked; no consent is ever given.
                "opt_out_email": "1",
                "skip_opt_out_email": "0",
                "action": "submitStage1",
                "usage": "domestic",
            },
            headers=headers,
            timeout=20.0,
            follow_redirects=False,
        )
        if post.status_code not in (301, 302, 303):
            post.raise_for_status()
            return self.parse(post.text, req.litres)
        page = await client.get(self.QUOTE_URL, headers=headers, timeout=20.0)
        page.raise_for_status()
        return self.parse(page.text, req.litres)
