"""TASK-F06 — Chip features (V2 §0.3, §0.5).

Day-level wrappers around institutional and margin data.

Look-ahead rule (V2 §0.5): chip / margin data for date T-1 is published
post-close and becomes available before T's pre-open (08:30). For row date T
we therefore use chip/margin values from T-1 (or the most recent prior
trading day) so the FeatureStore signal timestamp at T 13:30 sees data that
was already available.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Mapping

import numpy as np
import pandas as pd

from src.features.store import FeatureProvider, FeatureValue

__all__ = [
    "chip_feature_providers",
    "foreign_net_streak",
    "margin_n_day_change",
    "rolling_net_buy",
]


PRE_OPEN_TIME = time(8, 30)


def foreign_net_streak(net: pd.Series) -> pd.Series:
    """Return signed consecutive-day streak length.

    Positive value N means N consecutive net-buy days ending at index;
    negative value -N means N consecutive net-sell days; 0 means net flat.
    """
    out = np.zeros(len(net), dtype=int)
    prev = 0
    for i, val in enumerate(net.astype(float)):
        if val > 0:
            prev = prev + 1 if prev > 0 else 1
        elif val < 0:
            prev = prev - 1 if prev < 0 else -1
        else:
            prev = 0
        out[i] = prev
    return pd.Series(out, index=net.index, dtype=int)


def rolling_net_buy(net: pd.Series, *, window: int = 5) -> pd.Series:
    if window <= 0:
        raise ValueError("window must be positive")
    return net.astype(float).rolling(window=window, min_periods=window).sum()


def margin_n_day_change(margin_balance: pd.Series, *, n: int = 5) -> pd.Series:
    if n <= 0:
        raise ValueError("n must be positive")
    return margin_balance.astype(float) - margin_balance.astype(float).shift(n)


def _prior_value(series: pd.Series, ref_ts: pd.Timestamp) -> float | None:
    """Return value at the latest index strictly before ref_ts; None if none."""
    mask = series.index < ref_ts
    if not mask.any():
        return None
    val = series[mask].iloc[-1]
    if isinstance(val, float) and np.isnan(val):
        return None
    return float(val)


def chip_feature_providers(
    *,
    chips_by_stock: Mapping[str, pd.DataFrame],
    margin_by_stock: Mapping[str, pd.DataFrame],
    rolling_window: int = 5,
    streak_lookback: int = 5,
    margin_change_days: int = 5,
) -> list[FeatureProvider]:
    # Pre-compute per-stock derived series.
    chip_cache: dict[str, pd.DataFrame] = {}
    for sid, df in chips_by_stock.items():
        if df.empty:
            chip_cache[sid] = df.copy()
            continue
        base = df.sort_index().copy()
        if "foreign_net" in base.columns:
            base["foreign_net_streak"] = foreign_net_streak(base["foreign_net"])
            base["foreign_net_5d"] = rolling_net_buy(
                base["foreign_net"], window=rolling_window
            )
        chip_cache[sid] = base

    margin_cache: dict[str, pd.DataFrame] = {}
    for sid, df in margin_by_stock.items():
        if df.empty:
            margin_cache[sid] = df.copy()
            continue
        base = df.sort_index().copy()
        if "margin_balance" in base.columns:
            base["margin_balance_5d_change"] = margin_n_day_change(
                base["margin_balance"], n=margin_change_days
            )
        margin_cache[sid] = base

    def _make_provider(name: str, source: Mapping[str, pd.DataFrame]) -> FeatureProvider:
        def compute(stock_id: str, ref_date: date, ohlc: pd.DataFrame) -> FeatureValue | None:
            df = source.get(stock_id)
            ref_ts = pd.Timestamp(ref_date)
            available_at = datetime.combine(ref_date, PRE_OPEN_TIME)
            if df is None or df.empty or name not in df.columns:
                return FeatureValue(value=float("nan"), available_at=available_at)
            value = _prior_value(df[name], ref_ts)
            if value is None:
                return FeatureValue(value=float("nan"), available_at=available_at)
            return FeatureValue(value=value, available_at=available_at)

        return FeatureProvider(name=name, schema_version="v1", compute=compute)

    providers: list[FeatureProvider] = []
    chip_columns = ("foreign_net", "trust_net", "dealer_net", "all_net",
                    "foreign_net_streak", "foreign_net_5d")
    for col in chip_columns:
        providers.append(_make_provider(col, chip_cache))

    margin_columns = ("margin_balance", "short_balance", "margin_balance_5d_change")
    for col in margin_columns:
        providers.append(_make_provider(col, margin_cache))

    return providers
