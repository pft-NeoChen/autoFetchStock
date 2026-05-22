"""TASK-B03 — Benchmark engine (V2 §3.5).

Computes five cumulative-return curves to compare any strategy against:

1. ``weighted_index``        — market index price-only return
2. ``etf_total_return``      — 0050 (or equivalent) total-return index
3. ``equal_weight_universe`` — equal-weighted universe with daily rebalance
4. ``ma_strategy``           — long market when MA_short > MA_long, else cash
5. ``cash``                  — flat 1.0 baseline
"""

from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd

__all__ = ["BenchmarkInputError", "compute_benchmarks"]


class BenchmarkInputError(ValueError):
    """Raised when benchmark inputs are missing or unusable."""


def _cumulative_from_price(series: pd.Series) -> pd.Series:
    s = series.astype(float).dropna()
    if s.empty:
        raise BenchmarkInputError("price series is empty")
    return (s / s.iloc[0]).reindex(series.index).ffill()


def _equal_weight_curve(universe_daily: Mapping[str, pd.DataFrame]) -> pd.Series:
    if not universe_daily:
        raise BenchmarkInputError("universe_daily is empty")

    closes = pd.DataFrame(
        {sid: df["close"].astype(float) for sid, df in universe_daily.items()}
    ).sort_index()
    returns = closes.pct_change()
    # Daily rebalance: equal weight = mean cross-section return.
    daily = returns.mean(axis=1, skipna=True).fillna(0.0)
    return (1.0 + daily).cumprod()


def _ma_strategy_curve(
    close: pd.Series,
    *,
    short_window: int,
    long_window: int,
) -> pd.Series:
    close = close.astype(float)
    short = close.rolling(window=short_window, min_periods=short_window).mean()
    long = close.rolling(window=long_window, min_periods=long_window).mean()
    # Decide at T-1, apply to T (no look-ahead).
    in_market = (short > long).shift(1).fillna(False).astype(bool)
    daily_return = close.pct_change().fillna(0.0)
    strat_return = daily_return.where(in_market, 0.0)
    return (1.0 + strat_return).cumprod()


def compute_benchmarks(
    *,
    market_index: pd.DataFrame,
    etf_total_return: pd.Series,
    universe_daily: Mapping[str, pd.DataFrame],
    ma_short_window: int = 20,
    ma_long_window: int = 60,
) -> dict[str, pd.Series]:
    if market_index is None or market_index.empty or "close" not in market_index.columns:
        raise BenchmarkInputError("market_index must be a non-empty DataFrame with 'close'")
    if etf_total_return is None or etf_total_return.empty:
        raise BenchmarkInputError("etf_total_return is required")

    idx = market_index.index

    weighted_index = _cumulative_from_price(market_index["close"]).reindex(idx).ffill()
    etf_curve = _cumulative_from_price(etf_total_return).reindex(idx).ffill()
    equal_weight = _equal_weight_curve(universe_daily).reindex(idx).ffill().fillna(1.0)
    ma_strategy = _ma_strategy_curve(
        market_index["close"],
        short_window=ma_short_window,
        long_window=ma_long_window,
    ).reindex(idx).fillna(1.0)
    cash = pd.Series(1.0, index=idx, name="cash")

    return {
        "weighted_index": weighted_index,
        "etf_total_return": etf_curve,
        "equal_weight_universe": equal_weight,
        "ma_strategy": ma_strategy,
        "cash": cash,
    }
