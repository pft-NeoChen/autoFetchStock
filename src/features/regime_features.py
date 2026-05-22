"""TASK-F08 — Market regime features (V2 §6.1).

Computes index-level regime indicators (MA, ADX, vol percentile rank) and
broadcasts the same value across all stocks for a given trading day.
"""

from __future__ import annotations

from datetime import date, datetime, time

import numpy as np
import pandas as pd

from src.features.store import FeatureProvider, FeatureValue

__all__ = [
    "adx",
    "market_moving_average",
    "regime_feature_providers",
    "vol_percentile_rank",
]


MARKET_CLOSE = time(13, 30)


def market_moving_average(close: pd.Series, *, window: int = 60) -> pd.Series:
    if window <= 0:
        raise ValueError("window must be positive")
    return close.astype(float).rolling(window=window, min_periods=window).mean()


def adx(ohlc: pd.DataFrame, *, window: int = 14) -> pd.Series:
    """Simplified ADX using rolling means (not Wilder smoothing)."""
    if window <= 0:
        raise ValueError("window must be positive")
    high = ohlc["high"].astype(float)
    low = ohlc["low"].astype(float)
    close = ohlc["close"].astype(float)
    prev_close = close.shift(1)

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move.clip(lower=0)
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move.clip(lower=0)

    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    tr.iloc[0] = high.iloc[0] - low.iloc[0]

    atr = tr.rolling(window=window, min_periods=window).mean()
    plus_di = 100 * plus_dm.rolling(window=window, min_periods=window).mean() / atr
    minus_di = 100 * minus_dm.rolling(window=window, min_periods=window).mean() / atr

    denom = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / denom
    # Flat market: both DI defined but sum is zero → no directional movement → DX = 0.
    no_movement = plus_di.notna() & minus_di.notna() & ((plus_di + minus_di) == 0)
    dx = dx.where(~no_movement, 0.0)
    return dx.rolling(window=window, min_periods=window).mean()


def vol_percentile_rank(
    close: pd.Series,
    *,
    vol_window: int = 30,
    rank_window: int = 252,
) -> pd.Series:
    """Percentile rank of current vol_window vol within prior rank_window history."""
    if vol_window <= 0 or rank_window <= 0:
        raise ValueError("window sizes must be positive")
    vol = close.astype(float).pct_change().rolling(window=vol_window, min_periods=vol_window).std()
    # Rank current vol against the prior rank_window observations (exclude self).
    def _rank(arr: np.ndarray) -> float:
        if len(arr) <= 1:
            return np.nan
        current = arr[-1]
        baseline = arr[:-1]
        baseline = baseline[~np.isnan(baseline)]
        if baseline.size == 0:
            return np.nan
        return float((baseline <= current).sum() / baseline.size)

    return vol.rolling(window=rank_window, min_periods=2).apply(_rank, raw=True)


def regime_feature_providers(
    *,
    market_index_ohlc: pd.DataFrame,
    ma_window: int = 60,
    adx_window: int = 14,
    vol_window: int = 30,
    vol_rank_window: int = 252,
) -> list[FeatureProvider]:
    market = market_index_ohlc.sort_index().copy()
    cached = pd.DataFrame(index=market.index)
    cached["market_ma"] = market_moving_average(market["close"], window=ma_window)
    cached["market_adx"] = adx(market, window=adx_window)
    cached["market_vol_rank"] = vol_percentile_rank(
        market["close"], vol_window=vol_window, rank_window=vol_rank_window
    )

    def _make_provider(name: str) -> FeatureProvider:
        def compute(stock_id: str, ref_date: date, ohlc: pd.DataFrame) -> FeatureValue | None:
            available_at = datetime.combine(ref_date, MARKET_CLOSE)
            ts = pd.Timestamp(ref_date)
            if ts not in cached.index:
                return FeatureValue(value=float("nan"), available_at=available_at)
            value = cached.at[ts, name]
            return FeatureValue(value=float(value) if not pd.isna(value) else float("nan"),
                                available_at=available_at)

        return FeatureProvider(name=name, schema_version="v1", compute=compute)

    return [_make_provider(c) for c in ("market_ma", "market_adx", "market_vol_rank")]
