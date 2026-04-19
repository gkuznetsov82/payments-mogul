"""CurrencyCatalog runtime loader (spec 40 §currency_catalog).

Loads a YAML or JSON file with the project's currency catalog schema and exposes
query helpers by code, optionally filtered by validity date (active_from / active_to).

Backward compat: if `allow_local_overrides=True` in config, callers may extend
the catalog at runtime via `add_override(currency)` (no persistence — runtime only).
"""

from __future__ import annotations

import json
from datetime import date as _date_t
from pathlib import Path
from typing import Iterable, Optional

import yaml

from engine.money.money import Currency


class CurrencyCatalogError(Exception):
    pass


class CurrencyCatalog:
    def __init__(self,
                 currencies: Iterable[Currency],
                 catalog_version: str | None = None,
                 source: dict | None = None) -> None:
        # Index by code; multiple historical entries per code allowed via _by_code_all.
        self._by_code_all: dict[str, list[Currency]] = {}
        for c in currencies:
            self._by_code_all.setdefault(c.code, []).append(c)
        self.catalog_version = catalog_version
        self.source = source or {}

    # ------------------------------------------------------------------ constructors

    @classmethod
    def from_file(cls, path: str | Path, fmt: str = "yaml") -> "CurrencyCatalog":
        p = Path(path)
        if not p.exists():
            raise CurrencyCatalogError(f"catalog file not found: {p}")
        text = p.read_text(encoding="utf-8")
        if fmt == "yaml":
            data = yaml.safe_load(text)
        elif fmt == "json":
            data = json.loads(text)
        else:
            raise CurrencyCatalogError(f"unsupported catalog format: {fmt}")
        if not isinstance(data, dict):
            raise CurrencyCatalogError(f"catalog root must be a mapping, got {type(data).__name__}")
        items = data.get("currencies") or []
        if not isinstance(items, list):
            raise CurrencyCatalogError("catalog 'currencies' must be a list")
        currencies = [_currency_from_dict(item) for item in items]
        return cls(
            currencies=currencies,
            catalog_version=data.get("catalog_version"),
            source=data.get("source") or {},
        )

    # ------------------------------------------------------------------ query

    def codes(self) -> list[str]:
        """Sorted list of all currency codes in the catalog."""
        return sorted(self._by_code_all.keys())

    def all(self, code: str) -> list[Currency]:
        """All catalog records for `code` (current + historical), in insertion order."""
        return list(self._by_code_all.get(code, []))

    def get(self, code: str, on_date: Optional[_date_t] = None) -> Currency:
        """Return the currency record valid on `on_date` (default: any current record).

        Raises CurrencyCatalogError if code is unknown or no record matches.
        """
        records = self._by_code_all.get(code)
        if not records:
            raise CurrencyCatalogError(f"unknown currency code: {code!r}")
        if on_date is None:
            # Prefer record with no active_to (i.e. still current); else last entry.
            for r in records:
                if r.active_to is None:
                    return r
            return records[-1]
        for r in records:
            af = _parse_date(r.active_from)
            at = _parse_date(r.active_to)
            if af is not None and on_date < af:
                continue
            if at is not None and on_date > at:
                continue
            return r
        raise CurrencyCatalogError(
            f"currency {code!r} has no record valid on {on_date.isoformat()}"
        )

    def add_override(self, currency: Currency) -> None:
        """Append a runtime override entry (last-wins for same code)."""
        self._by_code_all.setdefault(currency.code, []).append(currency)


# --------------------------------------------------------------------------- helpers

def _currency_from_dict(d: dict) -> Currency:
    try:
        return Currency(
            code=d["code"],
            numeric_code=str(d.get("numeric_code", "")),
            name=d.get("name", ""),
            minor_unit=int(d["minor_unit"]),
            active_from=d.get("active_from"),
            active_to=d.get("active_to"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CurrencyCatalogError(f"invalid currency entry {d!r}: {exc}")


def _parse_date(s: str | None) -> _date_t | None:
    if s is None:
        return None
    try:
        return _date_t.fromisoformat(s)
    except (ValueError, TypeError):
        return None
