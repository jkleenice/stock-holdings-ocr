from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class Holding(BaseModel):
    """A single position as extracted from the source image, one-to-one with a row."""

    raw_name: str = Field(description="Name or symbol exactly as it appears in the image.")
    symbol: str | None = Field(default=None, description="Normalized ticker if recognizable.")
    quantity: Decimal | None = None
    market_value: Decimal | None = None
    currency: str
    account: str | None = None
    unrealized_pnl: Decimal | None = None
    unrealized_pnl_pct: Decimal | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        currency = value.strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("currency must be a 3-letter alphabetic code")
        return currency


class HoldingsSnapshot(BaseModel):
    """Output of the extractor for one image."""

    source: str
    extracted_at: datetime
    holdings: list[Holding]
    broker_hint: str | None = None
    raw_text: str | None = None
    extractor_model: str | None = None


class AggregatedPosition(BaseModel):
    """A position after normalization: one issuer, possibly multiple symbols/accounts."""

    issuer: str
    display_names: list[str]
    symbols: list[str]
    total_quantity: Decimal | None
    total_market_value: Decimal
    weight_pct: Decimal | None = None
    currency: str
    accounts: list[str]
    unrealized_pnl: Decimal | None = None
    unrealized_pnl_pct: Decimal | None = None


class AggregatedReport(BaseModel):
    snapshot_source: str
    generated_at: datetime
    positions: list[AggregatedPosition]
    total_value: Decimal
    currency: str | None
