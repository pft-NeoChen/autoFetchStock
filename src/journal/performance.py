"""TASK-D03c — Performance metrics (V2 §5.3 / §6.1) — RED skeleton."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from src.backtest.engine import Trade

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


def total_return(equity: pd.Series) -> float:
    raise NotImplementedError("TASK-D03c GREEN pending")


def sharpe_ratio(equity: pd.Series, periods_per_year: int = 252) -> float:
    raise NotImplementedError("TASK-D03c GREEN pending")


def sortino_ratio(equity: pd.Series, periods_per_year: int = 252) -> float:
    raise NotImplementedError("TASK-D03c GREEN pending")


def max_drawdown(equity: pd.Series) -> float:
    raise NotImplementedError("TASK-D03c GREEN pending")


def win_rate(trades: list) -> float:
    raise NotImplementedError("TASK-D03c GREEN pending")


def profit_factor(trades: list) -> float:
    raise NotImplementedError("TASK-D03c GREEN pending")


def expectancy_bp(trades: list) -> float:
    raise NotImplementedError("TASK-D03c GREEN pending")


def turnover(trades: list, initial_capital: float) -> float:
    raise NotImplementedError("TASK-D03c GREEN pending")


def summarize_performance(
    *, trades: list, equity: pd.Series, initial_capital: float
) -> PerformanceMetrics:
    raise NotImplementedError("TASK-D03c GREEN pending")
