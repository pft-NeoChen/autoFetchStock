"""TASK-B01 — Cost model for Taiwan equities (V2 §3.2).

Constants are module-level so tests can monkeypatch them. All functions are
pure — they take prices/shares/side and return floats or dicts.
"""

from __future__ import annotations

from typing import Literal

__all__ = [
    "COMMISSION_DISCOUNT",
    "COMMISSION_RATE",
    "TRANSACTION_TAX_DAYTRADE",
    "TRANSACTION_TAX_NORMAL",
    "commission",
    "round_to_tick",
    "round_trip_cost",
    "slippage",
    "tick_size_for",
]


# 手續費 / 稅率
COMMISSION_RATE: float = 0.001425        # 單邊
COMMISSION_DISCOUNT: float = 0.38        # 永豐折扣（可調）
TRANSACTION_TAX_NORMAL: float = 0.003    # 現股賣方
TRANSACTION_TAX_DAYTRADE: float = 0.0015 # 當沖賣方


# Tick rule (台交所 2020+) — (upper_exclusive, tick_size).
_TICK_BANDS: list[tuple[float, float]] = [
    (10.0, 0.01),
    (50.0, 0.05),
    (100.0, 0.1),
    (500.0, 0.5),
    (1000.0, 1.0),
    (float("inf"), 5.0),
]


def tick_size_for(price: float) -> float:
    """Return the legal tick size for ``price`` per TWSE 2020+ table."""
    if price < 0:
        raise ValueError("price must be non-negative")
    for upper, tick in _TICK_BANDS:
        if price < upper:
            return tick
    return _TICK_BANDS[-1][1]


def round_to_tick(price: float) -> float:
    tick = tick_size_for(price)
    rounded = round(price / tick) * tick
    # Use the tick size's decimal places to clean up float noise.
    digits = max(0, -int(round(_log10(tick))))
    return round(rounded, digits) if digits else rounded


def _log10(x: float) -> float:
    # Tiny inline log10 to avoid importing math here; tick is always a clean number.
    import math
    return math.log10(x)


def commission(notional: float) -> float:
    return notional * COMMISSION_RATE * COMMISSION_DISCOUNT


def round_trip_cost(
    price_in: float,
    price_out: float,
    shares: float,
    *,
    is_daytrade: bool = False,
) -> dict[str, float]:
    fee_in = commission(price_in * shares)
    fee_out = commission(price_out * shares)
    tax_rate = TRANSACTION_TAX_DAYTRADE if is_daytrade else TRANSACTION_TAX_NORMAL
    tax = price_out * shares * tax_rate
    return {
        "fee_in": fee_in,
        "fee_out": fee_out,
        "tax": tax,
        "total": fee_in + fee_out + tax,
    }


def slippage(
    *,
    price: float,
    side: Literal["buy", "sell"],
    tick_size: float,
    spread: float,
) -> float:
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
    direction = 1 if side == "buy" else -1
    return tick_size + 0.5 * spread * direction
