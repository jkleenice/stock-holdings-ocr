from decimal import Decimal

from holdings_ocr.metrics import aggregate_pnl
from holdings_ocr.schemas import Holding


def _h(market: str, pnl: str | None) -> Holding:
    return Holding(
        raw_name="X",
        market_value=Decimal(market),
        unrealized_pnl=Decimal(pnl) if pnl is not None else None,
        currency="KRW",
    )


def test_aggregate_pnl_empty_iterable_returns_none_pair():
    assert aggregate_pnl([]) == (None, None)


def test_aggregate_pnl_returns_none_when_any_market_value_missing():
    h1 = _h("100", "10")
    h2 = Holding(raw_name="Y", market_value=None, unrealized_pnl=Decimal("0"), currency="KRW")
    assert aggregate_pnl([h1, h2]) == (None, None)


def test_aggregate_pnl_returns_none_when_any_pnl_missing():
    h1 = _h("100", "10")
    h2 = _h("200", None)
    assert aggregate_pnl([h1, h2]) == (None, None)


def test_aggregate_pnl_value_weighted_two_holdings():
    # market 1000 (pnl 100, cost 900) + market 2000 (pnl -200, cost 2200)
    # total: market 3000, pnl -100, cost 3100 → return = -100/3100 ≈ -3.2258%
    h1 = _h("1000", "100")
    h2 = _h("2000", "-200")
    pnl, pct = aggregate_pnl([h1, h2])
    assert pnl == Decimal("-100")
    assert pct.quantize(Decimal("0.0001")) == Decimal("-3.2258")


def test_aggregate_pnl_alphabet_a_plus_c_matches_review_example():
    # 알파벳 A + 알파벳 C 실제 데이터: 2,481,408 + 540,549 / 588,668 + 174,894
    # total: market 3,070,076, pnl 715,443, cost 2,354,633 → return ≈ 30.38%
    a = _h("2481408", "540549")
    c = _h("588668", "174894")
    pnl, pct = aggregate_pnl([a, c])
    assert pnl == Decimal("715443")
    assert pct.quantize(Decimal("0.01")) == Decimal("30.38")


def test_aggregate_pnl_zero_cost_basis_returns_pnl_with_none_pct():
    # market == pnl means cost basis was 0 (e.g., free stock that became valuable)
    h = _h("100", "100")
    pnl, pct = aggregate_pnl([h])
    assert pnl == Decimal("100")
    assert pct is None


def test_aggregate_pnl_single_holding_uses_its_own_pct():
    # cost 100, pnl 20, return = 20% — but our function infers cost from market - pnl,
    # so market=120, pnl=20 → cost=100, return = 20/100 * 100 = 20%
    h = _h("120", "20")
    _, pct = aggregate_pnl([h])
    assert pct == Decimal("20")
