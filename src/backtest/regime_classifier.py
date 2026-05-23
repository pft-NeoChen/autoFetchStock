"""TASK-D03d — Market regime classifier (V2 §6.1 caveat #3).

Labels each trading day as BULL / BEAR / RANGE based on the market index's
position relative to long-term and intermediate moving averages. Window-
and walk-forward-level helpers aggregate day labels for the V2 §6.1
``regime_coverage`` decision check.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Iterable, Optional

import pandas as pd


__all__ = [
    "Regime",
    "RegimeCoverage",
    "classify_regime",
    "classify_window",
    "count_regime_coverage",
]

DEFAULT_FAST_WINDOW = 50
DEFAULT_SLOW_WINDOW = 200


class Regime(str, Enum):
    BULL = "bull"
    BEAR = "bear"
    RANGE = "range"


@dataclass(frozen=True)
class RegimeCoverage:
    bull: int = 0
    bear: int = 0
    range: int = 0


# ── Day-level ───────────────────────────────────────────────────────────────


def _compute_mas(
    market_ohlc: pd.DataFrame, fast_window: int, slow_window: int
) -> pd.DataFrame:
    """Cache fast/slow MAs onto a DataFrame indexed by the source's index."""
    close = market_ohlc["close"].astype(float).sort_index()
    return pd.DataFrame(
        {
            "close": close,
            "ma_fast": close.rolling(window=fast_window, min_periods=fast_window).mean(),
            "ma_slow": close.rolling(window=slow_window, min_periods=slow_window).mean(),
        }
    )


def _label_from_row(close: float, ma_fast: float, ma_slow: float) -> Optional[Regime]:
    if pd.isna(close) or pd.isna(ma_fast) or pd.isna(ma_slow):
        return None
    if close > ma_slow and ma_fast > ma_slow:
        return Regime.BULL
    if close < ma_slow and ma_fast < ma_slow:
        return Regime.BEAR
    return Regime.RANGE


def classify_regime(
    market_ohlc: pd.DataFrame,
    ref_date: date,
    *,
    fast_window: int = DEFAULT_FAST_WINDOW,
    slow_window: int = DEFAULT_SLOW_WINDOW,
) -> Optional[Regime]:
    """Label ``ref_date`` as BULL / BEAR / RANGE."""
    ma_df = _compute_mas(market_ohlc, fast_window, slow_window)
    ts = pd.Timestamp(ref_date)
    if ts not in ma_df.index:
        return None
    row = ma_df.loc[ts]
    return _label_from_row(row["close"], row["ma_fast"], row["ma_slow"])


# ── Window-level ────────────────────────────────────────────────────────────


def classify_window(
    market_ohlc: pd.DataFrame,
    start: date,
    end: date,
    *,
    fast_window: int = DEFAULT_FAST_WINDOW,
    slow_window: int = DEFAULT_SLOW_WINDOW,
) -> Optional[Regime]:
    """Aggregate day labels in [start, end] → most-common label."""
    ma_df = _compute_mas(market_ohlc, fast_window, slow_window)
    window_slice = ma_df.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    counter: Counter[Regime] = Counter()
    for _, row in window_slice.iterrows():
        label = _label_from_row(row["close"], row["ma_fast"], row["ma_slow"])
        if label is not None:
            counter[label] += 1
    if not counter:
        return None
    return counter.most_common(1)[0][0]


def count_regime_coverage(
    windows: Iterable[tuple[date, date]],
    market_ohlc: pd.DataFrame,
    *,
    fast_window: int = DEFAULT_FAST_WINDOW,
    slow_window: int = DEFAULT_SLOW_WINDOW,
) -> RegimeCoverage:
    """Count how many input windows fall into each regime label."""
    buckets: Counter[Regime] = Counter()
    for start, end in windows:
        label = classify_window(
            market_ohlc, start, end, fast_window=fast_window, slow_window=slow_window
        )
        if label is not None:
            buckets[label] += 1
    return RegimeCoverage(
        bull=buckets.get(Regime.BULL, 0),
        bear=buckets.get(Regime.BEAR, 0),
        range=buckets.get(Regime.RANGE, 0),
    )
