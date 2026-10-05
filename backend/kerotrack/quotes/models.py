"""Quote data types and pure helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

USER_AGENT = "KeroTrack/2 (+https://github.com/MrSiJo/KeroTrack)"

# UK domestic heating oil VAT rate.
VAT_RATE = 0.05


# Plausible effective price range (pence per litre ex VAT). Anything outside
# it means a supplier page changed shape, so the option is discarded rather
# than reported as a price.
MIN_SANE_PPL = 30.0
MAX_SANE_PPL = 300.0


@dataclass(frozen=True)
class QuoteRequest:
    postcode: str
    litres: int
    tanker: str
    # Only sent to providers that require one (``requires_email``).
    email: str | None = None


@dataclass(frozen=True)
class QuoteOption:
    supplier: str
    litres: int
    delivery_by: str | None
    delivery_label: str | None
    urgent: bool
    ppl_net: float | None
    total_inc_vat: float
    fees_inc_vat: float


@dataclass
class PollResult:
    supplier: str
    options: list[QuoteOption] = field(default_factory=list)
    error: str | None = None


def effective_ppl(total_inc_vat: float, litres: int) -> float:
    """Pence per litre ex VAT, with delivery and fees included in the total."""
    return total_inc_vat / (1 + VAT_RATE) / litres * 100


def is_sane(option: QuoteOption) -> bool:
    """True when the option's all in price is a plausible heating oil price."""
    if option.litres <= 0 or option.total_inc_vat <= 0:
        return False
    return MIN_SANE_PPL <= effective_ppl(option.total_inc_vat, option.litres) <= MAX_SANE_PPL


_URGENT = re.compile(r"express|next\s*day|saturday|sunday|emergency|urgent|priority", re.I)


def is_urgent_label(label: str | None) -> bool:
    """Premium fast delivery windows (express, next day, weekend, emergency)."""
    return bool(label) and bool(_URGENT.search(label or ""))


def quote_email(pattern: str, provider: str) -> str | None:
    """The per supplier quote address from ``buying.quote_email_pattern``."""
    pattern = (pattern or "").strip()
    if not pattern or "@" not in pattern:
        return None
    return pattern.replace("{site}", provider)


def all_in_ppl(total_inc_vat: float, litres: int) -> float:
    """What a litre really costs: pence per litre with VAT, delivery and fees."""
    return total_inc_vat / litres * 100


def best_option(options: list[QuoteOption]) -> QuoteOption | None:
    """Cheapest non urgent option by all-in total, or None."""
    standard = [o for o in options if not o.urgent]
    return min(standard, key=lambda o: o.total_inc_vat) if standard else None
