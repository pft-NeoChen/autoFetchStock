"""TASK-B04 — Single-stock backtester engine (V2 §3.1, §3.3, §3.7).

Self-built (no vectorbt) so we can wire ``cost_model`` + ``execution_model``
without adapter friction. Daily loop:

1. At T close, consult ``exit_decider`` for any open position.
2. Consult ``entry_decider`` if flat.
3. Pending orders → ``simulate_fill`` at T+1 open.
4. Track cash (T+2 ledger for sell proceeds) and equity (mark-to-market).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Optional

import pandas as pd

from src.backtest.cost_model import (
    TRANSACTION_TAX_DAYTRADE,
    TRANSACTION_TAX_NORMAL,
    commission,
)
from src.backtest.execution_model import (
    MarketBar,
    Order,
    next_business_day,
    simulate_fill,
)

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "Position",
    "Trade",
]


@dataclass
class Position:
    stock_id: str
    entry_date: date
    entry_price: float
    shares: int
    fees_in: float = 0.0
    highest_since_entry: float = 0.0


@dataclass
class Trade:
    stock_id: str
    entry_date: date
    entry_price: float
    exit_date: date
    exit_price: float
    shares: int
    pnl: float
    pnl_pct: float
    fees: float
    tax: float
    reason: str


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity_curve: pd.Series
    cash_curve: pd.Series
    final_equity: float
    final_cash: float


EntryDecider = Callable[[date, "pd.Series", bool], Optional[dict]]
ExitDecider = Callable[[date, "pd.Series", Position], Optional[str]]


@dataclass
class _PendingOrder:
    order: Order
    is_exit: bool
    reason: str = ""


class BacktestEngine:
    def __init__(
        self,
        *,
        initial_cash: float,
        entry_decider: EntryDecider,
        exit_decider: ExitDecider,
        is_daytrade: bool = False,
    ) -> None:
        self.initial_cash = float(initial_cash)
        self.entry_decider = entry_decider
        self.exit_decider = exit_decider
        self.is_daytrade = is_daytrade

    def run(self, *, stock_id: str, ohlc_df: pd.DataFrame) -> BacktestResult:
        df = ohlc_df.sort_index()
        cash_available = self.initial_cash
        pending_credits: dict[date, float] = {}  # T+2 settlement bucket
        position: Optional[Position] = None
        pending: Optional[_PendingOrder] = None
        trades: list[Trade] = []
        equity_history: list[tuple[pd.Timestamp, float]] = []
        cash_history: list[tuple[pd.Timestamp, float]] = []

        bar_index = list(df.index)
        for i, ts in enumerate(bar_index):
            today = ts.date() if hasattr(ts, "date") else ts
            row = df.loc[ts]

            # Settle any pending sell proceeds whose settlement date arrived.
            for sd in [d for d in pending_credits if d <= today]:
                cash_available += pending_credits.pop(sd)

            # Execute the pending order against this bar's open (T+1 for previous T's decision).
            if pending is not None:
                next_bar = _to_market_bar(today, row)
                fill = simulate_fill(pending.order, next_bar)
                if not fill.voided and fill.filled_shares > 0:
                    if pending.order.side == "buy":
                        cost = fill.fill_price * fill.filled_shares
                        fee_in = commission(cost)
                        # Affordability check (re-cap if cash short).
                        if cost + fee_in > cash_available:
                            affordable = int(cash_available // (fill.fill_price * (1 + 0.002)))
                            affordable = (affordable // 1000) * 1000
                            if affordable <= 0:
                                pending = None
                                _record(equity_history, cash_history, ts, cash_available, position, row)
                                continue
                            fill_shares = affordable
                            cost = fill.fill_price * fill_shares
                            fee_in = commission(cost)
                        else:
                            fill_shares = fill.filled_shares
                        cash_available -= cost + fee_in
                        position = Position(
                            stock_id=stock_id,
                            entry_date=fill.fill_date,
                            entry_price=fill.fill_price,
                            shares=fill_shares,
                            fees_in=fee_in,
                            highest_since_entry=float(row["high"]),
                        )
                    else:  # sell — closing position
                        assert position is not None
                        proceeds = fill.fill_price * fill.filled_shares
                        fee_out = commission(proceeds)
                        tax_rate = TRANSACTION_TAX_DAYTRADE if self.is_daytrade else TRANSACTION_TAX_NORMAL
                        tax = proceeds * tax_rate
                        net = proceeds - fee_out - tax
                        # T+2 settlement
                        pending_credits[fill.settlement_date] = pending_credits.get(fill.settlement_date, 0.0) + net
                        pnl = (
                            (fill.fill_price - position.entry_price) * position.shares
                            - position.fees_in
                            - fee_out
                            - tax
                        )
                        trades.append(
                            Trade(
                                stock_id=stock_id,
                                entry_date=position.entry_date,
                                entry_price=position.entry_price,
                                exit_date=fill.fill_date,
                                exit_price=fill.fill_price,
                                shares=position.shares,
                                pnl=pnl,
                                pnl_pct=pnl / (position.entry_price * position.shares),
                                fees=position.fees_in + fee_out,
                                tax=tax,
                                reason=pending.reason,
                            )
                        )
                        position = None
                pending = None

            # Update trailing high for open position.
            if position is not None:
                position.highest_since_entry = max(position.highest_since_entry, float(row["high"]))

            # Decide today's actions (orders submitted at close, executed next bar).
            if position is not None:
                reason = self.exit_decider(today, row, position)
                if reason is not None:
                    pending = _PendingOrder(
                        order=Order(
                            stock_id=stock_id,
                            side="sell",
                            shares=position.shares,
                            submitted_at=datetime.combine(today, datetime.min.time()),
                        ),
                        is_exit=True,
                        reason=reason,
                    )
            else:
                decision = self.entry_decider(today, row, False)
                if decision is not None:
                    pending = _PendingOrder(
                        order=Order(
                            stock_id=stock_id,
                            side="buy",
                            shares=int(decision["target_shares"]),
                            submitted_at=datetime.combine(today, datetime.min.time()),
                        ),
                        is_exit=False,
                    )

            _record(equity_history, cash_history, ts, cash_available, position, row)

        equity_curve = pd.Series(
            [v for _, v in equity_history], index=[t for t, _ in equity_history], name="equity"
        )
        cash_curve = pd.Series(
            [v for _, v in cash_history], index=[t for t, _ in cash_history], name="cash"
        )
        # Final equity includes pending settlements + mark-to-market of any open position.
        final_cash = cash_available + sum(pending_credits.values())
        mtm = position.shares * df["close"].iloc[-1] if position else 0.0
        final_equity = final_cash + mtm

        return BacktestResult(
            trades=trades,
            equity_curve=equity_curve,
            cash_curve=cash_curve,
            final_equity=final_equity,
            final_cash=final_cash,
        )


def _to_market_bar(today: date, row: "pd.Series") -> MarketBar:
    return MarketBar(
        date=today,
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=int(row["volume"]),
        previous_close=float(row.get("previous_close", row["open"])),
    )


def _record(
    equity_history: list,
    cash_history: list,
    ts: pd.Timestamp,
    cash: float,
    position: Optional[Position],
    row: "pd.Series",
) -> None:
    mtm = position.shares * float(row["close"]) if position else 0.0
    equity_history.append((ts, cash + mtm))
    cash_history.append((ts, cash))
