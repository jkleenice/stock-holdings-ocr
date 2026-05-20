from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .categorizer import categorize, category_pnl_summary, category_totals, load_categories
from .category_rules import (
    CategoryRule,
    UncategorizedGroup,
    category_options,
    group_uncategorized_holdings,
    user_category_mapping,
)
from .holdings_storage import SnapshotRecord
from .schemas import Holding


@dataclass(frozen=True)
class CostBasisChartData:
    long_rows: list[dict[str, object]]
    label_rows: list[dict[str, object]]
    ordered_categories: list[str]
    skipped: list[str]


@dataclass(frozen=True)
class HoldingsViewModel:
    source_count: int
    total_holdings: int
    all_holdings: list[Holding]
    holding_rows: list[dict[str, str]]
    category_rows: list[dict[str, object]]
    category_buckets: dict[str, list[Holding]]
    category_options: list[str]
    uncategorized: list[Holding]
    uncategorized_groups: list[UncategorizedGroup]
    totals: dict[str, Decimal]
    pnl_summary: dict[str, tuple[Decimal | None, Decimal | None]]
    user_category_rules: list[CategoryRule]


def format_money(value: Decimal | None) -> str:
    if value is None:
        return "-"
    return f"{value:,}원"


def format_pnl(value: Decimal | None) -> str:
    if value is None:
        return "-"
    if value > 0:
        return f"▲ {value:,}원"
    if value < 0:
        return f"▼ {abs(value):,}원"
    return "0원"


def format_pct(value: Decimal | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}%"


def build_holdings_view_model(
    records: list[SnapshotRecord],
    *,
    user_category_rules: list[CategoryRule],
    base_categories: dict[str, str] | None = None,
) -> HoldingsViewModel:
    base_categories = base_categories if base_categories is not None else load_categories()
    user_categories = user_category_mapping(user_category_rules)
    effective_categories = {**base_categories, **user_categories}

    all_holdings = [holding for record in records for holding in record.snapshot.holdings]
    category_buckets, uncategorized = categorize(all_holdings, categories=effective_categories)
    totals = category_totals(category_buckets)
    pnl_summary = category_pnl_summary(category_buckets)

    return HoldingsViewModel(
        source_count=len(records),
        total_holdings=len(all_holdings),
        all_holdings=all_holdings,
        holding_rows=build_holding_rows(records),
        category_rows=build_category_rows(category_buckets, totals, pnl_summary),
        category_buckets=category_buckets,
        category_options=category_options(base_categories, user_categories),
        uncategorized=uncategorized,
        uncategorized_groups=group_uncategorized_holdings(uncategorized),
        totals=totals,
        pnl_summary=pnl_summary,
        user_category_rules=user_category_rules,
    )


def build_holding_rows(records: list[SnapshotRecord]) -> list[dict[str, str]]:
    show_source = len(records) > 1
    rows: list[dict[str, str]] = []
    for record in records:
        for holding in record.snapshot.holdings:
            row = {
                "종목": holding.raw_name,
                "평가금액": format_money(holding.market_value),
                "손익": format_pnl(holding.unrealized_pnl),
                "수익률": format_pct(holding.unrealized_pnl_pct),
            }
            if show_source:
                row["출처"] = record.name
            rows.append(row)
    return rows


def build_category_rows(
    category_buckets: dict[str, list[Holding]],
    totals: dict[str, Decimal],
    pnl_summary: dict[str, tuple[Decimal | None, Decimal | None]],
) -> list[dict[str, object]]:
    grand_total = sum(totals.values(), Decimal(0))
    rows: list[dict[str, object]] = []
    for category, holdings in category_buckets.items():
        total = totals[category]
        weight = (total / grand_total * Decimal("100")) if grand_total > 0 else Decimal(0)
        category_pnl, category_return = pnl_summary[category]
        rows.append({
            "테마": category,
            "평가금액": format_money(total),
            "비중": f"{weight:.2f}%",
            "손익": format_pnl(category_pnl),
            "수익률": format_pct(category_return),
            "종목 수": len(holdings),
            "종목": ", ".join(sorted({holding.raw_name for holding in holdings})),
            "_sort": total,
        })
    rows.sort(key=lambda row: row["_sort"], reverse=True)
    for row in rows:
        del row["_sort"]
    return rows


def market_value_chart_rows(view_model: HoldingsViewModel) -> list[dict[str, object]]:
    rows = [
        {"카테고리": category, "금액": float(view_model.totals[category])}
        for category in view_model.category_buckets
    ]
    rows.sort(key=lambda row: row["금액"], reverse=True)
    return rows


def return_chart_rows(view_model: HoldingsViewModel) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for category in view_model.category_buckets:
        _, return_pct = view_model.pnl_summary[category]
        if return_pct is not None:
            rows.append({
                "카테고리": category,
                "수익률": float(return_pct),
                "보유금액": float(view_model.totals[category]),
            })
    rows.sort(key=lambda row: row["수익률"], reverse=True)
    return rows


def return_value_chart_rows(view_model: HoldingsViewModel) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for category in view_model.category_buckets:
        _, return_pct = view_model.pnl_summary[category]
        rows.append({
            "카테고리": category,
            "보유금액": float(view_model.totals[category]),
            "수익률": float(return_pct) if return_pct is not None else None,
        })
    rows.sort(key=lambda row: row["보유금액"], reverse=True)
    return rows


def cost_basis_chart_data(view_model: HoldingsViewModel) -> CostBasisChartData:
    chart_rows: list[dict[str, object]] = []
    skipped: list[str] = []
    for category in view_model.category_buckets:
        market = view_model.totals[category]
        pnl, _ = view_model.pnl_summary[category]
        if pnl is None:
            skipped.append(category)
            continue
        cost = market - pnl
        chart_rows.append({
            "카테고리": category,
            "보유금액": float(market),
            "원금": float(cost),
        })
    chart_rows.sort(key=lambda row: row["보유금액"], reverse=True)

    long_rows: list[dict[str, object]] = []
    label_rows: list[dict[str, object]] = []
    for row in chart_rows:
        category = str(row["카테고리"])
        market_value = float(row["보유금액"])
        cost_value = float(row["원금"])
        long_rows.append({"카테고리": category, "구분": "원금", "금액": cost_value})
        long_rows.append({"카테고리": category, "구분": "보유금액", "금액": market_value})
        profit = market_value - cost_value
        sign = "+" if profit >= 0 else "−"
        label_rows.append({
            "카테고리": category,
            "위치": max(market_value, cost_value),
            "수익금": profit,
            "라벨": f"{sign}{abs(profit):,.0f}원",
        })

    return CostBasisChartData(
        long_rows=long_rows,
        label_rows=label_rows,
        ordered_categories=[str(row["카테고리"]) for row in chart_rows],
        skipped=skipped,
    )
