from decimal import Decimal

import pytest

from views.holdings import _format_money, _format_pct, _format_pnl


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
