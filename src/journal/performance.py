"""TASK-D03c — Performance metrics (V2 §5.3 / §6.1).

Pure functions over ``equity`` (pd.Series) and ``trades`` (list[Trade]) plus a
``summarize_performance`` aggregator that returns a ``PerformanceMetrics``
dataclass for downstream decision gating and reporting.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

__all__ = [
    "PerformanceMetrics",
    "expectancy_bp",
    "max_drawdown",
    "profit_factor",
    "sharpe_ratio",
    "sortino_ratio",
    "summarize_performance",
    "total_return",
    "turnover",
    "win_rate",
]


@dataclass
class PerformanceMetrics:
    n_trades: int
    total_return: float
    sharpe: float
    sortino: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    expectancy_bp: float
    turnover: float


def _returns(equity: pd.Series) -> pd.Series:
    return equity.astype(float).pct_change().dropna()


def total_return(equity: pd.Series) -> float:
    if equity.empty or len(equity) < 2:
        return 0.0
    start = float(equity.iloc[0])
    end = float(equity.iloc[-1])
    if start == 0:
        return 0.0
    return end / start - 1.0


def sharpe_ratio(equity: pd.Series, periods_per_year: int = 252) -> float:
    rets = _returns(equity)
    if rets.empty:
        return 0.0
    std = float(rets.std(ddof=0))
    if std == 0.0:
        return 0.0
    return math.sqrt(periods_per_year) * float(rets.mean()) / std


def sortino_ratio(equity: pd.Series, periods_per_year: int = 252) -> float:
    rets = _returns(equity)
    if rets.empty:
        return 0.0
    downside = rets[rets < 0]
    mean = float(rets.mean())
    if downside.empty:
        return float("inf") if mean > 0 else 0.0
    dd = float(downside.std(ddof=0))
    if dd == 0.0:
        return float("inf") if mean > 0 else 0.0
    return math.sqrt(periods_per_year) * mean / dd


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    eq = equity.astype(float)
    running_peak = eq.cummax()
    drawdown = (running_peak - eq) / running_peak
    return float(drawdown.max())


def win_rate(trades: Iterable) -> float:
    trades = list(trades)
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.pnl > 0)
    return wins / len(trades)


def profit_factor(trades: Iterable) -> float:
    trades = list(trades)
    if not trades:
        return 0.0
    gains = sum(t.pnl for t in trades if t.pnl > 0)
    losses = -sum(t.pnl for t in trades if t.pnl < 0)
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def expectancy_bp(trades: Iterable) -> float:
    trades = list(trades)
    if not trades:
        return 0.0
    return float(np.mean([t.pnl_pct for t in trades])) * 10_000


def turnover(trades: Iterable, initial_capital: float) -> float:
    trades = list(trades)
    if not trades or initial_capital == 0:
        return 0.0
    gross = sum(2 * t.entry_price * t.shares for t in trades)  # round-trip
    return gross / initial_capital


def summarize_performance(
    *,
    trades: Iterable,
    equity: pd.Series,
    initial_capital: float,
) -> PerformanceMetrics:
    trades = list(trades)
    return PerformanceMetrics(
        n_trades=len(trades),
        total_return=total_return(equity),
        sharpe=sharpe_ratio(equity),
        sortino=sortino_ratio(equity),
        max_drawdown=max_drawdown(equity),
        win_rate=win_rate(trades),
        profit_factor=profit_factor(trades),
        expectancy_bp=expectancy_bp(trades),
        turnover=turnover(trades, initial_capital),
    )
