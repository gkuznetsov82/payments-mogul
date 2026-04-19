"""Local-file FX source (spec 40 §fx §Local file source).

Reads YAML / JSON / CSV with the v2 fx_rates schema:

    rates:
      - date: "YYYY-MM-DD"
        base_currency: "EUR"
        quote_currency: "USD"
        rate: "1.102500"
        provider_id: "ECB"
        retrieved_at: "..."
"""

from __future__ import annotations

import csv
import json
from datetime import date as _date_t, datetime as _datetime_t, timezone
from decimal import Decimal
from pathlib import Path

import yaml

from engine.fx.rates import FXLookupError, FXRate


class LocalFXSource:
    def __init__(self, rates: list[FXRate]) -> None:
        # Index by (date, base, quote) for O(1) lookup.
        self._index: dict[tuple[_date_t, str, str], FXRate] = {
            (r.date, r.base_currency, r.quote_currency): r for r in rates
        }
        self._all = list(rates)

    @classmethod
    def from_file(cls, path: str | Path, fmt: str = "yaml") -> "LocalFXSource":
        p = Path(path)
        if not p.exists():
            raise FXLookupError(f"FX local file not found: {p}")
        text = p.read_text(encoding="utf-8")
        if fmt == "yaml":
            data = yaml.safe_load(text)
            items = (data or {}).get("rates") or []
        elif fmt == "json":
            data = json.loads(text)
            items = (data or {}).get("rates") or []
        elif fmt == "csv":
            reader = csv.DictReader(text.splitlines())
            items = list(reader)
        else:
            raise FXLookupError(f"unsupported FX local format: {fmt}")
        rates = [_rate_from_dict(d) for d in items]
        return cls(rates)

    def get_rate(self,
                 on_date: _date_t,
                 base: str,
                 quote: str) -> FXRate | None:
        return self._index.get((on_date, base, quote))

    def all_rates(self) -> list[FXRate]:
        return list(self._all)


def _rate_from_dict(d: dict) -> FXRate:
    try:
        date_v = d["date"]
        if isinstance(date_v, str):
            date_v = _date_t.fromisoformat(date_v)
        retrieved = d.get("retrieved_at")
        if isinstance(retrieved, str):
            # Handle "Z" suffix as UTC.
            retrieved = retrieved.replace("Z", "+00:00")
            retrieved = _datetime_t.fromisoformat(retrieved)
        elif retrieved is None:
            retrieved = _datetime_t.now(tz=timezone.utc)
        return FXRate(
            date=date_v,
            base_currency=d["base_currency"],
            quote_currency=d["quote_currency"],
            rate=Decimal(str(d["rate"])),
            provider_id=d.get("provider_id", "unknown"),
            retrieved_at=retrieved,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise FXLookupError(f"invalid FX rate entry {d!r}: {exc}")
