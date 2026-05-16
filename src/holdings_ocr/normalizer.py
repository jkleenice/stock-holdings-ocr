from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import yaml

from .metrics import aggregate_pnl
from .schemas import AggregatedPosition, Holding, HoldingsSnapshot

DEFAULT_ALIASES_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "aliases" / "issuer_aliases.yaml"
)
DEFAULT_KOREAN_NAMES_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "aliases" / "korean_names.yaml"
)


def load_issuer_aliases(path: Path | None = None) -> dict[str, str]:
    """Load `symbol -> issuer` mapping from a YAML file shaped `issuer: [symbols]`."""
    path = path or DEFAULT_ALIASES_PATH
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    mapping: dict[str, str] = {}
    for issuer, symbols in data.items():
        for symbol in symbols:
            mapping[str(symbol).upper()] = issuer
    return mapping


def load_korean_name_aliases(path: Path | None = None) -> dict[str, str]:
    """Load `normalized raw_name -> issuer` mapping from a YAML file shaped `issuer: [raw_names]`."""
    path = path or DEFAULT_KOREAN_NAMES_PATH
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    mapping: dict[str, str] = {}
    for issuer, raw_names in data.items():
        for raw_name in raw_names:
            mapping[_normalize_raw_name(raw_name)] = issuer
    return mapping


def resolve_issuer(
    holding: Holding,
    aliases: dict[str, str],
    korean_names: dict[str, str],
) -> str:
    """Return the canonical issuer name for a holding.

    Precedence:
    1. Symbol alias match (e.g. GOOGL -> Alphabet)
    2. Korean raw-name alias match (e.g. 알파벳 A -> Alphabet)
    3. Symbol passthrough (uppercased)
    4. Raw-name passthrough
    """
    symbol_key = holding.symbol.upper() if holding.symbol else None
    raw_name_key = _normalize_raw_name(holding.raw_name)
    if symbol_key and symbol_key in aliases:
        return aliases[symbol_key]
    if raw_name_key in korean_names:
        return korean_names[raw_name_key]
    return symbol_key or holding.raw_name


def aggregate_by_issuer(
    snapshot: HoldingsSnapshot,
    aliases: dict[str, str] | None = None,
    korean_names: dict[str, str] | None = None,
) -> list[AggregatedPosition]:
    """Collapse holdings into one row per issuer.

    Handles two distinct merges in one pass:
    - Same issuer, different share class (GOOGL + GOOG -> Alphabet) via `aliases`.
    - Same symbol, different account: rows share an issuer key; accounts are preserved as a list.
    """
    aliases = aliases if aliases is not None else load_issuer_aliases()
    korean_names = korean_names if korean_names is not None else load_korean_name_aliases()
    buckets: dict[str, list] = defaultdict(list)

    for holding in snapshot.holdings:
        issuer = resolve_issuer(holding, aliases, korean_names)
        buckets[issuer].append(holding)

    positions: list[AggregatedPosition] = []
    for issuer, items in buckets.items():
        symbols = sorted({h.symbol.upper() for h in items if h.symbol})
        display_names = sorted({h.raw_name for h in items})

        currencies = sorted({h.currency for h in items})
        if len(currencies) != 1:
            raise ValueError(f"issuer '{issuer}' mixes currencies: {', '.join(currencies)}")

        missing_market_values = [h.raw_name for h in items if h.market_value is None]
        if missing_market_values:
            raise ValueError(
                f"issuer '{issuer}' has holdings without market_value: {', '.join(missing_market_values)}"
            )

        known_quantities = [h.quantity for h in items if h.quantity is not None]
        total_qty = None if len(known_quantities) != len(items) else sum(known_quantities, Decimal(0))
        total_val = sum((h.market_value for h in items if h.market_value is not None), Decimal(0))
        accounts = sorted({h.account for h in items if h.account})
        currency = currencies[0]
        total_unrealized_pnl, total_unrealized_pnl_pct = aggregate_pnl(items)

        positions.append(
            AggregatedPosition(
                issuer=issuer,
                display_names=display_names,
                symbols=symbols,
                total_quantity=total_qty,
                total_market_value=total_val,
                currency=currency,
                accounts=accounts,
                unrealized_pnl=total_unrealized_pnl,
                unrealized_pnl_pct=total_unrealized_pnl_pct,
            )
        )

    return positions


def _normalize_raw_name(value: str) -> str:
    return " ".join(str(value).split()).casefold()
