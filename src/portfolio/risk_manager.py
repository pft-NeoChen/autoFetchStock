"""TASK-R01 — Portfolio risk gates (V2 §4.2).

RiskManager is intentionally separate from SignalEngine. It accepts a proposed
entry size and answers whether it is allowed under account-level constraints:
single-trade risk, concurrent holdings, stock allocation, daily loss limit, and
loss-streak cooldown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional, Sequence

__all__ = [
    "PositionSnapshot",
    "RiskConfig",
    "RiskDecision",
    "RiskManager",
    "RiskState",
]


@dataclass(frozen=True)
class PositionSnapshot:
    stock_id: str
    market_value: float


@dataclass(frozen=True)
class RiskConfig:
    max_single_trade_risk_pct: float = 0.01
    max_daily_loss_pct: float = 0.02
    max_positions: int = 8
    max_stock_allocation_pct: float = 0.15
    losses_before_half_size: int = 3
    losses_before_cooldown: int = 5
    cooldown_trading_days: int = 1

    def __post_init__(self) -> None:
        _require_positive("max_single_trade_risk_pct", self.max_single_trade_risk_pct)
        _require_positive("max_daily_loss_pct", self.max_daily_loss_pct)
        _require_positive("max_positions", self.max_positions)
        _require_positive("max_stock_allocation_pct", self.max_stock_allocation_pct)
        _require_positive("losses_before_half_size", self.losses_before_half_size)
        _require_positive("losses_before_cooldown", self.losses_before_cooldown)
        if self.losses_before_cooldown < self.losses_before_half_size:
            raise ValueError("losses_before_cooldown must be >= losses_before_half_size")
        _require_positive("cooldown_trading_days", self.cooldown_trading_days)


@dataclass
class RiskState:
    current_date: Optional[date] = None
    realized_pnl_today: float = 0.0
    consecutive_losses: int = 0
    cooldown_until: Optional[date] = None


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    approved_shares: int
    risk_amount: float
    reasons: list[str] = field(default_factory=list)


class RiskManager:
    def __init__(self, config: Optional[RiskConfig] = None, state: Optional[RiskState] = None) -> None:
        self.config = config or RiskConfig()
        self.state = state or RiskState()

    def evaluate_entry(
        self,
        *,
        account_equity: float,
        stock_id: str,
        entry_price: float,
        stop_price: float,
        target_shares: int,
        trade_date: Optional[date] = None,
        open_positions: Optional[Sequence[PositionSnapshot]] = None,
        reduce_to_fit: bool = False,
    ) -> RiskDecision:
        if account_equity <= 0:
            raise ValueError("account_equity must be positive")
        if entry_price <= 0:
            raise ValueError("entry_price must be positive")
        if target_shares <= 0:
            return RiskDecision(False, 0, 0.0, ["non_positive_shares"])

        if trade_date is not None:
            self._roll_date(trade_date)

        reasons: list[str] = []
        shares = int(target_shares)
        positions = list(open_positions or [])

        if self.is_paused(on_date=trade_date):
            return RiskDecision(False, 0, self._risk_amount(entry_price, stop_price, shares), ["cooldown"])

        if self.state.realized_pnl_today <= -(account_equity * self.config.max_daily_loss_pct):
            return RiskDecision(
                False,
                0,
                self._risk_amount(entry_price, stop_price, shares),
                ["daily_loss_limit"],
            )

        if self._is_new_stock(stock_id, positions) and len(positions) >= self.config.max_positions:
            return RiskDecision(False, 0, self._risk_amount(entry_price, stop_price, shares), ["max_positions"])

        shares, allocation_reasons = self._apply_allocation_cap(
            account_equity=account_equity,
            stock_id=stock_id,
            entry_price=entry_price,
            shares=shares,
            positions=positions,
            reduce_to_fit=reduce_to_fit,
        )
        reasons.extend(allocation_reasons)
        if shares <= 0:
            return RiskDecision(False, 0, 0.0, reasons or ["stock_allocation"])

        per_share_risk = entry_price - stop_price
        if per_share_risk <= 0:
            return RiskDecision(False, 0, 0.0, ["invalid_stop_price"])

        max_risk = account_equity * self.config.max_single_trade_risk_pct
        risk_amount = per_share_risk * shares
        if risk_amount > max_risk:
            if not reduce_to_fit:
                return RiskDecision(False, 0, risk_amount, ["single_trade_risk"])
            shares = int(max_risk // per_share_risk)
            if shares <= 0:
                return RiskDecision(False, 0, 0.0, ["single_trade_risk"])
            risk_amount = per_share_risk * shares
            reasons.append("reduced_single_trade_risk")

        return RiskDecision(True, shares, risk_amount, reasons)

    def record_trade_result(self, realized_pnl: float, *, trade_date: date) -> RiskState:
        self._roll_date(trade_date)
        self.state.realized_pnl_today += realized_pnl

        if realized_pnl < 0:
            self.state.consecutive_losses += 1
            if self.state.consecutive_losses >= self.config.losses_before_cooldown:
                self.state.cooldown_until = add_trading_days(trade_date, self.config.cooldown_trading_days)
        else:
            self.state.consecutive_losses = 0
            self.state.cooldown_until = None

        return self.state

    def position_size_multiplier(self, *, on_date: Optional[date] = None) -> float:
        if self.is_paused(on_date=on_date):
            return 0.0
        if self.state.consecutive_losses >= self.config.losses_before_half_size:
            return 0.5
        return 1.0

    def is_paused(self, *, on_date: Optional[date] = None) -> bool:
        if self.state.cooldown_until is None:
            return False
        if on_date is None:
            return True
        return on_date <= self.state.cooldown_until

    def _roll_date(self, current: date) -> None:
        if self.state.current_date != current:
            self.state.current_date = current
            self.state.realized_pnl_today = 0.0

    def _apply_allocation_cap(
        self,
        *,
        account_equity: float,
        stock_id: str,
        entry_price: float,
        shares: int,
        positions: Sequence[PositionSnapshot],
        reduce_to_fit: bool,
    ) -> tuple[int, list[str]]:
        existing_value = sum(p.market_value for p in positions if p.stock_id == stock_id)
        max_value = account_equity * self.config.max_stock_allocation_pct
        proposed_value = existing_value + entry_price * shares
        if proposed_value <= max_value:
            return shares, []
        if not reduce_to_fit:
            return 0, ["stock_allocation"]

        max_new_value = max_value - existing_value
        approved = int(max_new_value // entry_price)
        if approved <= 0:
            return 0, ["stock_allocation"]
        return min(shares, approved), ["reduced_stock_allocation"]

    @staticmethod
    def _is_new_stock(stock_id: str, positions: Sequence[PositionSnapshot]) -> bool:
        return all(p.stock_id != stock_id for p in positions)

    @staticmethod
    def _risk_amount(entry_price: float, stop_price: float, shares: int) -> float:
        return max(entry_price - stop_price, 0.0) * max(shares, 0)


def add_trading_days(start: date, days: int) -> date:
    current = start
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def _require_positive(name: str, value: float) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")
