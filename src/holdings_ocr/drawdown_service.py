from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pandas as pd
import yfinance as yf

from .drawdown import compute_drawdown_stats, to_yfinance_symbol


PERIOD_LABELS = {
    "1y": "최근 1년",
    "3y": "최근 3년",
    "5y": "최근 5년",
    "max": "전체 기간",
}


def fetch_close_prices_raw(yf_symbol: str, period: str) -> pd.Series:
    df = yf.download(
        yf_symbol,
        period=period,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    return extract_close_series(df)


def extract_close_series(df: pd.DataFrame | None) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=float)

    if isinstance(df.columns, pd.MultiIndex):
        close_col = next((column for column in df.columns if column[0] == "Close"), None)
        if close_col is None:
            return pd.Series(dtype=float)
        close = df[close_col]
    else:
        if "Close" not in df.columns:
            return pd.Series(dtype=float)
        close = df["Close"]

    return pd.to_numeric(close, errors="coerce").dropna()


def format_price(value: float) -> str:
    if value >= 1000:
        return f"{value:,.0f}"
    if value >= 10:
        return f"{value:,.2f}"
    return f"{value:,.4f}"


def drawdown_amount(drawdown_pct: float) -> float:
    return max(0.0, -drawdown_pct)


def drawdown_color(drawdown_amount_value: float) -> str:
    if drawdown_amount_value < 5:
        return "#2ca02c"
    if drawdown_amount_value < 15:
        return "#e9c46a"
    if drawdown_amount_value < 30:
        return "#f4a261"
    return "#e45756"


def drawdown_label(drawdown_amount_value: float) -> str:
    if drawdown_amount_value < 5:
        return "고점 근처"
    if drawdown_amount_value < 15:
        return "약한 조정"
    if drawdown_amount_value < 30:
        return "중간 조정"
    return "큰 하락"


def build_drawdown_rows(
    tracked: list[str],
    period: str,
    as_of_date: date | str | pd.Timestamp | None = None,
    *,
    fetch_close_prices: Callable[[str, str], pd.Series] = fetch_close_prices_raw,
) -> tuple[list[dict[str, object]], list[tuple[str, str]]]:
    rows: list[dict[str, object]] = []
    failures: list[tuple[str, str]] = []

    for ticker in tracked:
        yf_symbol = to_yfinance_symbol(ticker)
        try:
            close = fetch_close_prices(yf_symbol, period)
            stats = compute_drawdown_stats(close, as_of_date=as_of_date)
        except Exception as exc:  # noqa: BLE001
            failures.append((ticker, str(exc)))
            continue

        rows.append(
            {
                "티커": ticker,
                "조회 티커": yf_symbol,
                "기준가": stats.current_price,
                "기준가 날짜": stats.current_date.date().isoformat(),
                "고점": stats.peak_price,
                "고점 날짜": stats.peak_date.date().isoformat(),
                "기준일 하락률": stats.drawdown_pct,
                "회복 필요 상승률": stats.recovery_pct,
            }
        )

    rows.sort(key=lambda row: drawdown_amount(float(row["기준일 하락률"])), reverse=True)
    return rows, failures
