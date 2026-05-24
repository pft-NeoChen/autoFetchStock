"""TASK-S1-HELPER - event-study primitives for strategy research.

This module is intentionally research-only. It may depend on feature/backtest
helpers, but production signal modules must not depend on it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import ceil
from typing import Any

import numpy as np
import pandas as pd

from src.backtest.cost_model import round_trip_cost

__all__ = [
    "EventStudyResult",
    "GateVerdict",
    "compute_forward_returns",
    "evaluate_event_study_gate",
    "event_study",
]


@dataclass
class EventStudyResult:
    n_events: int
    base_rate: float
    hit_rate: float
    mean_return_bp: dict[int, float]
    median_return_bp: dict[int, float]
    top5pct_excluded_mean_bp: dict[int, float]
    return_distribution: dict[int, np.ndarray]
    cost_adjusted_mean_bp: dict[int, float]
    cost_adjusted_median_bp: dict[int, float]


@dataclass(frozen=True)
class GateVerdict:
    passed: bool
    reasons: list[str]


CostModel = Callable[..., Any]


_MEAN_BP_THRESHOLDS: dict[int, float] = {1: 10.0, 3: 30.0, 5: 50.0}
_MIN_EVENTS = 100
_MIN_HIT_RATE_SPREAD = 0.05


def compute_forward_returns(
    ohlc: pd.DataFrame,
    horizons: Sequence[int] = (1, 3, 5),
) -> pd.DataFrame:
    """Compute per-stock forward close-to-close returns for each horizon."""
    _validate_ohlc_index(ohlc)
    if not horizons:
        raise ValueError("horizons must not be empty")
    price_col = _price_column(ohlc)
    close = ohlc.sort_index()[price_col].astype(float)
    out = pd.DataFrame(index=close.index)
    for horizon in horizons:
        if horizon <= 0:
            raise ValueError("horizons must be positive integers")
        future = close.groupby(level="stock_id").shift(-horizon)
        out[f"forward_return_{horizon}d"] = future / close - 1.0
    return out


def event_study(
    trigger_mask: pd.Series | pd.DataFrame,
    ohlc: pd.DataFrame,
    horizons: Sequence[int] = (1, 3, 5),
    cost_model: CostModel | None = None,
) -> EventStudyResult:
    """Aggregate forward returns for trigger events.

    ``cost_model`` defaults to ``src.backtest.cost_model.round_trip_cost`` and
    is always converted to basis points from actual notional, avoiding a fixed
    hard-coded cost assumption.
    """
    _validate_ohlc_index(ohlc)
    if not horizons:
        raise ValueError("horizons must not be empty")
    cost_fn = cost_model or round_trip_cost
    sorted_ohlc = ohlc.sort_index()
    mask = _normalise_trigger_mask(trigger_mask, sorted_ohlc.index)
    forward_returns = compute_forward_returns(sorted_ohlc, horizons)
    primary_horizon = 5 if 5 in horizons else max(horizons)

    mean_return_bp: dict[int, float] = {}
    median_return_bp: dict[int, float] = {}
    top5pct_excluded_mean_bp: dict[int, float] = {}
    return_distribution: dict[int, np.ndarray] = {}
    cost_adjusted_mean_bp: dict[int, float] = {}
    cost_adjusted_median_bp: dict[int, float] = {}

    price = sorted_ohlc[_price_column(sorted_ohlc)].astype(float)
    primary_returns = pd.Series(dtype=float)

    for horizon in horizons:
        col = f"forward_return_{horizon}d"
        event_returns = forward_returns.loc[mask, col].dropna()
        if horizon == primary_horizon:
            primary_returns = event_returns

        returns_array = event_returns.to_numpy(dtype=float)
        return_distribution[horizon] = returns_array
        return_bp = returns_array * 10000.0
        mean_return_bp[horizon] = _mean_or_nan(return_bp)
        median_return_bp[horizon] = _median_or_nan(return_bp)
        top5pct_excluded_mean_bp[horizon] = _top5pct_excluded_mean(return_bp)

        costs_bp = _costs_in_bp(
            event_returns=event_returns,
            price=price,
            cost_model=cost_fn,
        )
        adjusted = return_bp - costs_bp
        cost_adjusted_mean_bp[horizon] = _mean_or_nan(adjusted)
        cost_adjusted_median_bp[horizon] = _median_or_nan(adjusted)

    event_dates = _event_dates(mask)
    primary_col = f"forward_return_{primary_horizon}d"
    base_returns = (
        forward_returns.loc[event_dates, primary_col].dropna()
        if event_dates
        else pd.Series(dtype=float)
    )
    base_rate = _positive_rate(base_returns)
    hit_rate = _positive_rate(primary_returns)

    return EventStudyResult(
        n_events=int(len(primary_returns)),
        base_rate=base_rate,
        hit_rate=hit_rate,
        mean_return_bp=mean_return_bp,
        median_return_bp=median_return_bp,
        top5pct_excluded_mean_bp=top5pct_excluded_mean_bp,
        return_distribution=return_distribution,
        cost_adjusted_mean_bp=cost_adjusted_mean_bp,
        cost_adjusted_median_bp=cost_adjusted_median_bp,
    )


def evaluate_event_study_gate(
    result: EventStudyResult,
    horizon: int = 5,
) -> GateVerdict:
    """Evaluate the S1 research gate for a single horizon."""
    mean_threshold = _MEAN_BP_THRESHOLDS.get(horizon, 50.0)
    reasons: list[str] = []

    if result.n_events < _MIN_EVENTS:
        reasons.append(f"n_events {result.n_events} < {_MIN_EVENTS}")

    cost_mean = result.cost_adjusted_mean_bp.get(horizon, float("nan"))
    if not np.isfinite(cost_mean) or cost_mean < mean_threshold:
        reasons.append(
            f"cost_adjusted_mean_{horizon}d {cost_mean:.2f} < {mean_threshold:.2f}"
        )

    cost_median = result.cost_adjusted_median_bp.get(horizon, float("nan"))
    if not np.isfinite(cost_median) or cost_median <= 0:
        reasons.append(f"cost_adjusted_median_{horizon}d {cost_median:.2f} <= 0")

    hit_spread = result.hit_rate - result.base_rate
    if not np.isfinite(hit_spread) or hit_spread < _MIN_HIT_RATE_SPREAD:
        reasons.append(
            f"hit_rate_minus_base_rate {hit_spread:.4f} < {_MIN_HIT_RATE_SPREAD:.4f}"
        )

    top5_excluded = result.top5pct_excluded_mean_bp.get(horizon, float("nan"))
    if not np.isfinite(top5_excluded) or top5_excluded <= 0:
        reasons.append(f"top5pct_excluded_mean_{horizon}d {top5_excluded:.2f} <= 0")

    return GateVerdict(passed=not reasons, reasons=reasons)


def _validate_ohlc_index(ohlc: pd.DataFrame) -> None:
    if not isinstance(ohlc.index, pd.MultiIndex):
        raise ValueError("ohlc index must be a MultiIndex(date, stock_id)")
    if "date" not in ohlc.index.names or "stock_id" not in ohlc.index.names:
        raise ValueError("ohlc index levels must be named 'date' and 'stock_id'")


def _price_column(ohlc: pd.DataFrame) -> str:
    if "adj_close" in ohlc.columns:
        return "adj_close"
    if "close" in ohlc.columns:
        return "close"
    raise ValueError("ohlc must include 'close' or 'adj_close'")


def _normalise_trigger_mask(
    trigger_mask: pd.Series | pd.DataFrame,
    index: pd.MultiIndex,
) -> pd.Series:
    if isinstance(trigger_mask, pd.DataFrame):
        if trigger_mask.empty:
            mask = pd.Series(False, index=trigger_mask.index)
        elif len(trigger_mask.columns) == 1:
            mask = trigger_mask.iloc[:, 0]
        else:
            mask = trigger_mask.any(axis=1)
    else:
        mask = trigger_mask
    return mask.reindex(index, fill_value=False).astype(bool)


def _event_dates(mask: pd.Series) -> list[pd.Timestamp]:
    if not mask.any():
        return []
    dates = mask[mask].index.get_level_values("date").unique()
    return list(dates)


def _mean_or_nan(values: np.ndarray) -> float:
    return float(np.mean(values)) if values.size else float("nan")


def _median_or_nan(values: np.ndarray) -> float:
    return float(np.median(values)) if values.size else float("nan")


def _top5pct_excluded_mean(return_bp: np.ndarray) -> float:
    if return_bp.size == 0:
        return float("nan")
    exclude_count = max(1, ceil(return_bp.size * 0.05))
    if exclude_count >= return_bp.size:
        return float("nan")
    trimmed = np.sort(return_bp)[:-exclude_count]
    return float(np.mean(trimmed)) if trimmed.size else float("nan")


def _positive_rate(values: pd.Series) -> float:
    if values.empty:
        return 0.0
    return float((values > 0).mean())


def _costs_in_bp(
    *,
    event_returns: pd.Series,
    price: pd.Series,
    cost_model: CostModel,
) -> np.ndarray:
    costs: list[float] = []
    for idx, ret in event_returns.items():
        price_in = float(price.loc[idx])
        price_out = price_in * (1.0 + float(ret))
        shares = 1.0
        raw_cost = cost_model(
            price_in=price_in,
            price_out=price_out,
            shares=shares,
            is_daytrade=False,
        )
        total = _cost_total(raw_cost)
        notional = price_in * shares
        costs.append(total / notional * 10000.0 if notional else float("nan"))
    return np.array(costs, dtype=float)


def _cost_total(raw_cost: dict[str, float] | float | Any) -> float:
    if isinstance(raw_cost, dict):
        return float(raw_cost.get("total", 0.0))
    return float(raw_cost)
