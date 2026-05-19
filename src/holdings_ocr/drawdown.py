from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


TRACKED_TICKERS_SESSION_KEY = "drawdown_tracked_tickers"
TRACKED_TICKERS_CACHE_FILE = Path(".cache/drawdown/tickers.json")


@dataclass(frozen=True)
class DrawdownStats:
    current_price: float
    peak_price: float
    peak_date: pd.Timestamp
    drawdown_pct: float
    recovery_pct: float


def parse_ticker_input(value: str) -> list[str]:
    """Parse comma, whitespace, or newline separated tickers, deduped in input order."""
    normalized = value.replace(",", " ").replace(";", " ")
    tickers: list[str] = []
    seen: set[str] = set()
    for raw in normalized.split():
        ticker = raw.strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)
    return tickers


def load_tracked_tickers(path: Path = TRACKED_TICKERS_CACHE_FILE) -> list[str]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return parse_ticker_input(" ".join(str(item) for item in data))


def save_tracked_tickers(
    tickers: list[str],
    path: Path = TRACKED_TICKERS_CACHE_FILE,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(parse_ticker_input(" ".join(tickers)), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def to_yfinance_symbol(symbol: str) -> str:
    """Convert a user-entered symbol to the yfinance lookup form."""
    clean = symbol.strip().upper()
    if clean.isdigit() and len(clean) == 6:
        return f"{clean}.KS"
    return clean


def compute_drawdown_stats(prices: pd.Series) -> DrawdownStats:
    series = _clean_price_series(prices)
    if series.empty:
        raise ValueError("price series is empty")

    current_price = float(series.iloc[-1])
    peak_price = float(series.max())
    peak_date = pd.Timestamp(series.idxmax())
    drawdown_pct = (current_price / peak_price - 1.0) * 100.0
    recovery_pct = (peak_price / current_price - 1.0) * 100.0 if current_price > 0 else 0.0
    return DrawdownStats(
        current_price=current_price,
        peak_price=peak_price,
        peak_date=peak_date,
        drawdown_pct=drawdown_pct,
        recovery_pct=recovery_pct,
    )


def compute_drawdown_series(prices: pd.Series) -> pd.Series:
    series = _clean_price_series(prices)
    if series.empty:
        return pd.Series(dtype=float)
    return (series / series.cummax() - 1.0) * 100.0


def _clean_price_series(prices: pd.Series) -> pd.Series:
    series = pd.to_numeric(prices, errors="coerce").dropna()
    return series[series > 0]
