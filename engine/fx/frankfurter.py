"""Frankfurter FX source (spec 40 §fx §frankfurter_sources).

Each FrankfurterFXSource wraps one configured endpoint with a `country_provider_map`
that resolves which central-bank label to attach to a returned rate. The
provider mapping does NOT change the upstream HTTP call — it controls the
`provider_id` recorded in the normalized FXRate.

HTTP is performed lazily via httpx; importing this module never triggers a
network call. If httpx is missing at lookup time, a clear error is raised so
test environments without network deps still load the engine cleanly.
"""

from __future__ import annotations

from datetime import date as _date_t, datetime as _datetime_t, timezone
from decimal import Decimal

from engine.config.models import FrankfurterSourceConfig
from engine.fx.rates import FXLookupError, FXRate


class FrankfurterFXSource:
    def __init__(self, cfg: FrankfurterSourceConfig) -> None:
        self.cfg = cfg
        self.source_id = cfg.source_id
        # Per-source in-memory cache for run determinism: (date, base, quote) -> FXRate.
        self._cache: dict[tuple[_date_t, str, str], FXRate] = {}

    # ------------------------------------------------------------------ provider resolution

    def resolve_provider(self) -> str:
        """Return the provider_id derived from the source's `country_provider_map`
        (keyed on `base_country`) with `default_provider` fallback. Spec 40 §fx
        forbids implicit silent fallback — at least one of map/default must
        resolve, or this raises FXLookupError."""
        cm = self.cfg.country_provider_map or {}
        if self.cfg.base_country in cm:
            return cm[self.cfg.base_country]
        if self.cfg.default_provider:
            return self.cfg.default_provider
        # Pydantic validator on FrankfurterSourceConfig also enforces this at load time.
        raise FXLookupError(
            f"frankfurter source {self.source_id!r}: cannot resolve provider for "
            f"base_country={self.cfg.base_country!r}"
        )

    # ------------------------------------------------------------------ lookup

    def get_rate(self,
                 on_date: _date_t,
                 base: str,
                 quote: str) -> FXRate | None:
        if not self.cfg.enabled:
            return None
        key = (on_date, base, quote)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            import httpx
        except ImportError as exc:
            raise FXLookupError(
                "frankfurter source requires httpx; install it to use remote FX"
            ) from exc

        url = f"{self.cfg.base_url.rstrip('/')}/{on_date.isoformat()}"
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(url, params={"from": base, "to": quote})
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            raise FXLookupError(f"frankfurter HTTP error for {url}: {exc}") from exc

        rates = payload.get("rates") or {}
        if quote not in rates:
            return None
        try:
            rate_dec = Decimal(str(rates[quote]))
        except Exception as exc:
            raise FXLookupError(f"invalid rate value from frankfurter: {rates[quote]!r}") from exc

        rec = FXRate(
            date=on_date,
            base_currency=base,
            quote_currency=quote,
            rate=rate_dec,
            provider_id=self.resolve_provider(),
            retrieved_at=_datetime_t.now(tz=timezone.utc),
        )
        self._cache[key] = rec
        return rec

    # ------------------------------------------------------------------ test-friendly seed

    def seed_cache(self, rate: FXRate) -> None:
        """Inject a rate into the per-source cache (used by tests to avoid network)."""
        self._cache[(rate.date, rate.base_currency, rate.quote_currency)] = rate
