from unittest.mock import MagicMock

import pytest

from views.fear_greed import (
    _bar_color,
    _fetch_fng_raw,
    _korean_label,
    _metric_delta,
    _metric_value,
)


def test_bar_color_extreme_fear_red():
    assert _bar_color(0) == "#e45756"
    assert _bar_color(24) == "#e45756"


def test_bar_color_fear_orange():
    assert _bar_color(25) == "#f4a261"
    assert _bar_color(44) == "#f4a261"


def test_bar_color_neutral_yellow():
    assert _bar_color(45) == "#e9c46a"
    assert _bar_color(54) == "#e9c46a"


def test_bar_color_greed_yellow_green():
    assert _bar_color(55) == "#9acd32"
    assert _bar_color(74) == "#9acd32"


def test_bar_color_extreme_greed_green():
    assert _bar_color(75) == "#2ca02c"
    assert _bar_color(100) == "#2ca02c"


@pytest.mark.parametrize("english,korean", [
    ("Extreme Fear", "극도의 공포"),
    ("Fear", "공포"),
    ("Neutral", "중립"),
    ("Greed", "탐욕"),
    ("Extreme Greed", "극도의 탐욕"),
])
def test_korean_label_translates_known_classifications(english, korean):
    assert _korean_label(english) == korean


def test_korean_label_passes_through_unknown():
    assert _korean_label("Anything Else") == "Anything Else"


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

    monkeypatch.setattr("views.fear_greed.requests.get", fake_get)

    result = _fetch_fng_raw(limit=2)
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
    monkeypatch.setattr("views.fear_greed.requests.get", lambda *a, **kw: fake_response)

    with pytest.raises(_requests.HTTPError):
        _fetch_fng_raw(limit=1)


def test_metric_value_preserves_zero():
    """Critical: 0 (Extreme Fear bottom) must not be replaced by em-dash."""
    assert _metric_value(0) == 0


def test_metric_value_preserves_hundred():
    assert _metric_value(100) == 100


def test_metric_value_none_becomes_dash():
    assert _metric_value(None) == "—"


def test_metric_delta_signed_difference():
    assert _metric_delta(50, 30) == 20
    assert _metric_delta(30, 50) == -20


def test_metric_delta_prior_zero_does_not_fallthrough_to_none():
    """If yesterday was 0, today's delta should still compute (not None)."""
    assert _metric_delta(15, 0) == 15


def test_metric_delta_none_prior_returns_none():
    assert _metric_delta(50, None) is None
