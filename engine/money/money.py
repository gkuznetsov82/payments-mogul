"""Money + Currency primitives (spec 40 §money).

Money is a Decimal-backed amount paired with a Currency. Quantization to the
currency's `minor_unit` is deterministic and uses the configured rounding mode
(default `half_up`).

Money is intended to be the externally-visible representation when
`money.enforce_money_object=true` per spec; agent internals may continue to
hold raw scalar amounts and convert at boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP, Decimal
from typing import Union


_MODE_MAP = {
    "half_up": ROUND_HALF_UP,
    "half_even": ROUND_HALF_EVEN,
    "down": ROUND_DOWN,
    "up": ROUND_UP,
    "floor": ROUND_FLOOR,
    "ceiling": ROUND_CEILING,
}


class MoneyError(Exception):
    pass


@dataclass(frozen=True)
class Currency:
    """ISO 4217 currency descriptor (spec 40 §currency_catalog)."""
    code: str            # alpha-3, e.g. "USD"
    numeric_code: str    # 3-digit ISO numeric, kept as string for "008"-style preservation
    name: str
    minor_unit: int      # decimal places of the minor unit; e.g. 2 for USD, 0 for JPY, 3 for BHD
    active_from: str | None = None  # YYYY-MM-DD or None for "always active"
    active_to: str | None = None    # YYYY-MM-DD or None for "still active"


@dataclass(frozen=True)
class Money:
    """A monetary amount paired with its currency.

    Construct via `Money.of(amount, currency, ...)` to get correct quantization.
    Direct construction stores the raw Decimal without re-quantizing — use only
    when you have already-quantized input.
    """
    amount: Decimal
    currency: Currency

    # ------------------------------------------------------------------ constructors

    @classmethod
    def of(cls,
           amount: Union[str, int, float, Decimal],
           currency: Currency,
           rounding_mode: str = "half_up") -> "Money":
        """Quantize `amount` to currency.minor_unit and pair it with currency."""
        if isinstance(amount, float):
            # Avoid float repr surprises (0.1 != Decimal("0.1"))
            dec = Decimal(str(amount))
        elif isinstance(amount, Decimal):
            dec = amount
        else:
            dec = Decimal(str(amount))
        try:
            mode = _MODE_MAP[rounding_mode]
        except KeyError as exc:
            raise MoneyError(f"unknown rounding_mode '{rounding_mode}'") from exc
        quant = Decimal(1).scaleb(-currency.minor_unit) if currency.minor_unit > 0 else Decimal(1)
        quantized = dec.quantize(quant, rounding=mode)
        return cls(amount=quantized, currency=currency)

    # ------------------------------------------------------------------ operators (same currency only)

    def _check_same(self, other: "Money") -> None:
        if not isinstance(other, Money):
            raise MoneyError("operand is not Money")
        if other.currency.code != self.currency.code:
            raise MoneyError(
                f"currency mismatch: {self.currency.code} vs {other.currency.code}"
            )

    def add(self, other: "Money", rounding_mode: str = "half_up") -> "Money":
        self._check_same(other)
        return Money.of(self.amount + other.amount, self.currency, rounding_mode)

    def sub(self, other: "Money", rounding_mode: str = "half_up") -> "Money":
        self._check_same(other)
        return Money.of(self.amount - other.amount, self.currency, rounding_mode)

    # ------------------------------------------------------------------ rendering

    def to_dict(self) -> dict:
        """Wire/snapshot representation (spec 51/52: amount as string for precision)."""
        return {
            "amount": format(self.amount, "f"),
            "currency": self.currency.code,
        }

    def __str__(self) -> str:
        return f"{format(self.amount, 'f')} {self.currency.code}"
