"""TASK-S1-E0 — trade-level resample bootstrap.

Resamples trade-level pnl_pct with replacement to produce 95% CIs for
expectancy_bp / sharpe / profit_factor / n_trades. Pure functions; no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np


__all__ = [
    "BootstrapStat",
    "bootstrap_trade_metrics",
    "expectancy_bp",
    "profit_factor",
    "sharpe_ratio",
]


@dataclass(frozen=True)
class BootstrapStat:
    point: float
    ci_low: float
    ci_high: float
    n_iter: int


def _pnl_array(trades: Sequence[dict]) -> np.ndarray:
    if not trades:
        return np.array([], dtype=float)
    return np.array([float(t.get("pnl_pct", float("nan"))) for t in trades], dtype=float)


def expectancy_bp(trades: Sequence[dict]) -> float:
    arr = _pnl_array(trades)
    if arr.size == 0:
        return float("nan")
    return float(np.nanmean(arr) * 10000.0)


def profit_factor(trades: Sequence[dict]) -> float:
    arr = _pnl_array(trades)
    if arr.size == 0:
        return float("nan")
    wins = float(arr[arr > 0].sum())
    losses = float(-arr[arr < 0].sum())
    if losses == 0:
        return float("inf") if wins > 0 else float("nan")
    return wins / losses


def sharpe_ratio(trades: Sequence[dict]) -> float:
    arr = _pnl_array(trades)
    if arr.size < 2:
        return float("nan")
    std = float(np.nanstd(arr, ddof=1))
    if std == 0:
        return 0.0
    mean = float(np.nanmean(arr))
    return mean / std


_METRICS: dict[str, Callable[[Sequence[dict]], float]] = {
    "expectancy_bp": expectancy_bp,
    "sharpe": sharpe_ratio,
    "profit_factor": profit_factor,
}


def bootstrap_trade_metrics(
    trades: Sequence[dict],
    *,
    n_iter: int = 100,
    seed: int = 42,
    ci_low: float = 0.025,
    ci_high: float = 0.975,
) -> dict[str, BootstrapStat]:
    if n_iter <= 0:
        raise ValueError("n_iter must be positive")
    rng = np.random.default_rng(seed)
    n = len(trades)
    if n == 0:
        nan_stat = BootstrapStat(float("nan"), float("nan"), float("nan"), n_iter)
        return {
            "expectancy_bp": nan_stat,
            "sharpe": nan_stat,
            "profit_factor": nan_stat,
            "n_trades": BootstrapStat(0, 0, 0, n_iter),
        }

    samples: dict[str, list[float]] = {key: [] for key in _METRICS}
    indices_matrix = rng.integers(low=0, high=n, size=(n_iter, n))
    for i in range(n_iter):
        sampled = [trades[int(j)] for j in indices_matrix[i]]
        for key, fn in _METRICS.items():
            value = fn(sampled)
            if math.isfinite(value):
                samples[key].append(value)

    result: dict[str, BootstrapStat] = {}
    for key, fn in _METRICS.items():
        point = fn(trades)
        arr = np.array(samples[key], dtype=float) if samples[key] else np.array([])
        if arr.size == 0:
            result[key] = BootstrapStat(point, float("nan"), float("nan"), n_iter)
            continue
        low = float(np.quantile(arr, ci_low))
        high = float(np.quantile(arr, ci_high))
        result[key] = BootstrapStat(point, low, high, n_iter)

    result["n_trades"] = BootstrapStat(n, n, n, n_iter)
    return result
