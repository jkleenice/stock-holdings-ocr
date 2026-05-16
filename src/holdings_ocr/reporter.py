from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from .normalizer import aggregate_by_issuer
from .schemas import AggregatedReport, HoldingsSnapshot


def build_report(
    snapshot: HoldingsSnapshot,
    aliases: dict[str, str] | None = None,
    korean_names: dict[str, str] | None = None,
) -> AggregatedReport:
    positions = aggregate_by_issuer(snapshot, aliases, korean_names)
    currencies = sorted({p.currency for p in positions})
    if len(currencies) > 1:
        raise ValueError(f"snapshot mixes currencies: {', '.join(currencies)}")

    total = sum((p.total_market_value for p in positions), Decimal(0))
    currency = currencies[0] if currencies else None
    weighted_positions = [
        p.model_copy(
            update={
                "weight_pct": (p.total_market_value / total * Decimal("100")) if total > 0 else None,
            }
        )
        for p in positions
    ]
    return AggregatedReport(
        snapshot_source=snapshot.source,
        generated_at=datetime.now(timezone.utc),
        positions=weighted_positions,
        total_value=total,
        currency=currency,
    )


def render_markdown(report: AggregatedReport) -> str:
    include_quantity = any(p.total_quantity is not None for p in report.positions)
    header = "| 발행사 | 표시명 | 평가금액 | 비중 | 손익 | 계좌 |"
    separator = "| --- | --- | --- | --- | --- | --- |"
    if include_quantity:
        header = "| 발행사 | 표시명 | 수량 | 평가금액 | 비중 | 손익 | 계좌 |"
        separator = "| --- | --- | --- | --- | --- | --- | --- |"

    lines = [
        "# Holdings Report",
        "",
        f"- Source: `{report.snapshot_source}`",
        f"- Generated: {report.generated_at.isoformat()}",
        f"- Total: {_format_money(report.total_value, report.currency)}",
        "",
        header,
        separator,
    ]
    for p in sorted(report.positions, key=lambda x: x.total_market_value, reverse=True):
        accounts = ", ".join(p.accounts) if p.accounts else "-"
        display_name = ", ".join(p.display_names) if p.display_names else "-"
        unrealized = _format_unrealized(p.unrealized_pnl, p.unrealized_pnl_pct, p.currency)
        row = [
            p.issuer,
            display_name,
            _format_money(p.total_market_value, p.currency),
            _format_pct(p.weight_pct),
            unrealized,
            accounts,
        ]
        if include_quantity:
            row.insert(2, _format_quantity(p.total_quantity))
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines) + "\n"


def _format_quantity(quantity: Decimal | None) -> str:
    return str(quantity) if quantity is not None else "-"


def _format_money(value: Decimal, currency: str | None) -> str:
    return f"{value} {currency}" if currency else str(value)


def _format_pct(value: Decimal | None) -> str:
    return f"{value.quantize(Decimal('0.01'))}%" if value is not None else "-"


def _format_unrealized(
    pnl: Decimal | None,
    pnl_pct: Decimal | None,
    currency: str | None,
) -> str:
    if pnl is None and pnl_pct is None:
        return "-"
    if pnl is None:
        return _format_pct(pnl_pct)
    money = _format_money(pnl, currency)
    if pnl_pct is None:
        return money
    return f"{money} ({_format_pct(pnl_pct)})"
