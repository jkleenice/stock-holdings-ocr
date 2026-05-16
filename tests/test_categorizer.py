from decimal import Decimal
from pathlib import Path

import pytest

from holdings_ocr.categorizer import (
    categorize,
    category_pnl_summary,
    category_totals,
    load_categories,
)
from holdings_ocr.schemas import Holding


def test_load_categories_normalizes_issuer_keys(tmp_path: Path):
    path = tmp_path / "categories.yaml"
    path.write_text("구글:\n  - Alphabet\n  - \"ACE 구글밸류체인액티브\"\n")
    mapping = load_categories(path)
    assert mapping["alphabet"] == "구글"
    assert mapping["ace 구글밸류체인액티브"] == "구글"


def test_load_categories_rejects_overlapping_issuers(tmp_path: Path):
    path = tmp_path / "categories.yaml"
    path.write_text("구글:\n  - Alphabet\n미국시장:\n  - Alphabet\n")
    with pytest.raises(ValueError, match="overlapping entries"):
        load_categories(path)


def test_categorize_routes_google_share_classes_to_single_bucket():
    holdings = [
        Holding(raw_name="알파벳 A", market_value=Decimal("2481408"), currency="KRW"),
        Holding(raw_name="알파벳 C", market_value=Decimal("588668"), currency="KRW"),
        Holding(raw_name="ACE 구글밸류체인액티브", market_value=Decimal("2409690"), currency="KRW"),
    ]
    buckets, uncategorized = categorize(
        holdings,
        aliases={},
        korean_names={"알파벳 a": "Alphabet", "알파벳 c": "Alphabet"},
        categories={"alphabet": "구글", "ace 구글밸류체인액티브": "구글"},
    )
    assert uncategorized == []
    assert len(buckets["구글"]) == 3
    assert category_totals(buckets)["구글"] == Decimal("5479766")


def test_categorize_does_not_assign_sp500_to_google():
    """S&P 500 contains Google but must not appear in the Google bucket."""
    holdings = [
        Holding(raw_name="알파벳 A", market_value=Decimal("100"), currency="KRW"),
        Holding(raw_name="ACE 미국S&P500", market_value=Decimal("200"), currency="KRW"),
    ]
    buckets, _ = categorize(
        holdings,
        aliases={},
        korean_names={"알파벳 a": "Alphabet"},
        categories={"alphabet": "구글", "ace 미국s&p500": "미국시장"},
    )
    assert [h.raw_name for h in buckets["구글"]] == ["알파벳 A"]
    assert [h.raw_name for h in buckets["미국시장"]] == ["ACE 미국S&P500"]


def test_categorize_collects_unknown_holdings_as_uncategorized():
    holdings = [
        Holding(raw_name="새로운 ETF", market_value=Decimal("100"), currency="KRW"),
    ]
    _, uncategorized = categorize(
        holdings,
        aliases={},
        korean_names={},
        categories={"alphabet": "구글"},
    )
    assert len(uncategorized) == 1
    assert uncategorized[0].raw_name == "새로운 ETF"


def test_category_pnl_summary_computes_value_weighted_return():
    buckets = {
        "구글": [
            Holding(
                raw_name="알파벳 A",
                market_value=Decimal("2481408"),
                unrealized_pnl=Decimal("540549"),
                currency="KRW",
            ),
            Holding(
                raw_name="알파벳 C",
                market_value=Decimal("588668"),
                unrealized_pnl=Decimal("174894"),
                currency="KRW",
            ),
        ],
    }
    summary = category_pnl_summary(buckets)
    total_pnl, return_pct = summary["구글"]
    assert total_pnl == Decimal("715443")
    # cost = 3,070,076 - 715,443 = 2,354,633 → return ≈ 30.38%
    assert return_pct.quantize(Decimal("0.01")) == Decimal("30.38")


def test_category_pnl_summary_returns_none_when_any_pnl_missing():
    buckets = {
        "X": [
            Holding(raw_name="A", market_value=Decimal("100"), unrealized_pnl=Decimal("10"), currency="KRW"),
            Holding(raw_name="B", market_value=Decimal("200"), unrealized_pnl=None, currency="KRW"),
        ],
    }
    summary = category_pnl_summary(buckets)
    assert summary["X"] == (None, None)


def test_default_categories_yaml_loads_without_overlaps():
    """Smoke test: ensure the project-default categories.yaml file is internally consistent."""
    mapping = load_categories()
    assert mapping  # not empty
    # 알파벳 (via Alphabet issuer) must route to 구글, not 미국시장
    assert mapping.get("alphabet") == "구글"
