"""Normalized FX record (spec 40 §fx §Normalized FX record shape)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date_t, datetime as _datetime_t
from decimal import Decimal


class FXLookupError(Exception):
    pass


@dataclass(frozen=True)
class FXRate:
    """Normalized FX rate per spec 40 §fx."""
    date: _date_t
    base_currency: str        # ISO 4217 alpha-3
    quote_currency: str       # ISO 4217 alpha-3
    rate: Decimal
    provider_id: str
    retrieved_at: _datetime_t

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "base_currency": self.base_currency,
            "quote_currency": self.quote_currency,
            "rate": format(self.rate, "f"),
            "provider_id": self.provider_id,
            "retrieved_at": self.retrieved_at.isoformat(),
        }
