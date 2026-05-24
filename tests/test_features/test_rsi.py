"""TASK-S1-E2 — RSI(14) feature helper."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features.rsi import rsi


pytestmark = pytest.mark.unit


def test_rsi_flat_series_is_nan_due_to_zero_gain_and_loss() -> None:
    series = pd.Series([100.0] * 30)

    result = rsi(series, window=14)

    assert pd.isna(result.iloc[-1])


def test_rsi_monotonic_increase_returns_100() -> None:
    series = pd.Series(np.arange(1.0, 31.0))

    result = rsi(series, window=14)

    assert result.iloc[-1] == pytest.approx(100.0, abs=1e-6)


def test_rsi_monotonic_decrease_returns_0() -> None:
    series = pd.Series(np.arange(30.0, 0.0, -1.0))

    result = rsi(series, window=14)

    assert result.iloc[-1] == pytest.approx(0.0, abs=1e-6)


def test_rsi_is_nan_until_window_plus_one_diffs_available() -> None:
    series = pd.Series(np.arange(1.0, 20.0))

    result = rsi(series, window=14)

    # diff() drops first observation, then rolling(window) needs `window` values.
    assert pd.isna(result.iloc[:14]).all()
    assert not pd.isna(result.iloc[14])
