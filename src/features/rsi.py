"""TASK-S1-E2 — RSI(14) helper for C1-safe mean reversion research.

Simple Wilder-style RSI built on rolling SMA of gains and losses. Returns NaN
until ``window`` non-NaN diffs are available (i.e. the first ``window`` rows of
``rsi`` are NaN). All-flat series → NaN due to 0/0 ratio.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


__all__ = ["rsi"]


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Relative Strength Index over ``window`` periods."""
    delta = close.astype(float).diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.rolling(window=window, min_periods=window).mean()
    avg_loss = loss.rolling(window=window, min_periods=window).mean()
    rs = avg_gain.divide(avg_loss.replace(0.0, np.nan))
    out = 100.0 - 100.0 / (1.0 + rs)
    # When all gains and no losses → avg_loss = 0 → RSI = 100
    full_gain = (avg_loss == 0.0) & (avg_gain > 0.0)
    out = out.where(~full_gain, 100.0)
    # When all losses and no gains → avg_gain = 0 → RSI = 0
    full_loss = (avg_gain == 0.0) & (avg_loss > 0.0)
    out = out.where(~full_loss, 0.0)
    return out
