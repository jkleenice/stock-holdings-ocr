from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from .schemas import Holding


def aggregate_pnl(
    holdings: Iterable[Holding],
) -> tuple[Decimal | None, Decimal | None]:
    """Sum unrealized P&L across holdings, plus value-weighted return percent.

    Return percent = `total_pnl / (total_market_value - total_pnl) * 100`,
    i.e. profit/loss divided by inferred cost basis.

    Returns `(None, None)` if the iterable is empty or any holding lacks
    `market_value` or `unrealized_pnl` — partial sums would mislead.
    Returns `(total_pnl, None)` when cost basis is exactly 0.
    """
    items = list(holdings)
    if not items:
        return None, None
    if any(h.market_value is None or h.unrealized_pnl is None for h in items):
        return None, None
    total_pnl = sum((h.unrealized_pnl for h in items), Decimal(0))
    total_market = sum((h.market_value for h in items), Decimal(0))
    cost_basis = total_market - total_pnl
    if cost_basis == 0:
        return total_pnl, None
    return total_pnl, total_pnl / cost_basis * Decimal("100")
