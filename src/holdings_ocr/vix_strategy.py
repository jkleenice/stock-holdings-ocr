from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
import yfinance as yf


@dataclass(frozen=True)
class SimulationResult:
    """Output of a single strategy simulation over a daily price series."""

    timeline: pd.DataFrame
    final_value: float
    total_invested: float
    buy_count: int


@dataclass(frozen=True)
class VixComparisonViewModel:
    ticker: str
    vix_threshold: float
    prices: pd.Series
    vix: pd.Series
    dca: SimulationResult
    vix_strategy: SimulationResult
    years: float
    dca_cagr: float
    vix_cagr: float
    start_date: date
    end_date: date
    trading_days: int
    normalized_rows: list[dict[str, object]]
    portfolio_rows: list[dict[str, object]]
    cash_rows: list[dict[str, object]]
    price_rows: list[dict[str, object]]
    buy_marker_rows: list[dict[str, object]]


def first_trading_days_of_month(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Return one date per (year, month), using the earliest trading day in the index."""
    if len(index) == 0:
        return pd.DatetimeIndex([])
    months = pd.PeriodIndex(index, freq="M")
    df = pd.DataFrame({"date": index, "month": months})
    firsts = df.groupby("month")["date"].min()
    return pd.DatetimeIndex(firsts.values)


def simulate_dca(prices: pd.Series, monthly_amount: float) -> SimulationResult:
    """Invest `monthly_amount` on the first trading day of each month present in `prices`."""
    if prices.empty:
        return SimulationResult(
            timeline=pd.DataFrame(),
            final_value=0.0,
            total_invested=0.0,
            buy_count=0,
        )

    buy_days = set(first_trading_days_of_month(prices.index))
    rows: list[dict[str, object]] = []
    shares = 0.0
    cash = 0.0
    invested = 0.0
    buy_count = 0

    for day, price in prices.items():
        price_f = float(price)
        is_buy = day in buy_days and monthly_amount > 0 and price_f > 0
        if is_buy:
            shares += monthly_amount / price_f
            invested += monthly_amount
            buy_count += 1
        rows.append({
            "date": day,
            "shares": shares,
            "cash": cash,
            "value": shares * price_f + cash,
            "buy": is_buy,
            "invested": invested,
        })

    timeline = pd.DataFrame(rows).set_index("date")
    return SimulationResult(
        timeline=timeline,
        final_value=float(timeline["value"].iloc[-1]),
        total_invested=float(timeline["invested"].iloc[-1]),
        buy_count=buy_count,
    )


def simulate_vix_lumpsum(
    prices: pd.Series,
    vix: pd.Series,
    monthly_amount: float,
    vix_threshold: float,
) -> SimulationResult:
    """Accrue monthly cash, then buy with all available cash when VIX reaches threshold."""
    if prices.empty:
        return SimulationResult(
            timeline=pd.DataFrame(),
            final_value=0.0,
            total_invested=0.0,
            buy_count=0,
        )

    common = prices.index.intersection(vix.index)
    prices_aligned = prices.loc[common]
    vix_aligned = vix.loc[common]
    accrual_days = set(first_trading_days_of_month(common))

    rows: list[dict[str, object]] = []
    shares = 0.0
    cash = 0.0
    invested = 0.0
    buy_count = 0

    for day in common:
        price_f = float(prices_aligned.loc[day])
        vix_f = float(vix_aligned.loc[day])

        if day in accrual_days and monthly_amount > 0:
            cash += monthly_amount
            invested += monthly_amount

        is_buy = False
        if vix_f >= vix_threshold and cash > 0 and price_f > 0:
            shares += cash / price_f
            cash = 0.0
            is_buy = True
            buy_count += 1

        rows.append({
            "date": day,
            "shares": shares,
            "cash": cash,
            "value": shares * price_f + cash,
            "buy": is_buy,
            "invested": invested,
        })

    timeline = pd.DataFrame(rows).set_index("date")
    return SimulationResult(
        timeline=timeline,
        final_value=float(timeline["value"].iloc[-1]),
        total_invested=float(timeline["invested"].iloc[-1]),
        buy_count=buy_count,
    )


def compute_cagr(start_value: float, end_value: float, years: float) -> float:
    """Compound annual growth rate. Returns 0 for nonsensical inputs."""
    if start_value <= 0 or years <= 0 or end_value <= 0:
        return 0.0
    return (end_value / start_value) ** (1.0 / years) - 1.0


def fetch_history_raw(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Pull daily close prices via yfinance. Returns a DataFrame with a single close column."""
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    return extract_close_frame(df)


def extract_close_frame(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        close_col = next((column for column in df.columns if column[0] == "Close"), None)
        if close_col is None:
            return pd.DataFrame()
        close = df[close_col]
    else:
        if "Close" not in df.columns:
            return pd.DataFrame()
        close = df["Close"]

    out = pd.DataFrame({"close": close})
    out.index.name = "Date"
    return out


def range_scale(series: pd.Series) -> pd.Series:
    """Rescale a series to [0, 100] over its own min/max."""
    clean = series.dropna()
    if clean.empty:
        return series
    lo = float(clean.min())
    hi = float(clean.max())
    if hi == lo:
        return pd.Series([50.0] * len(series), index=series.index)
    return (series - lo) / (hi - lo) * 100.0


def build_vix_comparison_view_model(
    *,
    ticker: str,
    prices: pd.Series,
    vix: pd.Series,
    monthly_amount: float,
    vix_threshold: float,
) -> VixComparisonViewModel:
    prices_aligned, vix_aligned = align_history(prices, vix)
    if len(prices_aligned) < 30:
        raise ValueError(f"기간이 너무 짧습니다 (거래일 {len(prices_aligned)}일).")

    dca = simulate_dca(prices_aligned, monthly_amount)
    vix_strategy = simulate_vix_lumpsum(
        prices_aligned,
        vix_aligned,
        monthly_amount,
        vix_threshold,
    )
    years = (prices_aligned.index.max() - prices_aligned.index.min()).days / 365.25
    dca_cagr = compute_cagr(dca.total_invested, dca.final_value, years)
    vix_cagr = compute_cagr(vix_strategy.total_invested, vix_strategy.final_value, years)

    return VixComparisonViewModel(
        ticker=ticker,
        vix_threshold=vix_threshold,
        prices=prices_aligned,
        vix=vix_aligned,
        dca=dca,
        vix_strategy=vix_strategy,
        years=years,
        dca_cagr=dca_cagr,
        vix_cagr=vix_cagr,
        start_date=prices_aligned.index.min().date(),
        end_date=prices_aligned.index.max().date(),
        trading_days=len(prices_aligned),
        normalized_rows=normalized_history_rows(ticker, prices_aligned, vix_aligned),
        portfolio_rows=strategy_timeline_rows(
            dca,
            vix_strategy,
            value_column="value",
            output_column="가치($)",
        ),
        cash_rows=strategy_timeline_rows(
            dca,
            vix_strategy,
            value_column="cash",
            output_column="현금($)",
        ),
        price_rows=price_history_rows(prices_aligned),
        buy_marker_rows=buy_marker_rows(prices_aligned, vix_strategy),
    )


def align_history(prices: pd.Series, vix: pd.Series) -> tuple[pd.Series, pd.Series]:
    common = prices.index.intersection(vix.index)
    return prices.loc[common], vix.loc[common]


def normalized_history_rows(
    ticker: str,
    prices: pd.Series,
    vix: pd.Series,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    labels = ((f"{ticker} 가격", range_scale(prices)), ("VIX", range_scale(vix)))
    for label, series in labels:
        rows.extend(
            {"Date": day, "시리즈": label, "정규화": float(value)}
            for day, value in series.dropna().items()
        )
    return rows


def strategy_timeline_rows(
    dca: SimulationResult,
    vix_strategy: SimulationResult,
    *,
    value_column: str,
    output_column: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    strategy_labels = (("매월 매수", dca), ("VIX 일시매수", vix_strategy))
    for label, result in strategy_labels:
        if result.timeline.empty:
            continue
        rows.extend(
            {"Date": day, "전략": label, output_column: float(value)}
            for day, value in result.timeline[value_column].items()
        )
    return rows


def price_history_rows(prices: pd.Series) -> list[dict[str, object]]:
    return [{"Date": day, "price": float(price)} for day, price in prices.items()]


def buy_marker_rows(
    prices: pd.Series,
    vix_strategy: SimulationResult,
) -> list[dict[str, object]]:
    if vix_strategy.timeline.empty:
        return []
    buy_dates = vix_strategy.timeline[vix_strategy.timeline["buy"]].index
    return [
        {"Date": day, "price": float(price)}
        for day, price in prices.reindex(buy_dates).dropna().items()
    ]
