import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from holdings_ocr.schemas import Holding, HoldingsSnapshot
from views.holdings import (
    PROMPT_FINGERPRINT,
    _category_options,
    _content_hash,
    _clear_current_holdings,
    _extract_with_disk_cache,
    _format_money,
    _format_pct,
    _format_pnl,
    _group_uncategorized_holdings,
    _holding_category_keys,
    _load_current_holdings,
    _load_user_category_rules,
    _save_current_holdings,
    _save_user_category_rules,
    _upsert_user_category_rule,
    _user_category_mapping,
)


def test_format_money_with_value():
    assert _format_money(Decimal("123456")) == "123,456원"


def test_format_money_none_renders_dash():
    assert _format_money(None) == "-"


def test_format_money_zero():
    assert _format_money(Decimal("0")) == "0원"


def test_format_pnl_positive_uses_triangle_up():
    result = _format_pnl(Decimal("1500"))
    assert result.startswith("▲")
    assert "1,500" in result
    assert "원" in result


def test_format_pnl_negative_uses_triangle_down_and_strips_sign():
    result = _format_pnl(Decimal("-2000"))
    assert result.startswith("▼")
    assert "2,000" in result
    assert "-" not in result  # absolute value shown


def test_format_pnl_zero_no_triangle():
    assert _format_pnl(Decimal("0")) == "0원"


def test_format_pnl_none_renders_dash():
    assert _format_pnl(None) == "-"


def test_format_pct_two_decimal_places():
    assert _format_pct(Decimal("17.4567")) == "17.46%"


def test_format_pct_negative():
    assert _format_pct(Decimal("-32.91")) == "-32.91%"


def test_format_pct_none_renders_dash():
    assert _format_pct(None) == "-"


def test_format_pct_zero():
    assert _format_pct(Decimal("0")) == "0.00%"


@pytest.mark.parametrize("value,expected_prefix", [
    (Decimal("1"), "▲"),
    (Decimal("100000000"), "▲"),
    (Decimal("-1"), "▼"),
    (Decimal("-9999999"), "▼"),
])
def test_format_pnl_sign_indicator(value, expected_prefix):
    assert _format_pnl(value).startswith(expected_prefix)


def test_prompt_fingerprint_is_sixteen_hex_chars():
    """Cache invalidates on prompt changes via this fingerprint embedded in the cache key."""
    assert len(PROMPT_FINGERPRINT) == 16
    int(PROMPT_FINGERPRINT, 16)  # raises ValueError if not hex


# ── _content_hash ────────────────────────────────────────────────


def test_content_hash_same_inputs_produce_same_key():
    a = _content_hash(b"image-bytes", "gpt-4o", "fp1")
    b = _content_hash(b"image-bytes", "gpt-4o", "fp1")
    assert a == b


def test_content_hash_different_bytes_produce_different_keys():
    a = _content_hash(b"image-a", "gpt-4o", "fp1")
    b = _content_hash(b"image-b", "gpt-4o", "fp1")
    assert a != b


def test_content_hash_different_model_produces_different_key():
    a = _content_hash(b"img", "gpt-4o", "fp1")
    b = _content_hash(b"img", "gpt-4o-mini", "fp1")
    assert a != b


def test_content_hash_different_prompt_fp_produces_different_key():
    a = _content_hash(b"img", "gpt-4o", "fp1")
    b = _content_hash(b"img", "gpt-4o", "fp2")
    assert a != b


def test_content_hash_is_64_hex_chars():
    h = _content_hash(b"img", "gpt-4o", "fp")
    int(h, 16)
    assert len(h) == 64


# ── _extract_with_disk_cache ─────────────────────────────────────


def _make_fake_snapshot(source: str) -> HoldingsSnapshot:
    return HoldingsSnapshot(
        source=source,
        extracted_at=datetime.now(timezone.utc),
        holdings=[],
        broker_hint=None,
        raw_text="",
    )


def test_disk_cache_returns_existing_file_without_calling_extractor(tmp_path: Path, monkeypatch):
    image_bytes = b"image-bytes-for-cache-hit"
    model = "gpt-4o"
    prompt_fp = "abc123"
    cache_key = _content_hash(image_bytes, model, prompt_fp)

    cache_dir = tmp_path / "snapshots"
    cache_dir.mkdir()
    cached_json = '{"holdings": [], "broker_hint": null, "raw_text": "cached"}'
    (cache_dir / f"{cache_key}.json").write_text(cached_json, encoding="utf-8")

    def fail_extract(*args, **kwargs):
        raise AssertionError("extract_from_image must not be called on cache hit")

    monkeypatch.setattr("views.holdings.extract_from_image", fail_extract)

    result = _extract_with_disk_cache(image_bytes, ".png", model, prompt_fp, cache_dir=cache_dir)
    assert result == cached_json


def test_disk_cache_writes_new_file_on_miss(tmp_path: Path, monkeypatch):
    image_bytes = b"image-bytes-for-cache-miss"
    model = "gpt-4o"
    prompt_fp = "xyz789"
    cache_dir = tmp_path / "snapshots"

    def fake_extract(path, model):
        return _make_fake_snapshot(str(path))

    monkeypatch.setattr("views.holdings.extract_from_image", fake_extract)

    result = _extract_with_disk_cache(image_bytes, ".png", model, prompt_fp, cache_dir=cache_dir)
    parsed = json.loads(result)
    assert parsed["holdings"] == []

    cache_key = _content_hash(image_bytes, model, prompt_fp)
    cache_file = cache_dir / f"{cache_key}.json"
    assert cache_file.exists()
    assert cache_file.read_text(encoding="utf-8") == result


def test_disk_cache_second_call_hits_cache_and_skips_extractor(tmp_path: Path, monkeypatch):
    image_bytes = b"image-for-double-call"
    model = "gpt-4o"
    prompt_fp = "p1"
    cache_dir = tmp_path / "snapshots"

    call_count = {"n": 0}

    def fake_extract(path, model):
        call_count["n"] += 1
        return _make_fake_snapshot(str(path))

    monkeypatch.setattr("views.holdings.extract_from_image", fake_extract)

    _extract_with_disk_cache(image_bytes, ".png", model, prompt_fp, cache_dir=cache_dir)
    _extract_with_disk_cache(image_bytes, ".png", model, prompt_fp, cache_dir=cache_dir)
    _extract_with_disk_cache(image_bytes, ".png", model, prompt_fp, cache_dir=cache_dir)

    assert call_count["n"] == 1  # only first call hits the extractor


def test_disk_cache_ignores_filename_extension_for_key(tmp_path: Path, monkeypatch):
    """Same bytes uploaded as .png or .jpg should hit the same cache entry."""
    image_bytes = b"same-bytes-different-suffix"
    model = "gpt-4o"
    prompt_fp = "p1"
    cache_dir = tmp_path / "snapshots"

    call_count = {"n": 0}

    def fake_extract(path, model):
        call_count["n"] += 1
        return _make_fake_snapshot(str(path))

    monkeypatch.setattr("views.holdings.extract_from_image", fake_extract)

    _extract_with_disk_cache(image_bytes, ".png", model, prompt_fp, cache_dir=cache_dir)
    _extract_with_disk_cache(image_bytes, ".jpeg", model, prompt_fp, cache_dir=cache_dir)

    assert call_count["n"] == 1  # second call hits cache despite different suffix


# ── latest holdings persistence ─────────────────────────────────


def test_save_and_load_current_holdings_round_trip(tmp_path: Path):
    path = tmp_path / "current_holdings.json"
    snap = _make_fake_snapshot("first.png")
    snap_json = snap.model_dump_json(indent=2)

    _save_current_holdings([("first.png", snap, snap_json)], path=path)
    loaded = _load_current_holdings(path=path)

    assert len(loaded) == 1
    assert loaded[0][0] == "first.png"
    assert loaded[0][1].source == "first.png"
    assert json.loads(loaded[0][2])["holdings"] == []


def test_save_current_holdings_replaces_existing_file(tmp_path: Path):
    path = tmp_path / "current_holdings.json"
    first = _make_fake_snapshot("first.png")
    second = _make_fake_snapshot("second.png")

    _save_current_holdings([("first.png", first, first.model_dump_json())], path=path)
    _save_current_holdings([("second.png", second, second.model_dump_json())], path=path)

    loaded = _load_current_holdings(path=path)
    assert [name for name, _, _ in loaded] == ["second.png"]


def test_clear_current_holdings_removes_saved_file(tmp_path: Path):
    path = tmp_path / "current_holdings.json"
    snap = _make_fake_snapshot("first.png")
    _save_current_holdings([("first.png", snap, snap.model_dump_json())], path=path)

    _clear_current_holdings(path=path)

    assert _load_current_holdings(path=path) == []
    assert not path.exists()


def test_load_current_holdings_returns_empty_for_invalid_file(tmp_path: Path):
    path = tmp_path / "current_holdings.json"
    path.write_text("{not-json", encoding="utf-8")

    assert _load_current_holdings(path=path) == []


# ── user category rules ─────────────────────────────────────────


def test_holding_category_keys_include_symbol_and_raw_name():
    holding = Holding(raw_name="  신규 ETF  ", symbol="NEW", currency="KRW")

    assert _holding_category_keys(holding) == ["new", "신규 etf"]


def test_holding_category_keys_include_canonical_issuer_for_aliased_symbol():
    holding = Holding(raw_name="버크셔 B", symbol="BRK.B", currency="KRW")

    assert _holding_category_keys(holding) == ["berkshire hathaway", "brk.b", "버크셔 b"]


def test_save_and_load_user_category_rules_round_trip(tmp_path: Path):
    path = tmp_path / "category_overrides.json"
    rules = _upsert_user_category_rule(
        [],
        raw_name="신규 ETF",
        symbol="NEW",
        category="미국시장",
        keys=["NEW", "신규 ETF"],
    )

    _save_user_category_rules(rules, path=path)
    loaded = _load_user_category_rules(path=path)

    assert loaded == [{
        "raw_name": "신규 ETF",
        "symbol": "NEW",
        "category": "미국시장",
        "keys": ["new", "신규 etf"],
    }]
    assert _user_category_mapping(loaded) == {
        "new": "미국시장",
        "신규 etf": "미국시장",
    }


def test_user_category_rule_upsert_replaces_overlapping_keys():
    rules = _upsert_user_category_rule(
        [],
        raw_name="신규 ETF",
        symbol="NEW",
        category="미국시장",
        keys=["NEW", "신규 ETF"],
    )
    rules = _upsert_user_category_rule(
        rules,
        raw_name="신규 ETF",
        symbol="NEW",
        category="AI 반도체",
        keys=["new", "신규 ETF"],
    )

    assert len(rules) == 1
    assert rules[0]["category"] == "AI 반도체"


def test_category_options_keep_default_order_and_append_user_categories():
    assert _category_options(
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

    groups = _group_uncategorized_holdings(snapshot.holdings)

    assert len(groups) == 1
    assert groups[0]["count"] == 2
    assert groups[0]["market_value"] == Decimal("350")
    assert groups[0]["keys"] == ["new", "신규 etf", "new etf"]
