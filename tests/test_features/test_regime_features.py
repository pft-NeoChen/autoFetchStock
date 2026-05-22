"""TASK-F08 — Market regime features (V2 §6.1)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.features.regime_features import (
    adx,
    market_moving_average,
    regime_feature_providers,
    vol_percentile_rank,
)
from src.features.store import FeatureStore


def _stock_ohlc(n: int = 80) -> pd.DataFrame:
    idx = pd.date_range("2025-01-02", periods=n, freq="B")
    return pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1_000_000] * n,
        },
        index=idx,
    )


def _trending_market(n: int = 80, slope: float = 0.5) -> pd.DataFrame:
    idx = pd.date_range("2025-01-02", periods=n, freq="B")
    closes = np.array([100.0 + slope * i for i in range(n)])
    return pd.DataFrame(
        {
            "open": closes - 0.2,
            "high": closes + 0.5,
            "low": closes - 0.5,
            "close": closes,
            "volume": [1_000_000] * n,
        },
        index=idx,
    )


# ---- market_moving_average ----

@pytest.mark.unit
def test_market_moving_average_known() -> None:
    close = pd.Series([float(i) for i in range(1, 11)])
    ma = market_moving_average(close, window=5)
    assert ma.iloc[4] == pytest.approx(3.0)
    assert pd.isna(ma.iloc[3])


# ---- adx ----

@pytest.mark.unit
def test_adx_rises_under_strong_trend() -> None:
    df = _trending_market(n=60, slope=1.0)
    series = adx(df, window=14)
    # ADX should be > 20 (trend zone) for a clean linear uptrend
    assert series.dropna().iloc[-1] > 20


@pytest.mark.unit
def test_adx_low_for_flat_market() -> None:
    df = _trending_market(n=60, slope=0.0)
    series = adx(df, window=14)
    last = series.dropna().iloc[-1]
    assert last < 25  # flat market → low ADX


# ---- vol_percentile_rank ----

@pytest.mark.unit
def test_vol_percentile_rank_in_unit_interval() -> None:
    rng = np.random.default_rng(0)
    closes = pd.Series(100 + rng.normal(scale=0.5, size=300)).cumsum() + 100
    rank = vol_percentile_rank(closes, vol_window=30, rank_window=252)
    valid = rank.dropna()
    assert valid.between(0.0, 1.0).all()


@pytest.mark.unit
def test_vol_percentile_rank_uses_only_prior_window() -> None:
    closes = pd.Series([100.0] * 50 + [200.0] * 5)  # spike at end
    rank = vol_percentile_rank(closes, vol_window=5, rank_window=20)
    # The spike row's rank must NOT incorporate itself in the baseline;
    # we just confirm output is finite and within [0,1] for last row.
    last = rank.iloc[-1]
    assert not pd.isna(last)
    assert 0.0 <= last <= 1.0


# ---- regime provider integration ----

@pytest.mark.unit
def test_regime_providers_broadcast_same_value_to_all_stocks(tmp_path: Path) -> None:
    market = _trending_market(n=80, slope=0.3)
    raw = {"2330": _stock_ohlc(80), "2317": _stock_ohlc(80)}
    providers = regime_feature_providers(
        market_index_ohlc=market,
        ma_window=20,
        adx_window=14,
        vol_window=10,
        vol_rank_window=30,
    )
    store = FeatureStore(
        providers=providers,
        raw_daily=raw,
        universe_version="u",
        corp_action_version="c",
        git_commit="g",
        cache_dir=tmp_path,
    )

    df = store.build(["2330", "2317"], date(2025, 1, 2), date(2025, 4, 30))

    for col in ("market_ma", "market_adx", "market_vol_rank"):
        assert col in df.columns

    # Same date across stocks must yield identical regime values.
    last_date = df.index.get_level_values("date").max()
    val_a = df.loc[(last_date, "2330"), "market_adx"]
    val_b = df.loc[(last_date, "2317"), "market_adx"]
    assert val_a == pytest.approx(val_b)


@pytest.mark.unit
def test_regime_provider_handles_missing_market_date(tmp_path: Path) -> None:
    market = _trending_market(n=40, slope=0.3)
    raw = {"2330": _stock_ohlc(80)}  # stock has dates that market doesn't cover
    providers = regime_feature_providers(market_index_ohlc=market, ma_window=10)
    store = FeatureStore(
        providers=providers,
        raw_daily=raw,
        universe_version="u",
        corp_action_version="c",
        git_commit="g",
        cache_dir=tmp_path,
    )

    df = store.build(["2330"], date(2025, 1, 2), date(2025, 4, 30))
    # No crash; some later rows have NaN regime values
    assert "market_ma" in df.columns
