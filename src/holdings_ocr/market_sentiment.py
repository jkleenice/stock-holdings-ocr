from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd
import requests


FNG_URL = "https://api.alternative.me/fng/"


@dataclass(frozen=True)
class FearGreedMetric:
    label: str
    value: int | str
    delta: int | None


@dataclass(frozen=True)
class FearGreedPanelViewModel:
    has_data: bool
    value: int | None
    classification: str
    label_ko: str
    as_of_date: str
    metrics: tuple[FearGreedMetric, ...]
    history_rows: list[dict[str, object]]


def fetch_fng_raw(limit: int = 30) -> list[dict]:
    """Pull Crypto Fear & Greed history from alternative.me."""
    response = requests.get(FNG_URL, params={"limit": limit}, timeout=10)
    response.raise_for_status()
    return response.json()["data"]


def bar_color(value: int) -> str:
    if value < 25:
        return "#e45756"
    if value < 45:
        return "#f4a261"
    if value < 55:
        return "#e9c46a"
    if value < 75:
        return "#9acd32"
    return "#2ca02c"


def korean_label(classification: str) -> str:
    mapping = {
        "Extreme Fear": "극도의 공포",
        "Fear": "공포",
        "Neutral": "중립",
        "Greed": "탐욕",
        "Extreme Greed": "극도의 탐욕",
    }
    return mapping.get(classification, classification)


def metric_value(value: int | None) -> int | str:
    return value if value is not None else "—"


def metric_delta(current: int, prior: int | None) -> int | None:
    return (current - prior) if prior is not None else None


def fng_history_df(data: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(fng_history_rows(data))


def fng_history_rows(data: list[dict]) -> list[dict[str, object]]:
    return [
        {
            "날짜": datetime.fromtimestamp(int(item["timestamp"])),
            "지수": int(item["value"]),
            "분류": item["value_classification"],
        }
        for item in reversed(data)
    ]


def fng_item_date(item: dict) -> date:
    return datetime.fromtimestamp(int(item["timestamp"])).date()


def fng_history_as_of(data: list[dict], as_of_date: date) -> list[dict]:
    sorted_data = sorted(data, key=lambda item: int(item["timestamp"]), reverse=True)
    return [item for item in sorted_data if fng_item_date(item) <= as_of_date]


def get_fng_at(data: list[dict], idx: int) -> int | None:
    if idx >= len(data):
        return None
    return int(data[idx]["value"])


def build_fng_panel_view_model(data: list[dict]) -> FearGreedPanelViewModel:
    if not data:
        return FearGreedPanelViewModel(
            has_data=False,
            value=None,
            classification="",
            label_ko="",
            as_of_date="",
            metrics=(),
            history_rows=[],
        )

    current = data[0]
    value = int(current["value"])
    classification = current["value_classification"]
    metric_specs = (("전일", 1), ("7일 전", 7), ("30일 전", 29))
    metrics = tuple(
        FearGreedMetric(
            label=label,
            value=metric_value(get_fng_at(data, idx)),
            delta=metric_delta(value, get_fng_at(data, idx)),
        )
        for label, idx in metric_specs
    )

    return FearGreedPanelViewModel(
        has_data=True,
        value=value,
        classification=classification,
        label_ko=korean_label(classification),
        as_of_date=fng_item_date(current).isoformat(),
        metrics=metrics,
        history_rows=fng_history_rows(data),
    )


def market_status_summary(data: list[dict], drawdown_rows: list[dict]) -> str:
    parts = []
    if data:
        current = data[0]
        value = int(current["value"])
        parts.append(f"코인 심리는 {korean_label(current['value_classification'])} {value}점")
    if drawdown_rows:
        worst = drawdown_rows[0]
        worst_amount = max(0.0, -float(worst["기준일 하락률"]))
        parts.append(f"가장 많이 빠진 티커는 {worst['티커']} -{worst_amount:.2f}%")
    if not parts:
        return "공포·탐욕 지수 또는 추적 티커를 불러오면 기준일 상태를 한 줄로 요약해요."
    return " · ".join(parts)
