"""Quote models: effective price and best option ranking."""

from __future__ import annotations

import pytest

from kerotrack.quotes.models import QuoteOption, best_option, effective_ppl


def _q(total, urgent=False, s="a"):
    return QuoteOption(s, 500, None, None, urgent, None, total, 0.0)


def test_effective_ppl_includes_fees_ex_vat():
    assert effective_ppl(587.70, 500) == pytest.approx(111.943, abs=1e-3)


def test_best_option_ignores_urgent_and_ranks_on_total():
    assert best_option([_q(570, urgent=True), _q(588, s="bj"), _q(578, s="hfd")]).supplier == "hfd"
    assert best_option([_q(570, urgent=True)]) is None
    assert best_option([]) is None
