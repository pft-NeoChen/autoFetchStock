"""TASK-X01 — OrderRouter Protocol + DryRunRouter (V2 §10).

Defines the minimal live-trading router contract used by paper / sim /
live routers. ``DryRunRouter`` is the log-only reference implementation
— it accepts orders, generates IDs, tracks state for query/cancel, and
**never** produces fills or positions. Used as a safe default before
wiring real broker APIs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Literal, Optional, Protocol, runtime_checkable

__all__ = [
    "DryRunRouter",
    "LiveOrder",
    "OrderID",
    "OrderRouter",
    "OrderRouterError",
    "OrderState",
    "OrderStatus",
    "Position",
    "UnknownOrderError",
]


OrderID = str


class OrderState(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


TERMINAL_STATES = frozenset(
    {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED}
)


class OrderRouterError(Exception):
    """Base error for router operations."""


class UnknownOrderError(OrderRouterError, KeyError):
    """Raised when an order id is not tracked by the router."""


@dataclass(frozen=True)
class LiveOrder:
    stock_id: str
    side: Literal["buy", "sell"]
    shares: int
    order_type: Literal["market", "limit"] = "market"
    limit_price: Optional[float] = None
    tif: Literal["day", "ioc", "fok"] = "day"
    submitted_at: Optional[datetime] = None
    client_tag: Optional[str] = None

    def __post_init__(self) -> None:
        if self.shares <= 0:
            raise ValueError(f"shares must be > 0, got {self.shares}")
        if self.order_type == "limit" and self.limit_price is None:
            raise ValueError("limit order requires limit_price")
        if self.order_type == "market" and self.limit_price is not None:
            raise ValueError("market order must not carry limit_price")


@dataclass(frozen=True)
class OrderStatus:
    order_id: OrderID
    order: LiveOrder
    state: OrderState
    filled_shares: int = 0
    avg_fill_price: Optional[float] = None
    last_update_ts: Optional[datetime] = None
    reject_reason: Optional[str] = None


@dataclass(frozen=True)
class Position:
    stock_id: str
    shares: int
    avg_cost: float


@runtime_checkable
class OrderRouter(Protocol):
    def submit(self, order: LiveOrder) -> OrderID: ...
    def cancel(self, order_id: OrderID) -> None: ...
    def query(self, order_id: OrderID) -> OrderStatus: ...
    def positions(self) -> List[Position]: ...


@dataclass
class _DryRunLogEntry:
    event: str
    order_id: OrderID
    ts: datetime
    detail: str = ""


class DryRunRouter:
    """Log-only router. No external side effects, no fills, no positions."""

    def __init__(self, *, id_prefix: str = "DRY") -> None:
        self._id_prefix = id_prefix
        self._counter = 0
        self._statuses: dict[OrderID, OrderStatus] = {}
        self._log: List[_DryRunLogEntry] = []

    @property
    def log(self) -> List[_DryRunLogEntry]:
        return list(self._log)

    def _next_id(self) -> OrderID:
        self._counter += 1
        return f"{self._id_prefix}-{self._counter:06d}"

    def _now(self, order: LiveOrder) -> datetime:
        return order.submitted_at or datetime.utcnow()

    def submit(self, order: LiveOrder) -> OrderID:
        oid = self._next_id()
        ts = self._now(order)
        self._statuses[oid] = OrderStatus(
            order_id=oid,
            order=order,
            state=OrderState.SUBMITTED,
            last_update_ts=ts,
        )
        self._log.append(
            _DryRunLogEntry(
                event="submit",
                order_id=oid,
                ts=ts,
                detail=f"{order.side} {order.shares} {order.stock_id}",
            )
        )
        return oid

    def cancel(self, order_id: OrderID) -> None:
        status = self._statuses.get(order_id)
        if status is None:
            raise UnknownOrderError(order_id)
        if status.state in TERMINAL_STATES:
            raise OrderRouterError(
                f"cannot cancel order {order_id} in terminal state {status.state.value}"
            )
        ts = datetime.utcnow()
        self._statuses[order_id] = OrderStatus(
            order_id=order_id,
            order=status.order,
            state=OrderState.CANCELLED,
            filled_shares=status.filled_shares,
            avg_fill_price=status.avg_fill_price,
            last_update_ts=ts,
        )
        self._log.append(
            _DryRunLogEntry(event="cancel", order_id=order_id, ts=ts)
        )

    def query(self, order_id: OrderID) -> OrderStatus:
        status = self._statuses.get(order_id)
        if status is None:
            raise UnknownOrderError(order_id)
        return status

    def positions(self) -> List[Position]:
        return []
