"""TASK-B02 — Execution model (V2 §3.3 / §3.7).

Pure simulator for a single order:
- Signal at bar T close → fill at bar T+1 open.
- Fully-locked limit-up / -down bars void the order (高=低=當日收盤).
- Single order ≤ 5% of next-bar volume (liquidity cap).
- Whole-share orders rounded down to multiples of LOT_SIZE (1000 shares).
- Settlement date = fill_date + 2 business days (Mon-Fri).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal, Optional

__all__ = [
    "LIQUIDITY_CAP_PCT",
    "LOT_SIZE",
    "FillResult",
    "MarketBar",
    "Order",
    "next_business_day",
    "simulate_fill",
]


LOT_SIZE: int = 1000
LIQUIDITY_CAP_PCT: float = 0.05
LIMIT_PCT: float = 0.10


@dataclass(frozen=True)
class Order:
    stock_id: str
    side: Literal["buy", "sell"]
    shares: int
    submitted_at: datetime
    is_odd_lot: bool = False


@dataclass(frozen=True)
class MarketBar:
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    previous_close: float


@dataclass(frozen=True)
class FillResult:
    order: Order
    filled_shares: int
    fill_price: float
    fill_date: date
    settlement_date: date
    voided: bool = False
    voided_reason: str = ""


def next_business_day(d: date, *, n: int = 1) -> date:
    out = d
    while n > 0:
        out += timedelta(days=1)
        if out.weekday() < 5:
            n -= 1
    return out


def _is_locked(bar: MarketBar) -> str:
    """Return 'limit_up' / 'limit_down' / '' depending on lock state."""
    # Fully locked = high == low == open == close. Treat as locked when range == 0.
    if bar.high == bar.low and bar.open == bar.high == bar.close:
        if bar.close > bar.previous_close:
            return "limit_up"
        if bar.close < bar.previous_close:
            return "limit_down"
    return ""


def _voided(order: Order, reason: str) -> FillResult:
    return FillResult(
        order=order,
        filled_shares=0,
        fill_price=0.0,
        fill_date=date.min,
        settlement_date=date.min,
        voided=True,
        voided_reason=reason,
    )


def simulate_fill(order: Order, next_bar: Optional[MarketBar]) -> FillResult:
    if next_bar is None:
        return _voided(order, "no_next_bar")

    lock = _is_locked(next_bar)
    if lock:
        return _voided(order, lock)

    # Quantity normalisation
    if order.is_odd_lot:
        desired = order.shares
    else:
        desired = (order.shares // LOT_SIZE) * LOT_SIZE
    if desired <= 0:
        return _voided(order, "below_lot_size")

    # Liquidity cap
    raw_cap = int(next_bar.volume * LIQUIDITY_CAP_PCT)
    cap = raw_cap if order.is_odd_lot else (raw_cap // LOT_SIZE) * LOT_SIZE
    filled = min(desired, cap)
    if filled <= 0:
        return _voided(order, "insufficient_liquidity")

    return FillResult(
        order=order,
        filled_shares=filled,
        fill_price=next_bar.open,
        fill_date=next_bar.date,
        settlement_date=next_business_day(next_bar.date, n=2),
        voided=False,
        voided_reason="",
    )
