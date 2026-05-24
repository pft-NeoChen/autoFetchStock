"""TASK-P01 — Memory paper router (V2 §8.2).

Pure in-memory paper-trading router. Implements the
:class:`src.execution.order_router.OrderRouter` Protocol so the live
signal pipeline can route to it without code changes when paper mode
is selected.

Behaviour (first version, intentionally simple):
* Market orders fill **immediately** at the price returned by an
  injected ``quote_provider(stock_id) -> float``.
* Limit orders are not supported (will reject — raise a future task to
  add limit-order queue).
* Buy fills require enough cash (cash − fill notional ≥ 0); else
  REJECTED.
* Sell fills require an existing long position with enough shares;
  else REJECTED.
* Realized PnL accumulates on close (or partial close); avg_cost stays
  fixed on partial close.
* Cost model / slippage / settlement T+2 are **not** yet applied —
  parity with :mod:`src.backtest.cost_model` is a follow-up.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

from src.execution.order_router import (
    LiveOrder,
    OrderID,
    OrderRouterError,
    OrderState,
    OrderStatus,
    Position,
    TERMINAL_STATES,
    UnknownOrderError,
)

__all__ = ["MemoryRouter"]


QuoteProvider = Callable[[str], float]


@dataclass
class _InternalPosition:
    shares: int
    avg_cost: float


class MemoryRouter:
    def __init__(
        self,
        *,
        initial_cash: float,
        quote_provider: QuoteProvider,
        id_prefix: str = "PAPER",
    ) -> None:
        if initial_cash < 0:
            raise ValueError("initial_cash must be >= 0")
        self._cash = float(initial_cash)
        self._quote = quote_provider
        self._id_prefix = id_prefix
        self._counter = 0
        self._statuses: Dict[OrderID, OrderStatus] = {}
        self._positions: Dict[str, _InternalPosition] = {}
        self.realized_pnl: float = 0.0

    # ── basic accessors ────────────────────────────────────────────────────
    @property
    def cash(self) -> float:
        return self._cash

    def positions(self) -> List[Position]:
        return [
            Position(stock_id=sid, shares=pos.shares, avg_cost=pos.avg_cost)
            for sid, pos in self._positions.items()
            if pos.shares > 0
        ]

    def query(self, order_id: OrderID) -> OrderStatus:
        status = self._statuses.get(order_id)
        if status is None:
            raise UnknownOrderError(order_id)
        return status

    def cancel(self, order_id: OrderID) -> None:
        status = self._statuses.get(order_id)
        if status is None:
            raise UnknownOrderError(order_id)
        if status.state in TERMINAL_STATES:
            raise OrderRouterError(
                f"cannot cancel order {order_id} in terminal state {status.state.value}"
            )
        self._statuses[order_id] = OrderStatus(
            order_id=order_id,
            order=status.order,
            state=OrderState.CANCELLED,
            filled_shares=status.filled_shares,
            avg_fill_price=status.avg_fill_price,
            last_update_ts=datetime.utcnow(),
        )

    # ── order entry ────────────────────────────────────────────────────────
    def submit(self, order: LiveOrder) -> OrderID:
        oid = self._next_id()
        if order.order_type != "market":
            self._record_reject(oid, order, "limit_orders_not_supported")
            return oid

        try:
            price = float(self._quote(order.stock_id))
        except Exception as exc:  # noqa: BLE001
            self._record_reject(oid, order, f"quote_lookup_failed: {exc}")
            return oid

        if order.side == "buy":
            return self._fill_buy(oid, order, price)
        return self._fill_sell(oid, order, price)

    # ── internal helpers ──────────────────────────────────────────────────
    def _next_id(self) -> OrderID:
        self._counter += 1
        return f"{self._id_prefix}-{self._counter:06d}"

    def _record_reject(self, oid: OrderID, order: LiveOrder, reason: str) -> None:
        self._statuses[oid] = OrderStatus(
            order_id=oid,
            order=order,
            state=OrderState.REJECTED,
            last_update_ts=datetime.utcnow(),
            reject_reason=reason,
        )

    def _record_filled(
        self, oid: OrderID, order: LiveOrder, price: float
    ) -> None:
        self._statuses[oid] = OrderStatus(
            order_id=oid,
            order=order,
            state=OrderState.FILLED,
            filled_shares=order.shares,
            avg_fill_price=price,
            last_update_ts=datetime.utcnow(),
        )

    def _fill_buy(self, oid: OrderID, order: LiveOrder, price: float) -> OrderID:
        notional = price * order.shares
        if notional > self._cash:
            self._record_reject(oid, order, f"insufficient_cash need={notional} have={self._cash}")
            return oid
        self._cash -= notional

        existing = self._positions.get(order.stock_id)
        if existing is None:
            self._positions[order.stock_id] = _InternalPosition(
                shares=order.shares, avg_cost=price
            )
        else:
            total_shares = existing.shares + order.shares
            existing.avg_cost = (
                (existing.shares * existing.avg_cost + order.shares * price)
                / total_shares
            )
            existing.shares = total_shares
        self._record_filled(oid, order, price)
        return oid

    def _fill_sell(self, oid: OrderID, order: LiveOrder, price: float) -> OrderID:
        existing = self._positions.get(order.stock_id)
        if existing is None or existing.shares <= 0:
            self._record_reject(oid, order, "no_position")
            return oid
        if existing.shares < order.shares:
            self._record_reject(
                oid, order,
                f"insufficient_shares need={order.shares} have={existing.shares}",
            )
            return oid
        notional = price * order.shares
        self.realized_pnl += (price - existing.avg_cost) * order.shares
        self._cash += notional
        existing.shares -= order.shares
        if existing.shares == 0:
            del self._positions[order.stock_id]
        self._record_filled(oid, order, price)
        return oid
