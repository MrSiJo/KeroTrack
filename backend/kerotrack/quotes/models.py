"""Quote data types and pure helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

USER_AGENT = "KeroTrack/2 (+https://github.com/MrSiJo/KeroTrack)"

# UK domestic heating oil VAT rate.
VAT_RATE = 0.05


@dataclass(frozen=True)
class QuoteRequest:
    postcode: str
    litres: int
    tanker: str


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


def best_option(options: list[QuoteOption]) -> QuoteOption | None:
    """Cheapest non urgent option by all-in total, or None."""
    standard = [o for o in options if not o.urgent]
    return min(standard, key=lambda o: o.total_inc_vat) if standard else None
