"""TASK-F05 — Daily volume features (V2 §0.3).

Day-level wrapper around the spike concept in
``src/processor/volume_spike_detector.py``. The minute-level detector is kept
intact for the live UI; here we compute baseline / ratio / severity at the
(date, stock_id) granularity for the Feature Store.

Look-ahead safety: baseline at row T uses only volumes strictly before T
(implemented via ``shift(1)``).
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Tuple

import numpy as np
import pandas as pd

from src.config import (
    SPIKE_THRESHOLD_EXTREME,
    SPIKE_THRESHOLD_HIGH,
    SPIKE_THRESHOLD_LOW,
    SPIKE_THRESHOLD_MID,
)
from src.features.store import FeatureProvider, FeatureValue
from src.models import SpikeSeverity

__all__ = [
    "classify_volume_severity",
    "daily_volume_baseline",
    "daily_volume_ratio",
    "volume_feature_providers",
]


SIGNAL_CLOSE_TIME = time(13, 30)


def daily_volume_baseline(
    volume: pd.Series,
    *,
    window: int = 20,
    min_periods: int = 10,
) -> Tuple[pd.Series, pd.Series]:
    """Return (baseline, low_confidence) Series aligned to ``volume``.

    Baseline is the rolling mean of the *prior* ``window`` days (volume is
    shifted by one before averaging). ``low_confidence`` is True whenever the
    rolling window has fewer than ``window`` prior observations available.
    """
    if window <= 0 or min_periods <= 0:
        raise ValueError("window and min_periods must be positive")
    prior = volume.astype(float).shift(1)
    baseline = prior.rolling(window=window, min_periods=min_periods).mean()
    available = prior.rolling(window=window, min_periods=1).count()
    low_confidence = (available < window) | baseline.isna()
    return baseline, low_confidence


def daily_volume_ratio(
    volume: pd.Series,
    *,
    window: int = 20,
    min_periods: int = 10,
) -> pd.Series:
    baseline, _ = daily_volume_baseline(
        volume, window=window, min_periods=min_periods
    )
    return volume.astype(float) / baseline


def classify_volume_severity(
    ratio: float,
    *,
    volume: float = float("inf"),
    min_abs_volume: float = 0,
) -> SpikeSeverity:
    if ratio is None or (isinstance(ratio, float) and np.isnan(ratio)):
        return SpikeSeverity.NORMAL
    if volume < min_abs_volume:
        return SpikeSeverity.NORMAL
    if ratio >= SPIKE_THRESHOLD_EXTREME:
        return SpikeSeverity.EXTREME
    if ratio >= SPIKE_THRESHOLD_HIGH:
        return SpikeSeverity.HIGH
    if ratio >= SPIKE_THRESHOLD_MID:
        return SpikeSeverity.MID
    if ratio >= SPIKE_THRESHOLD_LOW:
        return SpikeSeverity.LOW
    return SpikeSeverity.NORMAL


def volume_feature_providers(
    *,
    window: int = 20,
    min_periods: int = 10,
    min_abs_volume: float = 0,
) -> list[FeatureProvider]:
    def _cache(ohlc: pd.DataFrame) -> pd.DataFrame:
        if "_volume_features_cache" in ohlc.attrs:
            return ohlc.attrs["_volume_features_cache"]
        baseline, low_conf = daily_volume_baseline(
            ohlc["volume"], window=window, min_periods=min_periods
        )
        ratio = ohlc["volume"].astype(float) / baseline
        severity = [
            classify_volume_severity(
                r,
                volume=v,
                min_abs_volume=min_abs_volume,
            ).value
            for r, v in zip(ratio, ohlc["volume"].astype(float))
        ]
        cache = pd.DataFrame(
            {
                "volume_ratio": ratio,
                "spike_severity": severity,
                "baseline_low_confidence": low_conf,
            },
            index=ohlc.index,
        )
        ohlc.attrs["_volume_features_cache"] = cache
        return cache

    def _provider(name: str, schema_version: str):
        def compute(stock_id: str, ref_date: date, ohlc: pd.DataFrame) -> FeatureValue | None:
            cache = _cache(ohlc)
            ts = pd.Timestamp(ref_date)
            if ts not in cache.index:
                return None
            value = cache.at[ts, name]
            return FeatureValue(
                value=value,
                available_at=datetime.combine(ref_date, SIGNAL_CLOSE_TIME),
            )

        return FeatureProvider(name=name, schema_version=schema_version, compute=compute)

    return [
        _provider("volume_ratio", "v1"),
        _provider("spike_severity", "v1"),
        _provider("baseline_low_confidence", "v1"),
    ]
