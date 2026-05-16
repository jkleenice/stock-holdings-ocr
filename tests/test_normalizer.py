from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from holdings_ocr.normalizer import aggregate_by_issuer, load_korean_name_aliases
from holdings_ocr.schemas import Holding, HoldingsSnapshot


def _snap(holdings: list[Holding]) -> HoldingsSnapshot:
    return HoldingsSnapshot(
        source="test.png",
        extracted_at=datetime.now(timezone.utc),
        holdings=holdings,
    )


def test_alphabet_class_a_and_c_are_merged():
    snap = _snap(
        [
            Holding(raw_name="GOOGL", symbol="GOOGL", quantity=Decimal("10"), market_value=Decimal("1500"), currency="USD"),
            Holding(raw_name="GOOG", symbol="GOOG", quantity=Decimal("5"), market_value=Decimal("750"), currency="USD"),
            Holding(raw_name="AAPL", symbol="AAPL", quantity=Decimal("2"), market_value=Decimal("400"), currency="USD"),
        ]
    )
    aliases = {"GOOGL": "Alphabet", "GOOG": "Alphabet"}
    by_issuer = {p.issuer: p for p in aggregate_by_issuer(snap, aliases)}

    assert by_issuer["Alphabet"].total_quantity == Decimal("15")
    assert by_issuer["Alphabet"].total_market_value == Decimal("2250")
    assert by_issuer["Alphabet"].symbols == ["GOOG", "GOOGL"]
    assert "AAPL" in by_issuer


def test_same_symbol_in_two_accounts_is_collapsed_and_keeps_accounts():
    snap = _snap(
        [
            Holding(raw_name="AAPL", symbol="AAPL", quantity=Decimal("3"), market_value=Decimal("600"), account="Brokerage", currency="USD"),
            Holding(raw_name="AAPL", symbol="AAPL", quantity=Decimal("2"), market_value=Decimal("400"), account="IRA", currency="USD"),
        ]
    )
    positions = aggregate_by_issuer(snap, aliases={})
    assert len(positions) == 1
    assert positions[0].total_quantity == Decimal("5")
    assert positions[0].total_market_value == Decimal("1000")
    assert positions[0].accounts == ["Brokerage", "IRA"]


def test_unknown_symbol_passes_through_as_its_own_issuer():
    snap = _snap([Holding(raw_name="UNKN", symbol="UNKN", quantity=Decimal("1"), market_value=Decimal("100"), currency="USD")])
    positions = aggregate_by_issuer(snap, aliases={})
    assert len(positions) == 1
    assert positions[0].issuer == "UNKN"


def test_missing_quantity_stays_unknown_when_any_row_is_unknown():
    snap = _snap(
        [
            Holding(raw_name="AAPL", symbol="AAPL", quantity=None, market_value=Decimal("150"), currency="USD"),
            Holding(raw_name="AAPL", symbol="AAPL", quantity=Decimal("1"), market_value=Decimal("200"), currency="USD"),
        ]
    )
    positions = aggregate_by_issuer(snap, aliases={})
    assert positions[0].total_quantity is None
    assert positions[0].total_market_value == Decimal("350")


def test_korean_name_aliases_are_used_when_symbol_is_missing():
    snap = _snap(
        [
            Holding(raw_name="알파벳 A", quantity=None, market_value=Decimal("1000"), currency="KRW"),
            Holding(raw_name="알파벳 C", quantity=None, market_value=Decimal("500"), currency="KRW"),
        ]
    )
    positions = aggregate_by_issuer(snap, aliases={}, korean_names={"알파벳 a": "Alphabet", "알파벳 c": "Alphabet"})
    assert len(positions) == 1
    assert positions[0].issuer == "Alphabet"
    assert positions[0].display_names == ["알파벳 A", "알파벳 C"]
    assert positions[0].total_quantity is None


def test_symbol_alias_beats_korean_name_alias():
    snap = _snap(
        [Holding(raw_name="애플", symbol="GOOGL", market_value=Decimal("1000"), currency="USD")]
    )
    positions = aggregate_by_issuer(
        snap,
        aliases={"GOOGL": "Alphabet"},
        korean_names={"애플": "Apple"},
    )
    assert positions[0].issuer == "Alphabet"


def test_mixed_currency_within_issuer_raises_error():
    snap = _snap(
        [
            Holding(raw_name="AAPL", symbol="AAPL", market_value=Decimal("100"), currency="USD"),
            Holding(raw_name="애플", market_value=Decimal("200"), currency="KRW"),
        ]
    )
    with pytest.raises(ValueError, match="mixes currencies"):
        aggregate_by_issuer(snap, aliases={"AAPL": "Apple"}, korean_names={"애플": "Apple"})


def test_korean_name_alias_loader_normalizes_spacing(tmp_path: Path):
    path = tmp_path / "korean_names.yaml"
    path.write_text('Alphabet:\n  - "알파벳   A"\n')
    aliases = load_korean_name_aliases(path)
    assert aliases["알파벳 a"] == "Alphabet"
