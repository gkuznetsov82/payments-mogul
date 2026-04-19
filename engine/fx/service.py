"""FXService — orchestrates source policy and lookups (spec 40 §fx).

Responsibilities:
- Honor `source_policy`: local_only | frankfurter_only | local_override_then_frankfurter.
- Constrain Frankfurter selection to `source_refs` when set.
- Allow caller to address a specific Frankfurter source via `requested_source_id`.
- Per-run in-memory caching for determinism.
"""

from __future__ import annotations

from datetime import date as _date_t
from typing import Optional

from engine.config.models import FXConfig
from engine.fx.frankfurter import FrankfurterFXSource
from engine.fx.local import LocalFXSource
from engine.fx.rates import FXLookupError, FXRate


class FXService:
    def __init__(self,
                 cfg: FXConfig,
                 local_source: Optional[LocalFXSource] = None,
                 frankfurter_sources: Optional[list[FrankfurterFXSource]] = None) -> None:
        self.cfg = cfg
        self.local_source = local_source
        self.frankfurter_sources = list(frankfurter_sources or [])
        self._frankfurter_by_id = {fs.source_id: fs for fs in self.frankfurter_sources}
        # Service-level cache for source-resolved lookups (post-policy).
        self._cache: dict[tuple[str, _date_t, str, str], FXRate] = {}

    # ------------------------------------------------------------------ public API

    def get_rate(self,
                 on_date: _date_t,
                 base: str,
                 quote: str,
                 requested_source_id: Optional[str] = None) -> FXRate:
        """Resolve a rate per configured policy. Raises FXLookupError if no
        source can satisfy the request."""
        cache_key = (requested_source_id or "*", on_date, base, quote)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        policy = self.cfg.source_policy
        rate: Optional[FXRate] = None

        # Targeted source request always wins (and only frankfurter sources are addressable).
        if requested_source_id is not None:
            if requested_source_id not in self._frankfurter_by_id:
                raise FXLookupError(
                    f"requested_source_id {requested_source_id!r} not registered"
                )
            if self.cfg.source_refs and requested_source_id not in self.cfg.source_refs:
                raise FXLookupError(
                    f"requested_source_id {requested_source_id!r} not in scenario source_refs"
                )
            rate = self._frankfurter_by_id[requested_source_id].get_rate(on_date, base, quote)
            if rate is None:
                raise FXLookupError(
                    f"no rate at {on_date} {base}->{quote} from source {requested_source_id!r}"
                )
            self._cache[cache_key] = rate
            return rate

        if policy == "local_only":
            rate = self._try_local(on_date, base, quote)
        elif policy == "frankfurter_only":
            rate = self._try_frankfurter(on_date, base, quote)
        elif policy == "local_override_then_frankfurter":
            rate = self._try_local(on_date, base, quote)
            if rate is None:
                rate = self._try_frankfurter(on_date, base, quote)
        else:
            raise FXLookupError(f"unsupported source_policy {policy!r}")

        if rate is None:
            raise FXLookupError(
                f"no rate found for {on_date} {base}->{quote} under policy {policy!r}"
            )
        self._cache[cache_key] = rate
        return rate

    # ------------------------------------------------------------------ helpers

    def _try_local(self, on_date: _date_t, base: str, quote: str) -> Optional[FXRate]:
        if self.local_source is None:
            return None
        return self.local_source.get_rate(on_date, base, quote)

    def _try_frankfurter(self, on_date: _date_t, base: str, quote: str) -> Optional[FXRate]:
        # Iterate sources in source_refs order if set; else in registered order.
        ids = self.cfg.source_refs or [fs.source_id for fs in self.frankfurter_sources]
        for sid in ids:
            src = self._frankfurter_by_id.get(sid)
            if src is None:
                continue
            r = src.get_rate(on_date, base, quote)
            if r is not None:
                return r
        return None
