from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import yaml

from .normalizer import (
    _normalize_raw_name,
    load_issuer_aliases,
    load_korean_name_aliases,
    resolve_issuer,
)
from .schemas import Holding

DEFAULT_CATEGORIES_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "categories.yaml"
)


def load_categories(path: Path | None = None) -> dict[str, str]:
    """Load `issuer_norm -> category` mapping from a YAML file shaped `category: [issuers]`.

    Raises ValueError if any issuer appears in more than one category, enforcing
    the "no overlap" rule.
    """
    path = path or DEFAULT_CATEGORIES_PATH
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    mapping: dict[str, str] = {}
    overlaps: list[tuple[str, str, str]] = []
    for category, issuers in data.items():
        for issuer in issuers:
            key = _normalize_raw_name(issuer)
            if key in mapping and mapping[key] != category:
                overlaps.append((issuer, mapping[key], category))
            mapping[key] = category
    if overlaps:
        details = "; ".join(f"'{name}' in both '{a}' and '{b}'" for name, a, b in overlaps)
        raise ValueError(f"categories.yaml has overlapping entries: {details}")
    return mapping


def categorize(
    holdings: list[Holding],
    *,
    aliases: dict[str, str] | None = None,
    korean_names: dict[str, str] | None = None,
    categories: dict[str, str] | None = None,
) -> tuple[dict[str, list[Holding]], list[Holding]]:
    """Bucket holdings by category. Returns (category -> holdings, uncategorized)."""
    aliases = aliases if aliases is not None else load_issuer_aliases()
    korean_names = korean_names if korean_names is not None else load_korean_name_aliases()
    categories = categories if categories is not None else load_categories()

    buckets: dict[str, list[Holding]] = defaultdict(list)
    uncategorized: list[Holding] = []
    for holding in holdings:
        issuer = resolve_issuer(holding, aliases, korean_names)
        issuer_key = _normalize_raw_name(issuer)
        category = categories.get(issuer_key)
        if category is None:
            # Fallback: try matching raw_name directly (for ETFs that share text with issuer).
            category = categories.get(_normalize_raw_name(holding.raw_name))
        if category is not None:
            buckets[category].append(holding)
        else:
            uncategorized.append(holding)
    return dict(buckets), uncategorized


def category_totals(buckets: dict[str, list[Holding]]) -> dict[str, Decimal]:
    """Sum market_value per category. None market_values are skipped."""
    totals: dict[str, Decimal] = {}
    for category, items in buckets.items():
        totals[category] = sum(
            (h.market_value for h in items if h.market_value is not None),
            Decimal(0),
        )
    return totals


def category_pnl_summary(
    buckets: dict[str, list[Holding]],
) -> dict[str, tuple[Decimal | None, Decimal | None]]:
    """Per-category `(total_pnl, return_pct)` using value-weighted return.

    Return percent is `total_pnl / (total_market_value - total_pnl) * 100`.
    Returns `(None, None)` for a bucket if any holding lacks `market_value`
    or `unrealized_pnl` — partial sums would be misleading.
    """
    summary: dict[str, tuple[Decimal | None, Decimal | None]] = {}
    for category, items in buckets.items():
        if any(h.market_value is None or h.unrealized_pnl is None for h in items):
            summary[category] = (None, None)
            continue
        total_pnl = sum((h.unrealized_pnl for h in items), Decimal(0))
        total_market = sum((h.market_value for h in items), Decimal(0))
        cost_basis = total_market - total_pnl
        if cost_basis == 0:
            summary[category] = (total_pnl, None)
        else:
            summary[category] = (total_pnl, total_pnl / cost_basis * Decimal("100"))
    return summary
