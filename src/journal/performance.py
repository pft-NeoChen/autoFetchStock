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
    "average_win_loss_ratio",
    "benchmark_alpha",
    "expectancy_bp",
    "max_drawdown",
    "oos_is_ratio",
    "profit_factor",
    "render_performance_report",
    "sharpe_ratio",
    "sortino_ratio",
    "summarize_performance",
    "top_n_excluded_return",
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
    avg_win_loss_ratio: float = 0.0
    oos_is_ratio: float = 0.0
    top5_excluded_return: float = 0.0
    benchmark_alpha: float = 0.0


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


def average_win_loss_ratio(trades: Iterable) -> float:
    trades = list(trades)
    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [-t.pnl for t in trades if t.pnl < 0]
    if not wins or not losses:
        return 0.0
    return float(np.mean(wins)) / float(np.mean(losses))


def oos_is_ratio(*, oos_return: float, is_return: float) -> float:
    if is_return == 0:
        return 0.0
    return oos_return / is_return


def top_n_excluded_return(trades: Iterable, *, initial_capital: float, n: int = 5) -> float:
    trades = list(trades)
    if not trades or initial_capital == 0:
        return 0.0
    remaining = sorted(trades, key=lambda t: t.pnl, reverse=True)[max(n, 0):]
    return sum(t.pnl for t in remaining) / initial_capital


def benchmark_alpha(*, strategy_return: float, benchmark_return: float) -> float:
    return strategy_return - benchmark_return


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
    benchmark_return: float = 0.0,
    is_return: float = 0.0,
    top_n: int = 5,
) -> PerformanceMetrics:
    trades = list(trades)
    strategy_return = total_return(equity)
    return PerformanceMetrics(
        n_trades=len(trades),
        total_return=strategy_return,
        sharpe=sharpe_ratio(equity),
        sortino=sortino_ratio(equity),
        max_drawdown=max_drawdown(equity),
        win_rate=win_rate(trades),
        profit_factor=profit_factor(trades),
        expectancy_bp=expectancy_bp(trades),
        turnover=turnover(trades, initial_capital),
        avg_win_loss_ratio=average_win_loss_ratio(trades),
        oos_is_ratio=oos_is_ratio(oos_return=strategy_return, is_return=is_return),
        top5_excluded_return=top_n_excluded_return(
            trades,
            initial_capital=initial_capital,
            n=top_n,
        ),
        benchmark_alpha=benchmark_alpha(
            strategy_return=strategy_return,
            benchmark_return=benchmark_return,
        ),
    )


def render_performance_report(metrics: PerformanceMetrics) -> str:
    lines = [
        "# Performance Report",
        "",
        "| 指標 | 值 |",
        "|------|----|",
        f"| 交易次數 | {metrics.n_trades} |",
        f"| 總報酬 | {metrics.total_return * 100:.2f}% |",
        f"| Sharpe（年化） | {_fmt_num(metrics.sharpe)} |",
        f"| Sortino | {_fmt_num(metrics.sortino)} |",
        f"| Max Drawdown | {metrics.max_drawdown * 100:.2f}% |",
        f"| 勝率 | {metrics.win_rate * 100:.2f}% |",
        f"| 平均盈虧比 | {_fmt_num(metrics.avg_win_loss_ratio)} |",
        f"| Profit Factor | {_fmt_num(metrics.profit_factor)} |",
        f"| 期望值（bp/trade） | {_fmt_num(metrics.expectancy_bp)} |",
        f"| OOS / IS | {_fmt_num(metrics.oos_is_ratio)} |",
        f"| Top-5 交易剔除後報酬 | {metrics.top5_excluded_return * 100:.2f}% |",
        f"| Benchmark Alpha | {metrics.benchmark_alpha * 100:.2f}% |",
        f"| Turnover | {_fmt_num(metrics.turnover)} |",
        "",
    ]
    return "\n".join(lines)


def _fmt_num(x: float) -> str:
    if x == float("inf"):
        return "∞"
    if x == float("-inf"):
        return "-∞"
    return f"{x:.2f}"
