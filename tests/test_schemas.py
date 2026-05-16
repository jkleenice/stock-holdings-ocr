from datetime import datetime, timezone
from decimal import Decimal

import pytest

from holdings_ocr.schemas import AggregatedPosition, Holding, HoldingsSnapshot


def test_snapshot_roundtrips_through_json():
    snap = HoldingsSnapshot(
        source="x.png",
        extracted_at=datetime.now(timezone.utc),
        holdings=[Holding(raw_name="AAPL", symbol="AAPL", quantity=Decimal("3"), market_value=Decimal("600"), currency="usd")],
    )
    payload = snap.model_dump_json()
    restored = HoldingsSnapshot.model_validate_json(payload)
    assert restored.holdings[0].symbol == "AAPL"
    assert restored.holdings[0].quantity == Decimal("3")
    assert restored.holdings[0].currency == "USD"


def test_invalid_currency_is_rejected():
    with pytest.raises(ValueError):
        Holding(raw_name="AAPL", market_value=Decimal("100"), currency="US")


def test_aggregated_position_allows_unknown_quantity_and_weight():
    position = AggregatedPosition(
        issuer="Alphabet",
        display_names=["알파벳 A", "알파벳 C"],
        symbols=[],
        total_quantity=None,
        total_market_value=Decimal("1000"),
        weight_pct=Decimal("50"),
        currency="KRW",
        accounts=["키움증권"],
        unrealized_pnl=Decimal("100"),
        unrealized_pnl_pct=Decimal("10"),
    )
    assert position.total_quantity is None
    assert position.weight_pct == Decimal("50")
