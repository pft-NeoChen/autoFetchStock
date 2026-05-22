"""TASK-F04 — Price features (V2 §0.3)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.features.price_features import (
    atr,
    daily_return,
    moving_average,
    price_feature_providers,
    rolling_volatility,
)
from src.features.store import FeatureStore


def _ohlc(prices: list[float], highs: list[float] | None = None, lows: list[float] | None = None) -> pd.DataFrame:
    idx = pd.date_range("2025-01-02", periods=len(prices), freq="B")
    return pd.DataFrame(
        {
            "open": prices,
            "high": highs if highs is not None else [p + 1 for p in prices],
            "low": lows if lows is not None else [p - 1 for p in prices],
            "close": prices,
            "volume": [1_000_000] * len(prices),
        },
        index=idx,
    )


# ---- moving_average ----

@pytest.mark.unit
def test_moving_average_known_values() -> None:
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    ma3 = moving_average(s, window=3)
    assert ma3.iloc[2] == pytest.approx(2.0)
    assert ma3.iloc[4] == pytest.approx(4.0)


@pytest.mark.unit
def test_moving_average_requires_full_window() -> None:
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    ma3 = moving_average(s, window=3)
    assert ma3.iloc[:2].isna().all()


@pytest.mark.unit
def test_moving_average_invalid_window_raises() -> None:
    with pytest.raises(ValueError):
        moving_average(pd.Series([1.0]), window=0)


# ---- daily_return ----

@pytest.mark.unit
def test_daily_return_known_values() -> None:
    s = pd.Series([100.0, 110.0, 99.0], dtype=float)
    r = daily_return(s)
    assert pd.isna(r.iloc[0])
    assert r.iloc[1] == pytest.approx(0.10)
    assert r.iloc[2] == pytest.approx(-0.10)


# ---- atr ----

@pytest.mark.unit
def test_atr_known_values() -> None:
    df = pd.DataFrame(
        {
            "high":  [11.0, 12.0, 13.0, 14.0],
            "low":   [10.0, 11.0, 12.0, 13.0],
            "close": [10.5, 11.5, 12.5, 13.5],
        }
    )
    atr3 = atr(df, window=3)
    # TR = [1.0, 1.5, 1.5, 1.5]; ATR3 at idx 2 = mean(1.0, 1.5, 1.5) = 1.333...
    assert atr3.iloc[2] == pytest.approx((1.0 + 1.5 + 1.5) / 3)
    assert atr3.iloc[3] == pytest.approx((1.5 + 1.5 + 1.5) / 3)


@pytest.mark.unit
def test_atr_requires_window() -> None:
    df = pd.DataFrame(
        {"high": [11.0, 12.0], "low": [10.0, 11.0], "close": [10.5, 11.5]}
    )
    assert atr(df, window=14).isna().all()


# ---- rolling_volatility ----

@pytest.mark.unit
def test_rolling_volatility_matches_std_of_returns() -> None:
    closes = pd.Series([100.0, 102.0, 101.0, 103.0, 104.0, 106.0], dtype=float)
    vol = rolling_volatility(closes, window=3)
    expected = closes.pct_change().rolling(window=3).std()
    pd.testing.assert_series_equal(vol.dropna(), expected.dropna(), check_names=False)


# ---- integration with FeatureStore ----

@pytest.mark.unit
def test_providers_integrate_with_feature_store(tmp_path: Path) -> None:
    closes = list(np.linspace(100, 130, 30))
    raw = {"2330": _ohlc(closes)}
    providers = price_feature_providers(ma_windows=(5, 10), atr_window=14, vol_window=20)
    store = FeatureStore(
        providers=providers,
        raw_daily=raw,
        universe_version="u",
        corp_action_version="c",
        git_commit="g",
        cache_dir=tmp_path,
    )

    df = store.build(["2330"], date(2025, 1, 2), date(2025, 2, 28))

    for col in ("ma_5", "ma_10", "daily_return", "atr_14", "vol_20"):
        assert col in df.columns
    series = df.xs("2330", level="stock_id")["ma_5"]
    assert not series.iloc[-1] != series.iloc[-1]  # not NaN at end
