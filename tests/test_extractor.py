from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from holdings_ocr.extractor import EXTRACTION_PROMPT, extract_from_image


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = SimpleNamespace(content=content)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, payload: str) -> None:
        self._payload = payload

    def create(self, **_: object) -> _FakeResponse:
        return _FakeResponse(self._payload)


class _FakeChat:
    def __init__(self, payload: str) -> None:
        self.completions = _FakeCompletions(payload)


class _FakeClient:
    def __init__(self, payload: str) -> None:
        self.chat = _FakeChat(payload)


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
