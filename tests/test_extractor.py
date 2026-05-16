from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from holdings_ocr.extractor import EXTRACTION_PROMPT, extract_from_image


class _FakeChoice:
    def __init__(self, content: str, finish_reason: str = "stop") -> None:
        self.message = SimpleNamespace(content=content)
        self.finish_reason = finish_reason


class _FakeResponse:
    def __init__(self, content: str, finish_reason: str = "stop") -> None:
        self.choices = [_FakeChoice(content, finish_reason)]


class _FakeCompletions:
    def __init__(self, payload: str, finish_reason: str = "stop") -> None:
        self._payload = payload
        self._finish_reason = finish_reason
        self.last_kwargs: dict | None = None

    def create(self, **kwargs: object) -> _FakeResponse:
        self.last_kwargs = kwargs
        return _FakeResponse(self._payload, self._finish_reason)


class _FakeChat:
    def __init__(self, payload: str, finish_reason: str = "stop") -> None:
        self.completions = _FakeCompletions(payload, finish_reason)


class _FakeClient:
    def __init__(self, payload: str, finish_reason: str = "stop") -> None:
        self.chat = _FakeChat(payload, finish_reason)


def test_extract_from_image_preserves_korean_rows(tmp_path: Path):
    image = tmp_path / "sample.png"
    image.write_bytes(b"fake-image")
    payload = """
    {
      "holdings": [
        {
          "raw_name": "알파벳 A",
          "symbol": null,
          "quantity": null,
          "market_value": 1200000,
          "currency": "KRW",
          "account": "키움증권",
          "unrealized_pnl": 100000,
          "unrealized_pnl_pct": 9.1
        },
        {
          "raw_name": "알파벳 C",
          "symbol": null,
          "quantity": null,
          "market_value": 800000,
          "currency": "KRW",
          "account": "키움증권",
          "unrealized_pnl": -20000,
          "unrealized_pnl_pct": -2.4
        }
      ],
      "broker_hint": "키움증권",
      "raw_text": "알파벳 A 알파벳 C"
    }
    """
    snapshot = extract_from_image(image, client=_FakeClient(payload))

    assert [holding.raw_name for holding in snapshot.holdings] == ["알파벳 A", "알파벳 C"]
    assert all(holding.symbol is None for holding in snapshot.holdings)
    assert all(holding.quantity is None for holding in snapshot.holdings)
    assert all(holding.currency == "KRW" for holding in snapshot.holdings)
    assert snapshot.broker_hint == "키움증권"
    assert snapshot.raw_text == "알파벳 A 알파벳 C"


def test_extraction_prompt_contains_korean_guardrails():
    assert "Preserve visible Korean names exactly" in EXTRACTION_PROMPT
    assert "If the screen shows values in 원, ₩, or KRW, emit `currency` as `KRW`." in EXTRACTION_PROMPT
    assert "If a ticker is not explicitly visible, `symbol` must be null." in EXTRACTION_PROMPT
    assert "If quantity is not visible, set `quantity` to null." in EXTRACTION_PROMPT


def test_extract_passes_temperature_zero_for_determinism(tmp_path: Path):
    """OCR must be deterministic — temperature=0 keeps repeated calls identical."""
    image = tmp_path / "sample.png"
    image.write_bytes(b"fake")
    client = _FakeClient('{"holdings": [], "broker_hint": null, "raw_text": ""}')
    extract_from_image(image, client=client)
    assert client.chat.completions.last_kwargs is not None
    assert client.chat.completions.last_kwargs["temperature"] == 0


def test_extract_raises_on_truncated_response(tmp_path: Path):
    """finish_reason=length means the JSON is incomplete — must fail loudly."""
    image = tmp_path / "sample.png"
    image.write_bytes(b"fake")
    truncated_json = '{"holdings": [{"raw_name": "A", "marke'  # cut mid-key
    client = _FakeClient(truncated_json, finish_reason="length")
    with pytest.raises(ValueError, match="finish_reason=length"):
        extract_from_image(image, client=client)


def test_extract_raises_on_invalid_json_with_preview(tmp_path: Path):
    """Bad JSON must surface a preview of what the model said, not a bare JSONDecodeError."""
    image = tmp_path / "sample.png"
    image.write_bytes(b"fake")
    client = _FakeClient("this is not JSON at all, sorry")
    with pytest.raises(ValueError, match="not valid JSON") as exc_info:
        extract_from_image(image, client=client)
    # Preview must include some of the offending text so the user can diagnose
    assert "this is not JSON" in str(exc_info.value)
