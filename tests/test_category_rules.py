from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from holdings_ocr.category_rules import (
    category_options,
    group_uncategorized_holdings,
    holding_category_keys,
    load_user_category_rules,
    save_user_category_rules,
    upsert_user_category_rule,
    user_category_mapping,
)
from holdings_ocr.schemas import Holding, HoldingsSnapshot


def test_holding_category_keys_include_symbol_and_raw_name():
    holding = Holding(raw_name="  신규 ETF  ", symbol="NEW", currency="KRW")

    assert holding_category_keys(holding) == ["new", "신규 etf"]


def test_holding_category_keys_include_canonical_issuer_for_aliased_symbol():
    holding = Holding(raw_name="버크셔 B", symbol="BRK.B", currency="KRW")

    assert holding_category_keys(holding) == ["berkshire hathaway", "brk.b", "버크셔 b"]


def test_save_and_load_user_category_rules_round_trip(tmp_path: Path):
    path = tmp_path / "category_overrides.json"
    rules = upsert_user_category_rule(
        [],
        raw_name="신규 ETF",
        symbol="NEW",
        category="미국시장",
        keys=["NEW", "신규 ETF"],
    )

    save_user_category_rules(rules, path=path)
    loaded = load_user_category_rules(path=path)

    assert len(loaded) == 1
    assert loaded[0].raw_name == "신규 ETF"
    assert loaded[0].symbol == "NEW"
    assert loaded[0].category == "미국시장"
    assert loaded[0].keys == ["new", "신규 etf"]
    assert user_category_mapping(loaded) == {
        "new": "미국시장",
        "신규 etf": "미국시장",
    }


def test_user_category_rule_upsert_replaces_overlapping_keys():
    rules = upsert_user_category_rule(
        [],
        raw_name="신규 ETF",
        symbol="NEW",
        category="미국시장",
        keys=["NEW", "신규 ETF"],
    )
    rules = upsert_user_category_rule(
        rules,
        raw_name="신규 ETF",
        symbol="NEW",
        category="AI 반도체",
        keys=["new", "신규 ETF"],
    )

    assert len(rules) == 1
    assert rules[0].category == "AI 반도체"


def test_category_options_keep_default_order_and_append_user_categories():
    assert category_options(
        {"alphabet": "구글", "apple": "애플"},
        {"new": "구글", "other": "새 테마"},
    ) == ["구글", "애플", "새 테마"]


def test_group_uncategorized_holdings_groups_by_symbol_and_sums_market_value():
    snapshot = HoldingsSnapshot(
        source="manual",
        extracted_at=datetime.now(timezone.utc),
        holdings=[
            {
                "raw_name": "신규 ETF",
                "symbol": "NEW",
                "market_value": Decimal("100"),
                "currency": "KRW",
            },
            {
                "raw_name": "NEW ETF",
                "symbol": "NEW",
                "market_value": Decimal("250"),
                "currency": "KRW",
            },
        ],
    )

    groups = group_uncategorized_holdings(snapshot.holdings)

    assert len(groups) == 1
    assert groups[0].count == 2
    assert groups[0].market_value == Decimal("350")
    assert groups[0].keys == ["new", "신규 etf", "new etf"]
