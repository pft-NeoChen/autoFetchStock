"""TASK-F06 — Chip features (V2 §0.3, §0.5)."""

from __future__ import annotations

from datetime import date, time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.features.chip_features import (
    chip_feature_providers,
    foreign_net_streak,
    margin_n_day_change,
    rolling_net_buy,
)
from src.features.store import FeatureStore, LookAheadError


def _daily_ohlc(n: int = 30) -> pd.DataFrame:
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


def _chip_frame(values: list[float], start: str = "2025-01-02") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(values), freq="B")
    return pd.DataFrame(
        {
            "foreign_net": values,
            "trust_net": [0.0] * len(values),
            "dealer_net": [0.0] * len(values),
            "all_net": values,
        },
        index=idx,
    )


# ---- foreign_net_streak ----

@pytest.mark.unit
def test_foreign_net_streak_positive_run() -> None:
    s = pd.Series([1, 2, 3, 4], dtype=float)
    streak = foreign_net_streak(s)
    assert streak.iloc[-1] == 4
    assert streak.iloc[0] == 1


@pytest.mark.unit
def test_foreign_net_streak_breaks_on_negative() -> None:
    s = pd.Series([1, 1, 1, -1, 1], dtype=float)
    streak = foreign_net_streak(s)
    # +1+1+1 → streak 3, -1 → -1, +1 → 1
    assert list(streak.astype(int)) == [1, 2, 3, -1, 1]


@pytest.mark.unit
def test_foreign_net_streak_zero_resets() -> None:
    s = pd.Series([1, 1, 0, 1], dtype=float)
    streak = foreign_net_streak(s)
    assert int(streak.iloc[2]) == 0
    assert int(streak.iloc[3]) == 1


# ---- rolling_net_buy ----

@pytest.mark.unit
def test_rolling_net_buy_5d_cumulative() -> None:
    s = pd.Series([1, 2, 3, 4, 5, 6], dtype=float)
    r = rolling_net_buy(s, window=5)
    assert r.iloc[4] == pytest.approx(15)
    assert r.iloc[5] == pytest.approx(20)
    assert pd.isna(r.iloc[3])


# ---- margin_n_day_change ----

@pytest.mark.unit
def test_margin_5d_change() -> None:
    s = pd.Series([100, 110, 120, 130, 140, 150], dtype=float)
    d = margin_n_day_change(s, n=5)
    assert d.iloc[5] == pytest.approx(50.0)
    assert pd.isna(d.iloc[4])


# ---- provider integration ----

@pytest.mark.unit
def test_chip_provider_uses_prior_day_to_avoid_lookahead(tmp_path: Path) -> None:
    raw = {"2330": _daily_ohlc(10)}
    chips = {"2330": _chip_frame([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])}
    providers = chip_feature_providers(
        chips_by_stock=chips,
        margin_by_stock={},
        streak_lookback=5,
        rolling_window=5,
        margin_change_days=5,
    )
    store = FeatureStore(
        providers=providers,
        raw_daily=raw,
        universe_version="u",
        corp_action_version="c",
        git_commit="g",
        cache_dir=tmp_path,
    )

    # Must not raise LookAheadError because chip available_at = ref_date 08:30 < signal 13:30
    df = store.build(["2330"], date(2025, 1, 2), date(2025, 1, 15))

    # Provider for date T uses chips[T-1] (prior trading day).
    series = df.xs("2330", level="stock_id")
    # row at idx 1 (2025-01-03) should reflect chips from idx 0 (foreign_net=1)
    assert series["foreign_net"].iloc[1] == pytest.approx(1.0)


@pytest.mark.unit
def test_chip_provider_returns_nan_when_no_data(tmp_path: Path) -> None:
    raw = {"2330": _daily_ohlc(5)}
    providers = chip_feature_providers(
        chips_by_stock={},
        margin_by_stock={},
    )
    store = FeatureStore(
        providers=providers,
        raw_daily=raw,
        universe_version="u",
        corp_action_version="c",
        git_commit="g",
        cache_dir=tmp_path,
    )

    df = store.build(["2330"], date(2025, 1, 2), date(2025, 1, 10))
    series = df.xs("2330", level="stock_id")
    assert series["foreign_net"].isna().all()


@pytest.mark.unit
def test_chip_provider_columns_present(tmp_path: Path) -> None:
    raw = {"2330": _daily_ohlc(15)}
    chips = {"2330": _chip_frame([100.0] * 15)}
    margin = {
        "2330": pd.DataFrame(
            {"margin_balance": list(range(100, 115))},
            index=pd.date_range("2025-01-02", periods=15, freq="B"),
        )
    }
    providers = chip_feature_providers(
        chips_by_stock=chips,
        margin_by_stock=margin,
        rolling_window=5,
        streak_lookback=5,
        margin_change_days=5,
    )
    store = FeatureStore(
        providers=providers,
        raw_daily=raw,
        universe_version="u",
        corp_action_version="c",
        git_commit="g",
        cache_dir=tmp_path,
    )
    df = store.build(["2330"], date(2025, 1, 2), date(2025, 1, 31))
    for col in ("foreign_net", "foreign_net_streak", "foreign_net_5d", "margin_balance_5d_change"):
        assert col in df.columns
