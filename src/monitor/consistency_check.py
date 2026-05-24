"""TASK-M02 — Live ↔ Backtest consistency check (V2 §9.2).

Compares live-trading metrics against backtest baseline; flags fall-out
beyond ``sigma`` standard deviations and recommends fallback to paper
mode when violations occur.

Schema is deliberately compact — feed it daily aggregated metrics from
the journal + experiment registry; refine fields as more dimensions
(trade-count, mean/std slippage, fill-rate) accumulate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

__all__ = [
    "ConsistencyMetric",
    "ConsistencyResult",
    "compare_live_to_backtest",
]


@dataclass(frozen=True)
class ConsistencyMetric:
    trade_count: float
    mean_slippage_bp: float
    std_slippage_bp: float


@dataclass(frozen=True)
class ConsistencyResult:
    passed: bool
    violations: List[str] = field(default_factory=list)
    recommended_action: str = "continue"  # "continue" | "fallback_to_paper"


def _within_band(value: float, center: float, half_width: float) -> bool:
    return (center - half_width) <= value <= (center + half_width)


def compare_live_to_backtest(
    *,
    live: ConsistencyMetric,
    backtest: ConsistencyMetric,
    sigma: float = 2.0,
    min_std: float = 1.0,
) -> ConsistencyResult:
    """Return a ``ConsistencyResult`` flagging metric violations.

    ``min_std`` floors zero/near-zero backtest std deviations so a single
    outlier doesn't degenerate to a zero-width band and reject everything.
    """
    violations: List[str] = []

    # trade_count band — backtest_std_slippage_bp doubles as a proxy
    # variability term (we lack a separate trade_count std today). Refine
    # when richer baseline aggregates land.
    count_std = max(backtest.std_slippage_bp, min_std)
    count_half = sigma * count_std
    if not _within_band(live.trade_count, backtest.trade_count, count_half):
        violations.append(
            f"trade_count outside {sigma}σ band "
            f"(live={live.trade_count}, bt={backtest.trade_count}±{count_half})"
        )

    # mean_slippage_bp band
    slip_std = max(backtest.std_slippage_bp, min_std)
    slip_half = sigma * slip_std
    if not _within_band(
        live.mean_slippage_bp, backtest.mean_slippage_bp, slip_half
    ):
        violations.append(
            f"mean_slippage_bp outside {sigma}σ band "
            f"(live={live.mean_slippage_bp}, bt={backtest.mean_slippage_bp}±{slip_half})"
        )

    passed = not violations
    return ConsistencyResult(
        passed=passed,
        violations=violations,
        recommended_action="continue" if passed else "fallback_to_paper",
    )
