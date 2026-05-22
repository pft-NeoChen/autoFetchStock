"""TASK-D03a — Bridge signal rules (S03 / S04) and BacktestEngine deciders.

`build_entry_conditions` / `build_exit_conditions` materialise the rule-input
dataclasses from a feature row, applying safe defaults for missing columns so
sparse feature frames never crash the engine — instead they fail the
rule's checks (the conservative outcome).

`make_entry_decider` / `make_exit_decider` close over the full feature frame
and market series and return Callables that match BacktestEngine's expected
``entry_decider`` / ``exit_decider`` signatures.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Mapping, Optional

import pandas as pd

from src.backtest.engine import Position
from src.signals.rules.exits import ExitConditions, evaluate_exit
from src.signals.rules.long_entry import EntryConditions, evaluate_long_entry

__all__ = [
    "build_entry_conditions",
    "build_exit_conditions",
    "make_entry_decider",
    "make_exit_decider",
]


def _get(row: pd.Series, key: str, default: Any) -> Any:
    if key in row.index:
        val = row[key]
        if pd.isna(val):
            return default
        return val
    return default


def build_entry_conditions(
    *,
    row: pd.Series,
    market_close: float,
    market_ma_60: float,
    breached_daily_loss: bool,
) -> EntryConditions:
    close = float(_get(row, "close", 0.0))
    open_ = float(_get(row, "open", 0.0))
    high = float(_get(row, "high", max(close, open_)))
    candle_body = abs(close - open_)
    upper_shadow = max(0.0, high - max(close, open_))
    return EntryConditions(
        close=close,
        open=open_,
        ma_5=float(_get(row, "ma_5", 0.0)),
        ma_20=float(_get(row, "ma_20", 0.0)),
        ma_60=float(_get(row, "ma_60", 0.0)),
        upper_shadow=upper_shadow,
        candle_body=candle_body,
        atr_14=float(_get(row, "atr_14", 0.0)),
        spike_severity=str(_get(row, "spike_severity", "normal")),
        high_20d=float(_get(row, "high_20d", float("inf"))),  # inf → no breakout
        foreign_net_streak=int(_get(row, "foreign_net_streak", 0)),
        margin_balance_5d_change=float(_get(row, "margin_balance_5d_change", 0.0)),
        market_close=float(market_close),
        market_ma_60=float(market_ma_60),
        is_limit_up=bool(_get(row, "is_limit_up", False)),
        news_severity=float(_get(row, "news_severity", 0.0)),
        breached_daily_loss=bool(breached_daily_loss),
    )


def build_exit_conditions(
    *,
    row: pd.Series,
    position: Position,
    days_held: int,
    ma_10_value: Optional[float] = None,
    trend_active: Optional[bool] = None,
) -> ExitConditions:
    close = float(_get(row, "close", 0.0))
    open_ = float(_get(row, "open", 0.0))
    candle_body = abs(close - open_)
    ma_10 = float(_get(row, "ma_10", ma_10_value if ma_10_value is not None else 0.0))
    ma_20 = float(_get(row, "ma_20", 0.0))
    if trend_active is None:
        trend_active = close > ma_20 if ma_20 > 0 else True
    return ExitConditions(
        entry_price=position.entry_price,
        current_close=close,
        current_open=open_,
        ma_10=ma_10,
        atr_14=float(_get(row, "atr_14", 0.0)),
        spike_severity=str(_get(row, "spike_severity", "normal")),
        candle_body=candle_body,
        highest_since_entry=position.highest_since_entry,
        days_held=days_held,
        trend_active=bool(trend_active),
    )


def make_entry_decider(
    *,
    feature_df: pd.DataFrame,
    market_state: Mapping[pd.Timestamp, dict[str, float]],
    target_shares: int = 1000,
    daily_loss_provider: Optional[Callable[[date], bool]] = None,
) -> Callable[[date, pd.Series, bool], Optional[dict]]:
    def decider(d: date, row: pd.Series, has_position: bool) -> Optional[dict]:
        if has_position:
            return None
        ts = pd.Timestamp(d)
        market = market_state.get(ts, {})
        market_close = float(market.get("market_close", 0.0))
        market_ma_60 = float(market.get("market_ma_60", 0.0))
        breached = bool(daily_loss_provider(d)) if daily_loss_provider else False
        conditions = build_entry_conditions(
            row=row,
            market_close=market_close,
            market_ma_60=market_ma_60,
            breached_daily_loss=breached,
        )
        ok, reasons, _ = evaluate_long_entry(conditions)
        if not ok:
            return None
        return {"target_shares": target_shares, "reasons": reasons}

    return decider


def make_exit_decider(
    *,
    feature_df: pd.DataFrame,
) -> Callable[[date, pd.Series, Position], Optional[str]]:
    def decider(d: date, row: pd.Series, position: Position) -> Optional[str]:
        days_held = max(0, (d - position.entry_date).days)
        conditions = build_exit_conditions(row=row, position=position, days_held=days_held)
        should_exit, reasons = evaluate_exit(conditions)
        if not should_exit:
            return None
        return ",".join(reasons)

    return decider
