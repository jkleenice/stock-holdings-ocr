from datetime import datetime, timezone
from decimal import Decimal

import pytest

from holdings_ocr.reporter import build_report, render_markdown
from holdings_ocr.schemas import Holding, HoldingsSnapshot


def test_report_totals_and_markdown_render():
    snap = HoldingsSnapshot(
        source="x.png",
        extracted_at=datetime.now(timezone.utc),
        holdings=[
            Holding(raw_name="GOOGL", symbol="GOOGL", quantity=Decimal("1"), market_value=Decimal("100"), currency="USD"),
            Holding(raw_name="GOOG", symbol="GOOG", quantity=Decimal("1"), market_value=Decimal("100"), currency="USD"),
            Holding(raw_name="AAPL", symbol="AAPL", quantity=Decimal("1"), market_value=Decimal("50"), currency="USD"),
        ],
    )
    report = build_report(snap, aliases={"GOOGL": "Alphabet", "GOOG": "Alphabet"})

    assert report.total_value == Decimal("250")
    assert report.positions[0].weight_pct == Decimal("80")
    md = render_markdown(report)
    assert "Alphabet" in md
    assert "AAPL" in md
    assert "80.00%" in md
    # Alphabet should appear before AAPL because it has the larger market value.
    assert md.index("Alphabet") < md.index("AAPL")


def test_markdown_renders_unknown_quantity_as_dash_and_hides_column_if_all_unknown():
    snap = HoldingsSnapshot(
        source="krw.png",
        extracted_at=datetime.now(timezone.utc),
        holdings=[
            Holding(raw_name="알파벳 A", quantity=None, market_value=Decimal("100"), currency="KRW"),
        ],
    )
    report = build_report(snap, aliases={}, korean_names={"알파벳 a": "Alphabet"})
    md = render_markdown(report)
    assert "| 발행사 | 표시명 | 평가금액 | 비중 | 손익 | 계좌 |" in md
    assert "| 발행사 | 표시명 | 수량 |" not in md


def test_report_raises_on_mixed_currencies():
    snap = HoldingsSnapshot(
        source="mixed.png",
        extracted_at=datetime.now(timezone.utc),
        holdings=[
            Holding(raw_name="AAPL", symbol="AAPL", quantity=Decimal("1"), market_value=Decimal("100"), currency="USD"),
            Holding(raw_name="005930", symbol="005930", quantity=Decimal("1"), market_value=Decimal("100000"), currency="KRW"),
        ],
    )
    with pytest.raises(ValueError, match="snapshot mixes currencies"):
        build_report(snap)
