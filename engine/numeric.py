"""Numeric typing utilities per spec 40/51/52.

Counts (persons, transactions) are emitted to external channels (events,
snapshots, API payloads) as integers via `round_count`. Amounts use
`round_amount` with configured decimal scale.

Rounding mode strings match simulation.count_rounding_mode /
amount_rounding_mode in the config.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP, Decimal


_MODE_MAP = {
    "half_up": ROUND_HALF_UP,
    "half_even": ROUND_HALF_EVEN,
    "down": ROUND_DOWN,
    "up": ROUND_UP,
    "floor": ROUND_FLOOR,
    "ceiling": ROUND_CEILING,
}


def round_count(value: float, mode: str = "half_up") -> int:
    """Round a raw rate-derived count to an integer per the configured mode."""
    if value == 0:
        return 0
    dec = Decimal(str(value))
    return int(dec.quantize(Decimal("1"), rounding=_MODE_MAP[mode]))


def round_amount(value: float, scale_dp: int = 2, mode: str = "half_up") -> float:
    """Round a monetary amount to the configured decimal scale."""
    if value == 0:
        return 0.0
    dec = Decimal(str(value))
    quant = Decimal(1).scaleb(-scale_dp)
    return float(dec.quantize(quant, rounding=_MODE_MAP[mode]))
