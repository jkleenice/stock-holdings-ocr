import pandas as pd
import pytest

import views.vix as vix_module
from holdings_ocr.vix_strategy import (
    build_vix_comparison_view_model,
    compute_cagr,
    first_trading_days_of_month,
    range_scale,
    simulate_dca,
    simulate_vix_lumpsum,
)


def _constant_prices(start="2024-01-01", end="2024-12-31", price=100.0):
    dates = pd.bdate_range(start=start, end=end)
    return pd.Series([price] * len(dates), index=dates)


def test_vix_module_exports_render_callable():
    assert hasattr(vix_module, "render")
    assert callable(vix_module.render)


# ── _first_trading_days_of_month ─────────────────────────────


def test_first_trading_days_picks_one_per_month():
    prices = _constant_prices()
    firsts = first_trading_days_of_month(prices.index)
    assert len(firsts) == 12


def test_first_trading_days_empty_input():
    empty = pd.DatetimeIndex([])
    assert len(first_trading_days_of_month(empty)) == 0


def test_first_trading_days_picks_earliest_in_month():
    prices = _constant_prices(start="2024-01-15", end="2024-03-31")
    firsts = first_trading_days_of_month(prices.index)
    assert firsts[0] == pd.Timestamp("2024-01-15")
    assert firsts[1] == pd.Timestamp("2024-02-01")
    assert firsts[2] == pd.Timestamp("2024-03-01")


# ── simulate_dca ──────────────────────────────────────────────


def test_simulate_dca_buys_once_per_month():
    prices = _constant_prices(price=100.0)
    result = simulate_dca(prices, monthly_amount=100.0)
    assert result.buy_count == 12
    assert result.total_invested == pytest.approx(1200.0)
    # Constant price → 1 share per buy → 12 shares × $100 = $1200
    assert result.final_value == pytest.approx(1200.0)


def test_simulate_dca_handles_appreciating_price():
    dates = pd.bdate_range(start="2024-01-01", end="2024-12-31")
    n = len(dates)
    # Linear: 100 → 200
    prices = pd.Series([100.0 + (i / (n - 1)) * 100.0 for i in range(n)], index=dates)
    result = simulate_dca(prices, monthly_amount=100.0)
    assert result.final_value > result.total_invested  # gains


def test_simulate_dca_empty_prices_returns_zeros():
    prices = pd.Series([], dtype=float, index=pd.DatetimeIndex([]))
    result = simulate_dca(prices, monthly_amount=100.0)
    assert result.final_value == 0.0
    assert result.total_invested == 0.0
    assert result.buy_count == 0


def test_simulate_dca_invested_grows_monotonically():
    prices = _constant_prices()
    result = simulate_dca(prices, monthly_amount=100.0)
    invested = result.timeline["invested"].values
    assert all(invested[i] <= invested[i + 1] for i in range(len(invested) - 1))


def test_simulate_dca_value_equals_shares_times_price_plus_cash():
    prices = _constant_prices(price=100.0)
    result = simulate_dca(prices, monthly_amount=100.0)
    last = result.timeline.iloc[-1]
    assert last["value"] == pytest.approx(last["shares"] * 100.0 + last["cash"])


# ── simulate_vix_lumpsum ──────────────────────────────────────


def test_simulate_vix_lumpsum_no_buys_when_vix_low():
    prices = _constant_prices(price=100.0)
    vix = pd.Series([15.0] * len(prices), index=prices.index)
    result = simulate_vix_lumpsum(prices, vix, monthly_amount=100.0, vix_threshold=30.0)
    assert result.buy_count == 0
    assert result.total_invested == pytest.approx(1200.0)
    # All cash, no shares
    assert result.timeline["cash"].iloc[-1] == pytest.approx(1200.0)
    assert result.final_value == pytest.approx(1200.0)


def test_simulate_vix_lumpsum_buys_when_threshold_met():
    prices = _constant_prices(price=100.0)
    vix = pd.Series([15.0] * len(prices), index=prices.index)
    spike_start = pd.Timestamp("2024-07-01")
    vix.loc[vix.index >= spike_start] = 35.0
    result = simulate_vix_lumpsum(prices, vix, monthly_amount=100.0, vix_threshold=30.0)
    # Jul-Dec → 6 accrual months, each accrual day fires a buy because VIX >= 30
    assert result.buy_count == 6
    assert result.timeline["cash"].iloc[-1] == pytest.approx(0.0)
    # All invested money deployed at constant price → final value == total invested
    assert result.final_value == pytest.approx(1200.0)


def test_simulate_vix_lumpsum_all_buy_dates_above_threshold():
    prices = _constant_prices(price=100.0)
    vix = pd.Series([15.0] * len(prices), index=prices.index)
    vix.loc[vix.index >= pd.Timestamp("2024-07-01")] = 35.0
    result = simulate_vix_lumpsum(prices, vix, monthly_amount=100.0, vix_threshold=30.0)
    buy_dates = result.timeline[result.timeline["buy"]].index
    for d in buy_dates:
        assert vix.loc[d] >= 30.0


def test_simulate_vix_lumpsum_drains_cash_completely_on_buy():
    prices = _constant_prices(price=100.0)
    vix = pd.Series([15.0] * len(prices), index=prices.index)
    vix.loc[pd.Timestamp("2024-06-03")] = 35.0  # single spike
    result = simulate_vix_lumpsum(prices, vix, monthly_amount=100.0, vix_threshold=30.0)
    # June 3 is the first trading day of June with VIX spike → accrue $600 cash (Jan-Jun), buy all
    buy_rows = result.timeline[result.timeline["buy"]]
    assert len(buy_rows) == 1
    # cash on buy day == 0 (drained)
    assert buy_rows["cash"].iloc[0] == pytest.approx(0.0)


def test_simulate_vix_lumpsum_alignment_uses_intersection():
    # prices Jan-Dec, vix only Jul-Dec → only Jul-Dec considered
    dates_p = pd.bdate_range(start="2024-01-01", end="2024-12-31")
    dates_v = pd.bdate_range(start="2024-07-01", end="2024-12-31")
    prices = pd.Series([100.0] * len(dates_p), index=dates_p)
    vix = pd.Series([35.0] * len(dates_v), index=dates_v)
    result = simulate_vix_lumpsum(prices, vix, monthly_amount=100.0, vix_threshold=30.0)
    # Only 6 months of overlap → 6 accrual + 6 buys (all above threshold)
    assert result.buy_count == 6
    assert result.total_invested == pytest.approx(600.0)


# ── compute_cagr ──────────────────────────────────────────────


def test_compute_cagr_zero_years_returns_zero():
    assert compute_cagr(1000.0, 2000.0, 0.0) == 0.0


def test_compute_cagr_zero_start_returns_zero():
    assert compute_cagr(0.0, 1000.0, 5.0) == 0.0


def test_compute_cagr_negative_end_returns_zero():
    assert compute_cagr(1000.0, 0.0, 5.0) == 0.0


def test_compute_cagr_doubles_in_10_years():
    # (2)^0.1 - 1 ≈ 0.07177346
    assert compute_cagr(1000.0, 2000.0, 10.0) == pytest.approx(0.0717734, abs=1e-5)


def test_compute_cagr_handles_loss():
    # (0.5)^0.1 - 1 ≈ -0.06697
    assert compute_cagr(1000.0, 500.0, 10.0) == pytest.approx(-0.0670, abs=1e-3)


# ── _range_scale ──────────────────────────────────────────────


def test_range_scale_maps_min_to_zero_and_max_to_hundred():
    s = pd.Series([10.0, 20.0, 30.0, 40.0])
    scaled = range_scale(s)
    assert scaled.iloc[0] == pytest.approx(0.0)
    assert scaled.iloc[-1] == pytest.approx(100.0)


def test_range_scale_constant_series_returns_fifty():
    s = pd.Series([5.0, 5.0, 5.0])
    scaled = range_scale(s)
    assert all(v == 50.0 for v in scaled)


def test_build_vix_comparison_view_model_prepares_chart_rows():
    prices = _constant_prices(price=100.0)
    vix = pd.Series([15.0] * len(prices), index=prices.index)

    view_model = build_vix_comparison_view_model(
        ticker="SPY",
        prices=prices,
        vix=vix,
        monthly_amount=100.0,
        vix_threshold=30.0,
    )

    assert view_model.ticker == "SPY"
    assert view_model.dca.buy_count == 12
    assert view_model.vix_strategy.buy_count == 0
    assert view_model.normalized_rows[0]["시리즈"] == "SPY 가격"
    assert view_model.portfolio_rows[0]["전략"] == "매월 매수"
    assert view_model.cash_rows[-1]["현금($)"] == pytest.approx(1200.0)
