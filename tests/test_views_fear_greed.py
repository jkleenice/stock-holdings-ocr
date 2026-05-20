from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

from holdings_ocr.market_sentiment import (
    bar_color,
    build_fng_panel_view_model,
    fetch_fng_raw,
    fng_history_as_of,
    korean_label,
    market_status_summary,
    metric_delta,
    metric_value,
)


def test_bar_color_extreme_fear_red():
    assert bar_color(0) == "#e45756"
    assert bar_color(24) == "#e45756"


def test_bar_color_fear_orange():
    assert bar_color(25) == "#f4a261"
    assert bar_color(44) == "#f4a261"


def test_bar_color_neutral_yellow():
    assert bar_color(45) == "#e9c46a"
    assert bar_color(54) == "#e9c46a"


def test_bar_color_greed_yellow_green():
    assert bar_color(55) == "#9acd32"
    assert bar_color(74) == "#9acd32"


def test_bar_color_extreme_greed_green():
    assert bar_color(75) == "#2ca02c"
    assert bar_color(100) == "#2ca02c"


@pytest.mark.parametrize("english,korean", [
    ("Extreme Fear", "극도의 공포"),
    ("Fear", "공포"),
    ("Neutral", "중립"),
    ("Greed", "탐욕"),
    ("Extreme Greed", "극도의 탐욕"),
])
def test_korean_label_translates_known_classifications(english, korean):
    assert korean_label(english) == korean


def test_korean_label_passes_through_unknown():
    assert korean_label("Anything Else") == "Anything Else"


def test_fetch_fng_raw_parses_alternative_me_response(monkeypatch):
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "name": "Fear and Greed Index",
        "data": [
            {"value": "42", "value_classification": "Fear", "timestamp": "1700000000", "time_until_update": "12345"},
            {"value": "55", "value_classification": "Greed", "timestamp": "1699913600"},
        ],
    }
    fake_response.raise_for_status = MagicMock()
    captured: dict = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        return fake_response

    monkeypatch.setattr("holdings_ocr.market_sentiment.requests.get", fake_get)

    result = fetch_fng_raw(limit=2)
    assert captured["url"] == "https://api.alternative.me/fng/"
    assert captured["params"] == {"limit": 2}
    assert captured["timeout"] == 10
    assert len(result) == 2
    assert result[0]["value"] == "42"
    assert result[0]["value_classification"] == "Fear"


def test_fetch_fng_raw_raises_on_http_error(monkeypatch):
    import requests as _requests

    fake_response = MagicMock()
    fake_response.raise_for_status.side_effect = _requests.HTTPError("502 Bad Gateway")
    monkeypatch.setattr("holdings_ocr.market_sentiment.requests.get", lambda *a, **kw: fake_response)

    with pytest.raises(_requests.HTTPError):
        fetch_fng_raw(limit=1)


def _fng_item(value: str, day: str) -> dict:
    timestamp = int(datetime.strptime(day, "%Y-%m-%d").timestamp())
    return {
        "value": value,
        "value_classification": "Fear",
        "timestamp": str(timestamp),
    }


def test_fng_history_as_of_uses_exact_matching_date_first():
    data = [
        _fng_item("50", "2024-01-03"),
        _fng_item("40", "2024-01-02"),
        _fng_item("30", "2024-01-01"),
    ]

    result = fng_history_as_of(data, date(2024, 1, 3))

    assert [item["value"] for item in result] == ["50", "40", "30"]


def test_fng_history_as_of_falls_back_to_previous_date():
    data = [
        _fng_item("60", "2024-01-05"),
        _fng_item("40", "2024-01-03"),
        _fng_item("20", "2024-01-01"),
    ]

    result = fng_history_as_of(data, date(2024, 1, 4))

    assert [item["value"] for item in result] == ["40", "20"]


def test_metric_value_preserves_zero():
    """Critical: 0 (Extreme Fear bottom) must not be replaced by em-dash."""
    assert metric_value(0) == 0


def test_metric_value_preserves_hundred():
    assert metric_value(100) == 100


def test_metric_value_none_becomes_dash():
    assert metric_value(None) == "—"


def test_metric_delta_signed_difference():
    assert metric_delta(50, 30) == 20
    assert metric_delta(30, 50) == -20


def test_metric_delta_prior_zero_does_not_fallthrough_to_none():
    """If yesterday was 0, today's delta should still compute (not None)."""
    assert metric_delta(15, 0) == 15


def test_metric_delta_none_prior_returns_none():
    assert metric_delta(50, None) is None


def test_market_status_summary_combines_fng_and_worst_drawdown():
    data = [{"value": "23", "value_classification": "Extreme Fear"}]
    rows = [{"티커": "NVDA", "기준일 하락률": -31.25}]

    summary = market_status_summary(data, rows)

    assert "극도의 공포 23점" in summary
    assert "NVDA -31.25%" in summary


def test_market_status_summary_handles_empty_state():
    summary = market_status_summary([], [])

    assert "기준일 상태를 한 줄로 요약" in summary


def test_build_fng_panel_view_model_keeps_zero_metric_values():
    data = [
        _fng_item("15", "2024-01-03"),
        _fng_item("0", "2024-01-02"),
    ]

    view_model = build_fng_panel_view_model(data)

    assert view_model.has_data is True
    assert view_model.value == 15
    assert view_model.metrics[0].value == 0
    assert view_model.metrics[0].delta == 15
