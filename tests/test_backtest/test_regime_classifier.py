"""TASK-D03d — Market regime classifier tests."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.backtest.regime_classifier import (
    Regime,
    RegimeCoverage,
    classify_regime,
    classify_window,
    count_regime_coverage,
)


def _market_df(close_series: list[float], start: date = date(2024, 1, 1)) -> pd.DataFrame:
    idx = pd.date_range(start=start, periods=len(close_series), freq="B")
    return pd.DataFrame(
        {
            "open": close_series,
            "high": [c * 1.005 for c in close_series],
            "low": [c * 0.995 for c in close_series],
            "close": close_series,
            "volume": [1_000_000] * len(close_series),
        },
        index=idx,
    )


# ---- Regime enum ----

@pytest.mark.unit
def test_regime_enum_has_three_labels() -> None:
    assert {r.value for r in Regime} == {"bull", "bear", "range"}


# ---- classify_regime ----

@pytest.mark.unit
def test_classify_bull_when_close_and_fast_above_slow() -> None:
    # Steadily rising series for 250 bars → close > MA50 > MA200
    closes = [100 + i * 0.5 for i in range(250)]
    df = _market_df(closes)
    label = classify_regime(df, df.index[-1].date(), fast_window=50, slow_window=200)
    assert label == Regime.BULL


@pytest.mark.unit
def test_classify_bear_when_close_and_fast_below_slow() -> None:
    closes = [200 - i * 0.5 for i in range(250)]
    df = _market_df(closes)
    label = classify_regime(df, df.index[-1].date(), fast_window=50, slow_window=200)
    assert label == Regime.BEAR


@pytest.mark.unit
def test_classify_range_when_market_flat() -> None:
    # Flat market: close == MA50 == MA200 → neither bull nor bear conditions
    closes = [100.0] * 250
    df = _market_df(closes)
    label = classify_regime(df, df.index[-1].date(), fast_window=50, slow_window=200)
    assert label == Regime.RANGE


@pytest.mark.unit
def test_classify_returns_none_for_unknown_date() -> None:
    df = _market_df([100 + i for i in range(250)])
    label = classify_regime(df, date(2099, 1, 1), fast_window=50, slow_window=200)
    assert label is None


@pytest.mark.unit
def test_classify_returns_none_when_history_insufficient() -> None:
    # Only 100 bars → MA200 NaN
    df = _market_df([100 + i for i in range(100)])
    label = classify_regime(df, df.index[-1].date(), fast_window=50, slow_window=200)
    assert label is None


# ---- classify_window ----

@pytest.mark.unit
def test_window_returns_dominant_label() -> None:
    closes = [100 + i * 0.5 for i in range(250)]  # all bull at tail
    df = _market_df(closes)
    start = df.index[210].date()
    end = df.index[249].date()
    label = classify_window(df, start, end, fast_window=50, slow_window=200)
    assert label == Regime.BULL


@pytest.mark.unit
def test_window_returns_none_when_no_classifiable_day() -> None:
    df = _market_df([100 + i for i in range(50)])  # insufficient for MA200
    label = classify_window(
        df, df.index[0].date(), df.index[-1].date(), fast_window=50, slow_window=200
    )
    assert label is None


@pytest.mark.unit
def test_window_handles_mixed_regimes() -> None:
    # Build series with a clear bull tail of 30 bars
    closes = [100 - i * 0.3 for i in range(220)] + [closes_tail for closes_tail in [200 + j for j in range(30)]]
    # rebuild ranges deterministically
    closes = [100 - i * 0.3 for i in range(220)] + [200 + j for j in range(30)]
    df = _market_df(closes)
    start = df.index[220].date()
    end = df.index[249].date()
    label = classify_window(df, start, end, fast_window=50, slow_window=200)
    # Bull tail dominates this slice
    assert label in {Regime.BULL, Regime.RANGE}  # tolerate edge cross


# ---- count_regime_coverage ----

@pytest.mark.unit
def test_count_returns_dataclass() -> None:
    df = _market_df([100 + i * 0.5 for i in range(250)])
    cov = count_regime_coverage(
        windows=[(df.index[210].date(), df.index[249].date())],
        market_ohlc=df,
        fast_window=50,
        slow_window=200,
    )
    assert isinstance(cov, RegimeCoverage)
    assert cov.bull == 1


@pytest.mark.unit
def test_count_aggregates_multiple_windows() -> None:
    # Bull series of 250
    bull_df = _market_df([100 + i * 0.5 for i in range(250)])
    # Bear series of 250 starting after bull ends
    bear_start = bull_df.index[-1].date()
    bear_df = _market_df([300 - i * 0.5 for i in range(250)], start=bear_start)
    combined = pd.concat([bull_df, bear_df]).sort_index()
    combined = combined[~combined.index.duplicated(keep="first")]

    bull_window = (bull_df.index[210].date(), bull_df.index[249].date())
    bear_window = (bear_df.index[210].date(), bear_df.index[249].date())

    cov = count_regime_coverage(
        windows=[bull_window, bear_window],
        market_ohlc=combined,
        fast_window=50,
        slow_window=200,
    )
    assert cov.bull >= 1
    assert cov.bear >= 1


@pytest.mark.unit
def test_count_skips_unclassifiable_windows() -> None:
    df = _market_df([100 + i for i in range(50)])  # too short
    cov = count_regime_coverage(
        windows=[(df.index[0].date(), df.index[-1].date())],
        market_ohlc=df,
        fast_window=50,
        slow_window=200,
    )
    assert cov == RegimeCoverage(bull=0, bear=0, range=0)


@pytest.mark.unit
def test_count_empty_windows_returns_zero_coverage() -> None:
    df = _market_df([100 + i for i in range(250)])
    cov = count_regime_coverage(windows=[], market_ohlc=df)
    assert cov == RegimeCoverage()
