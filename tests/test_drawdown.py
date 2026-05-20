from pathlib import Path

import pandas as pd
import pytest

from holdings_ocr.drawdown import (
    compute_drawdown_series,
    compute_drawdown_stats,
    load_tracked_tickers,
    parse_ticker_input,
    save_tracked_tickers,
    to_yfinance_symbol,
)


def test_parse_ticker_input_accepts_common_separators_and_dedupes():
    result = parse_ticker_input("aapl, msft\nNVDA  aapl; btc-usd")

    assert result == ["AAPL", "MSFT", "NVDA", "BTC-USD"]


def test_save_and_load_tracked_tickers_round_trip(tmp_path: Path):
    path = tmp_path / "tickers.json"

    save_tracked_tickers(["aapl", "MSFT", "aapl"], path=path)

    assert load_tracked_tickers(path) == ["AAPL", "MSFT"]


def test_load_tracked_tickers_returns_empty_for_missing_or_invalid_file(tmp_path: Path):
    assert load_tracked_tickers(tmp_path / "missing.json") == []

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not-json", encoding="utf-8")
    assert load_tracked_tickers(invalid) == []


def test_to_yfinance_symbol_maps_six_digit_korean_symbol_to_ks_suffix():
    assert to_yfinance_symbol("005930") == "005930.KS"


def test_to_yfinance_symbol_preserves_existing_suffix_and_crypto_dash():
    assert to_yfinance_symbol("005930.KQ") == "005930.KQ"
    assert to_yfinance_symbol("btc-usd") == "BTC-USD"


def test_compute_drawdown_stats_uses_period_peak_and_current_price():
    prices = pd.Series(
        [100.0, 150.0, 120.0],
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
    )

    stats = compute_drawdown_stats(prices)

    assert stats.current_price == pytest.approx(120.0)
    assert stats.current_date == pd.Timestamp("2024-01-03")
    assert stats.peak_price == pytest.approx(150.0)
    assert stats.peak_date == pd.Timestamp("2024-01-02")
    assert stats.drawdown_pct == pytest.approx(-20.0)
    assert stats.recovery_pct == pytest.approx(25.0)


def test_compute_drawdown_stats_ignores_nan_and_non_positive_prices():
    prices = pd.Series(
        [0.0, None, 100.0, 80.0],
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]),
    )

    stats = compute_drawdown_stats(prices)

    assert stats.peak_price == pytest.approx(100.0)
    assert stats.drawdown_pct == pytest.approx(-20.0)


def test_compute_drawdown_stats_uses_as_of_date_price_and_prior_peak():
    prices = pd.Series(
        [100.0, 150.0, 120.0, 180.0, 90.0],
        index=pd.to_datetime([
            "2024-01-01",
            "2024-01-02",
            "2024-01-03",
            "2024-01-04",
            "2024-01-05",
        ]),
    )

    stats = compute_drawdown_stats(prices, as_of_date="2024-01-03")

    assert stats.current_price == pytest.approx(120.0)
    assert stats.current_date == pd.Timestamp("2024-01-03")
    assert stats.peak_price == pytest.approx(150.0)
    assert stats.peak_date == pd.Timestamp("2024-01-02")
    assert stats.drawdown_pct == pytest.approx(-20.0)


def test_compute_drawdown_stats_uses_last_price_before_as_of_date():
    prices = pd.Series(
        [100.0, 150.0],
        index=pd.to_datetime(["2024-01-01", "2024-01-03"]),
    )

    stats = compute_drawdown_stats(prices, as_of_date="2024-01-02")

    assert stats.current_price == pytest.approx(100.0)
    assert stats.current_date == pd.Timestamp("2024-01-01")
    assert stats.drawdown_pct == pytest.approx(0.0)


def test_compute_drawdown_stats_raises_when_no_price_exists_before_as_of_date():
    prices = pd.Series(
        [100.0],
        index=pd.to_datetime(["2024-01-02"]),
    )

    with pytest.raises(ValueError, match="price series is empty"):
        compute_drawdown_stats(prices, as_of_date="2024-01-01")


def test_compute_drawdown_stats_raises_for_empty_prices():
    with pytest.raises(ValueError, match="price series is empty"):
        compute_drawdown_stats(pd.Series([], dtype=float))


def test_compute_drawdown_series_tracks_running_peak():
    prices = pd.Series([100.0, 150.0, 120.0, 180.0, 90.0])

    series = compute_drawdown_series(prices)

    assert series.iloc[0] == pytest.approx(0.0)
    assert series.iloc[2] == pytest.approx(-20.0)
    assert series.iloc[3] == pytest.approx(0.0)
    assert series.iloc[4] == pytest.approx(-50.0)
