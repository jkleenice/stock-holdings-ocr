from datetime import datetime, timezone
from decimal import Decimal

from holdings_ocr.category_rules import upsert_user_category_rule
from holdings_ocr.holdings_service import (
    build_holdings_view_model,
    cost_basis_chart_data,
    format_money,
    format_pct,
    format_pnl,
    market_value_chart_rows,
    return_chart_rows,
    return_value_chart_rows,
)
from holdings_ocr.holdings_storage import SnapshotRecord
from holdings_ocr.schemas import Holding, HoldingsSnapshot


def _snapshot(source: str, holdings: list[Holding]) -> HoldingsSnapshot:
    return HoldingsSnapshot(
        source=source,
        extracted_at=datetime.now(timezone.utc),
        holdings=holdings,
        broker_hint=None,
        raw_text="",
    )


def _record(name: str, holdings: list[Holding]) -> SnapshotRecord:
    snapshot = _snapshot(name, holdings)
    return SnapshotRecord(name, snapshot, snapshot.model_dump_json())


def test_format_money_and_pnl_for_display_rows():
    assert format_money(Decimal("123456")) == "123,456원"
    assert format_money(None) == "-"
    assert format_pnl(Decimal("1500")).startswith("▲")
    assert format_pnl(Decimal("-2000")).startswith("▼")
    assert format_pnl(Decimal("0")) == "0원"
    assert format_pnl(None) == "-"
    assert format_pct(Decimal("17.4567")) == "17.46%"
    assert format_pct(None) == "-"


def test_build_holdings_view_model_keeps_uncategorized_until_rule_is_saved():
    records = [
        _record(
            "first.png",
            [
                Holding(
                    raw_name="알파벳 A",
                    market_value=Decimal("100"),
                    unrealized_pnl=Decimal("20"),
                    unrealized_pnl_pct=Decimal("25"),
                    currency="KRW",
                ),
                Holding(
                    raw_name="신규 ETF",
                    symbol="NEW",
                    market_value=Decimal("300"),
                    unrealized_pnl=Decimal("30"),
                    unrealized_pnl_pct=Decimal("11.11"),
                    currency="KRW",
                ),
            ],
        )
    ]

    view_model = build_holdings_view_model(
        records,
        user_category_rules=[],
        base_categories={"alphabet": "구글"},
    )

    assert view_model.total_holdings == 2
    assert [row["테마"] for row in view_model.category_rows] == ["구글"]
    assert view_model.category_rows[0]["비중"] == "100.00%"
    assert len(view_model.uncategorized_groups) == 1
    assert view_model.uncategorized_groups[0].raw_names == ["신규 ETF"]


def test_build_holdings_view_model_applies_user_rule_to_theme_summary_and_charts():
    records = [
        _record(
            "first.png",
            [
                Holding(
                    raw_name="알파벳 A",
                    market_value=Decimal("100"),
                    unrealized_pnl=Decimal("20"),
                    unrealized_pnl_pct=Decimal("25"),
                    currency="KRW",
                ),
            ],
        ),
        _record(
            "second.png",
            [
                Holding(
                    raw_name="신규 ETF",
                    symbol="NEW",
                    market_value=Decimal("300"),
                    unrealized_pnl=Decimal("30"),
                    unrealized_pnl_pct=Decimal("11.11"),
                    currency="KRW",
                ),
            ],
        ),
    ]
    rules = upsert_user_category_rule(
        [],
        raw_name="신규 ETF",
        symbol="NEW",
        category="미국시장",
        keys=["NEW", "신규 ETF"],
    )

    view_model = build_holdings_view_model(
        records,
        user_category_rules=rules,
        base_categories={"alphabet": "구글"},
    )

    assert view_model.uncategorized == []
    assert [row["테마"] for row in view_model.category_rows] == ["미국시장", "구글"]
    assert view_model.category_rows[0]["비중"] == "75.00%"
    assert view_model.holding_rows[0]["출처"] == "first.png"
    assert market_value_chart_rows(view_model)[0] == {"카테고리": "미국시장", "금액": 300.0}
    assert return_chart_rows(view_model)[0]["카테고리"] == "구글"
    assert return_value_chart_rows(view_model)[0]["카테고리"] == "미국시장"


def test_cost_basis_chart_data_skips_categories_with_missing_pnl():
    records = [
        _record(
            "first.png",
            [
                Holding(
                    raw_name="알파벳 A",
                    market_value=Decimal("100"),
                    unrealized_pnl=None,
                    currency="KRW",
                ),
                Holding(
                    raw_name="애플",
                    market_value=Decimal("200"),
                    unrealized_pnl=Decimal("20"),
                    currency="KRW",
                ),
            ],
        )
    ]

    view_model = build_holdings_view_model(
        records,
        user_category_rules=[],
        base_categories={"alphabet": "구글", "애플": "애플"},
    )
    chart_data = cost_basis_chart_data(view_model)

    assert chart_data.skipped == ["구글"]
    assert chart_data.ordered_categories == ["애플"]
    assert chart_data.long_rows == [
        {"카테고리": "애플", "구분": "원금", "금액": 180.0},
        {"카테고리": "애플", "구분": "보유금액", "금액": 200.0},
    ]
    assert chart_data.label_rows[0]["라벨"] == "+20원"
