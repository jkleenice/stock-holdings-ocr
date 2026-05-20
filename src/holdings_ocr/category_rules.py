from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .normalizer import (
    _normalize_raw_name,
    load_issuer_aliases,
    load_korean_name_aliases,
    resolve_issuer,
)
from .schemas import Holding

USER_CATEGORY_RULES_FILE = Path(".cache/holdings-ocr/category_overrides.json")
USER_CATEGORY_RULES_VERSION = 1


@dataclass(frozen=True)
class CategoryRule:
    raw_name: str
    symbol: str | None
    category: str
    keys: list[str]


@dataclass(frozen=True)
class UncategorizedGroup:
    id: str
    raw_names: list[str]
    symbols: list[str]
    keys: list[str]
    count: int
    market_value: Decimal


def holding_category_keys(
    holding: Holding,
    *,
    aliases: dict[str, str] | None = None,
    korean_names: dict[str, str] | None = None,
) -> list[str]:
    aliases = aliases if aliases is not None else load_issuer_aliases()
    korean_names = korean_names if korean_names is not None else load_korean_name_aliases()

    keys: list[str] = []
    issuer_key = _normalize_raw_name(resolve_issuer(holding, aliases, korean_names))
    if issuer_key:
        keys.append(issuer_key)
    if holding.symbol:
        symbol_key = _normalize_raw_name(holding.symbol)
        if symbol_key and symbol_key not in keys:
            keys.append(symbol_key)
    raw_name_key = _normalize_raw_name(holding.raw_name)
    if raw_name_key and raw_name_key not in keys:
        keys.append(raw_name_key)
    return keys


def load_user_category_rules(path: Path = USER_CATEGORY_RULES_FILE) -> list[CategoryRule]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    raw_rules = payload.get("rules") if isinstance(payload, dict) else None
    if not isinstance(raw_rules, list):
        return []

    rules: list[CategoryRule] = []
    for item in raw_rules:
        rule = _coerce_category_rule(item)
        if rule is not None:
            rules.append(rule)
    return rules


def save_user_category_rules(
    rules: list[CategoryRule],
    path: Path = USER_CATEGORY_RULES_FILE,
) -> None:
    payload = {
        "version": USER_CATEGORY_RULES_VERSION,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "rules": [category_rule_to_json(rule) for rule in rules],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def category_rule_to_json(rule: CategoryRule) -> dict:
    return {
        "raw_name": rule.raw_name,
        "symbol": rule.symbol,
        "category": rule.category,
        "keys": rule.keys,
    }


def user_category_mapping(rules: list[CategoryRule]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for rule in rules:
        category = rule.category.strip()
        if not category:
            continue
        for key in rule.keys:
            normalized = _normalize_raw_name(str(key))
            if normalized:
                mapping[normalized] = category
    return mapping


def category_options(
    base_categories: dict[str, str],
    user_categories: dict[str, str],
) -> list[str]:
    options: list[str] = []
    seen: set[str] = set()
    for category in [*base_categories.values(), *user_categories.values()]:
        if category not in seen:
            options.append(category)
            seen.add(category)
    return options


def upsert_user_category_rule(
    rules: list[CategoryRule],
    *,
    raw_name: str,
    symbol: str | None,
    category: str,
    keys: list[str],
) -> list[CategoryRule]:
    normalized_keys = _normalize_keys(keys)
    category = category.strip()
    if not normalized_keys or not category:
        return rules

    key_set = set(normalized_keys)
    kept_rules = [
        rule
        for rule in rules
        if not key_set.intersection(_normalize_raw_name(str(key)) for key in rule.keys)
    ]
    kept_rules.append(
        CategoryRule(
            raw_name=raw_name,
            symbol=symbol,
            category=category,
            keys=normalized_keys,
        )
    )
    return kept_rules


def delete_user_category_rule(rules: list[CategoryRule], index: int) -> list[CategoryRule]:
    return [rule for idx, rule in enumerate(rules) if idx != index]


def category_rule_id(keys: list[str]) -> str:
    key_material = "|".join(keys)
    return hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:12]


def group_uncategorized_holdings(holdings: list[Holding]) -> list[UncategorizedGroup]:
    grouped: dict[str, dict] = {}
    aliases = load_issuer_aliases()
    korean_names = load_korean_name_aliases()
    for holding in holdings:
        keys = holding_category_keys(
            holding,
            aliases=aliases,
            korean_names=korean_names,
        )
        group_id = category_rule_id(keys[:1])
        group = grouped.setdefault(
            group_id,
            {
                "id": group_id,
                "raw_names": [],
                "symbols": [],
                "keys": [],
                "count": 0,
                "market_value": Decimal(0),
            },
        )
        _append_unique(group["raw_names"], holding.raw_name)
        _append_unique(group["symbols"], holding.symbol.upper() if holding.symbol else None)
        for key in keys:
            _append_unique(group["keys"], key)
        group["count"] += 1
        if holding.market_value is not None:
            group["market_value"] += holding.market_value

    targets = [
        UncategorizedGroup(
            id=group["id"],
            raw_names=group["raw_names"],
            symbols=group["symbols"],
            keys=group["keys"],
            count=group["count"],
            market_value=group["market_value"],
        )
        for group in grouped.values()
    ]
    targets.sort(key=lambda target: target.market_value, reverse=True)
    return targets


def _coerce_category_rule(item: object) -> CategoryRule | None:
    if not isinstance(item, dict):
        return None

    category = str(item.get("category") or "").strip()
    raw_name = str(item.get("raw_name") or "").strip()
    symbol_value = item.get("symbol")
    symbol = str(symbol_value).strip() if symbol_value else None
    keys = _normalize_keys(item.get("keys") if isinstance(item.get("keys"), list) else [])

    if not keys and symbol:
        keys.append(_normalize_raw_name(symbol))
    if raw_name:
        raw_name_key = _normalize_raw_name(raw_name)
        if raw_name_key and raw_name_key not in keys:
            keys.append(raw_name_key)

    if not category or not keys:
        return None

    return CategoryRule(
        raw_name=raw_name or keys[0],
        symbol=symbol,
        category=category,
        keys=keys,
    )


def _normalize_keys(keys: object) -> list[str]:
    normalized_keys: list[str] = []
    if not isinstance(keys, list):
        return normalized_keys
    for key in keys:
        normalized = _normalize_raw_name(str(key))
        if normalized and normalized not in normalized_keys:
            normalized_keys.append(normalized)
    return normalized_keys


def _append_unique(values: list[str], value: str | None) -> None:
    if value and value not in values:
        values.append(value)
