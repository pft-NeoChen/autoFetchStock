"""TASK-S01 — IC / decay / monotonicity analysis (V2 §1).

All functions are pure: they take feature / forward-return ``pd.Series``
indexed by ``(date, stock_id)`` MultiIndex and return summary dicts.

Definitions:
- IC at date T = Spearman rank correlation between feature(T) and
  forward_return(T) across the cross-section of stocks.
- ic_mean / ic_std / ic_ir = mean, std, mean/std of the daily IC series.
- p_value = two-sided t-test of the IC series against 0.
- Decay curve = IC stats for each holding-period horizon.
- Monotonicity = mean forward return per equal-sized feature quantile.
"""

from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd
from scipy import stats

__all__ = [
    "IC_THRESHOLDS",
    "compute_ic",
    "decay_curve",
    "meets_ic_threshold",
    "monotonicity_test",
]


# V2 §1 修訂建議
IC_THRESHOLDS: dict[int, float] = {1: 0.02, 5: 0.03, 20: 0.04}


def _daily_ic_series(feature: pd.Series, forward_return: pd.Series) -> pd.Series:
    """Spearman corr per date across the cross-section of stocks."""
    df = pd.concat([feature.rename("f"), forward_return.rename("r")], axis=1).dropna()
    if df.empty:
        return pd.Series(dtype=float)

    ics: list[tuple[pd.Timestamp, float]] = []
    for ts, group in df.groupby(level="date"):
        if len(group) < 2:
            continue
        f = group["f"].to_numpy()
        r = group["r"].to_numpy()
        if np.std(f) == 0 or np.std(r) == 0:
            continue
        rho, _ = stats.spearmanr(f, r)
        if rho is None or np.isnan(rho):
            continue
        ics.append((ts, float(rho)))

    if not ics:
        return pd.Series(dtype=float)
    return pd.Series([v for _, v in ics], index=[t for t, _ in ics]).sort_index()


def compute_ic(feature: pd.Series, forward_return: pd.Series) -> dict[str, float]:
    series = _daily_ic_series(feature, forward_return)
    if series.empty:
        return {
            "ic_mean": float("nan"),
            "ic_std": float("nan"),
            "ic_ir": float("nan"),
            "p_value": float("nan"),
            "n_periods": 0,
        }
    mean = float(series.mean())
    std = float(series.std(ddof=1)) if len(series) > 1 else 0.0
    if std == 0:
        ir = float("inf") if mean != 0 else 0.0
        p_value = 0.0 if mean != 0 else 1.0
    else:
        ir = mean / std
        _, p_value = stats.ttest_1samp(series.to_numpy(), 0.0)
        p_value = float(p_value)
    return {
        "ic_mean": mean,
        "ic_std": std,
        "ic_ir": float(ir),
        "p_value": p_value,
        "n_periods": int(len(series)),
    }


def decay_curve(
    feature: pd.Series,
    forward_returns_by_horizon: Mapping[int, pd.Series],
) -> dict[int, dict[str, float]]:
    return {h: compute_ic(feature, ret) for h, ret in forward_returns_by_horizon.items()}


def monotonicity_test(
    feature: pd.Series,
    forward_return: pd.Series,
    *,
    n_groups: int = 5,
) -> list[float]:
    """Return list of mean forward-returns per feature quantile (low → high)."""
    if n_groups < 2:
        raise ValueError("n_groups must be >= 2")
    df = pd.concat(
        [feature.rename("f"), forward_return.rename("r")], axis=1
    ).dropna()
    if df.empty:
        return [float("nan")] * n_groups
    try:
        df["bucket"] = pd.qcut(df["f"], q=n_groups, labels=False, duplicates="drop")
    except ValueError:
        return [float("nan")] * n_groups
    means = df.groupby("bucket")["r"].mean().sort_index()
    out = [float("nan")] * n_groups
    for bucket, val in means.items():
        if 0 <= bucket < n_groups:
            out[int(bucket)] = float(val)
    return out


def meets_ic_threshold(ic_mean: float, *, horizon_days: int) -> bool:
    threshold = IC_THRESHOLDS.get(horizon_days)
    if threshold is None:
        raise ValueError(f"no threshold defined for horizon={horizon_days}")
    return abs(ic_mean) >= threshold
