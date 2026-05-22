"""TASK-F04 — Price features (V2 §0.3).

Provides pure window functions (MA / daily return / ATR / rolling vol) plus a
factory that wraps them as ``FeatureProvider`` instances for ``FeatureStore``.
Providers operate on backward-adjusted OHLC (the store overwrites ``close``
etc. with the adjusted series before invocation).
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Sequence

import numpy as np
import pandas as pd

from src.features.store import FeatureProvider, FeatureValue

__all__ = [
    "atr",
    "daily_return",
    "moving_average",
    "price_feature_providers",
    "rolling_volatility",
]


SIGNAL_CLOSE_TIME = time(13, 30)


def moving_average(close: pd.Series, *, window: int) -> pd.Series:
    if window <= 0:
        raise ValueError("window must be positive")
    return close.astype(float).rolling(window=window, min_periods=window).mean()


def daily_return(close: pd.Series) -> pd.Series:
    return close.astype(float).pct_change()


def atr(ohlc: pd.DataFrame, *, window: int = 14) -> pd.Series:
    if window <= 0:
        raise ValueError("window must be positive")
    high = ohlc["high"].astype(float)
    low = ohlc["low"].astype(float)
    close = ohlc["close"].astype(float)
    prev_close = close.shift(1)

    tr = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    # First TR has no previous close — fall back to high - low so window stays usable.
    tr.iloc[0] = high.iloc[0] - low.iloc[0]
    return tr.rolling(window=window, min_periods=window).mean()


def rolling_volatility(close: pd.Series, *, window: int = 20) -> pd.Series:
    if window <= 0:
        raise ValueError("window must be positive")
    return close.astype(float).pct_change().rolling(window=window, min_periods=window).std()


def _series_provider(
    name: str,
    schema_version: str,
    series_fn,
) -> FeatureProvider:
    def compute(stock_id: str, ref_date: date, ohlc: pd.DataFrame) -> FeatureValue | None:
        series = series_fn(ohlc)
        ts = pd.Timestamp(ref_date)
        if ts not in series.index:
            return None
        value = series.loc[ts]
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return FeatureValue(
                value=float("nan"),
                available_at=datetime.combine(ref_date, SIGNAL_CLOSE_TIME),
            )
        return FeatureValue(
            value=float(value),
            available_at=datetime.combine(ref_date, SIGNAL_CLOSE_TIME),
        )

    return FeatureProvider(name=name, schema_version=schema_version, compute=compute)


def price_feature_providers(
    *,
    ma_windows: Sequence[int] = (5, 10, 20, 60),
    atr_window: int = 14,
    vol_window: int = 20,
) -> list[FeatureProvider]:
    providers: list[FeatureProvider] = []
    for w in ma_windows:
        providers.append(
            _series_provider(
                name=f"ma_{w}",
                schema_version="v1",
                series_fn=lambda df, w=w: moving_average(df["close"], window=w),
            )
        )
    providers.append(
        _series_provider(
            name="daily_return",
            schema_version="v1",
            series_fn=lambda df: daily_return(df["close"]),
        )
    )
    providers.append(
        _series_provider(
            name=f"atr_{atr_window}",
            schema_version="v1",
            series_fn=lambda df, w=atr_window: atr(df, window=w),
        )
    )
    providers.append(
        _series_provider(
            name=f"vol_{vol_window}",
            schema_version="v1",
            series_fn=lambda df, w=vol_window: rolling_volatility(df["close"], window=w),
        )
    )
    return providers
