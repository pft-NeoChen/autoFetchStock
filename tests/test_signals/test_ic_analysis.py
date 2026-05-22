"""TASK-S01 — IC / decay / monotonicity analysis (V2 §1)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.signals.ic_analysis import (
    IC_THRESHOLDS,
    compute_ic,
    decay_curve,
    meets_ic_threshold,
    monotonicity_test,
)


def _multi_index(dates: int = 30, stocks: int = 10) -> pd.MultiIndex:
    d = pd.date_range("2025-01-02", periods=dates, freq="B")
    sids = [f"S{i:02d}" for i in range(stocks)]
    return pd.MultiIndex.from_product([d, sids], names=["date", "stock_id"])


# ---- compute_ic ----

@pytest.mark.unit
def test_ic_returns_required_fields() -> None:
    idx = _multi_index()
    rng = np.random.default_rng(0)
    feat = pd.Series(rng.normal(size=len(idx)), index=idx, name="x")
    ret = pd.Series(rng.normal(size=len(idx)), index=idx, name="r")

    res = compute_ic(feat, ret)
    assert set(res.keys()) >= {"ic_mean", "ic_std", "ic_ir", "p_value", "n_periods"}


@pytest.mark.unit
def test_ic_random_close_to_zero() -> None:
    idx = _multi_index(dates=60, stocks=20)
    rng = np.random.default_rng(42)
    feat = pd.Series(rng.normal(size=len(idx)), index=idx)
    ret = pd.Series(rng.normal(size=len(idx)), index=idx)

    res = compute_ic(feat, ret)
    assert abs(res["ic_mean"]) < 0.05
    assert res["p_value"] > 0.05


@pytest.mark.unit
def test_ic_perfect_correlation_is_one() -> None:
    idx = _multi_index(dates=20, stocks=10)
    rng = np.random.default_rng(0)
    feat = pd.Series(rng.normal(size=len(idx)), index=idx)
    ret = feat.copy()

    res = compute_ic(feat, ret)
    assert res["ic_mean"] == pytest.approx(1.0)
    assert res["ic_ir"] > 100  # std should be ~0, ir huge


@pytest.mark.unit
def test_ic_handles_nan_rows() -> None:
    idx = _multi_index(dates=20, stocks=10)
    rng = np.random.default_rng(1)
    feat = pd.Series(rng.normal(size=len(idx)), index=idx)
    ret = pd.Series(rng.normal(size=len(idx)), index=idx)
    feat.iloc[:50] = np.nan

    res = compute_ic(feat, ret)
    assert not np.isnan(res["ic_mean"])
    assert res["n_periods"] > 0


@pytest.mark.unit
def test_ic_negative_correlation() -> None:
    idx = _multi_index(dates=20, stocks=10)
    rng = np.random.default_rng(3)
    feat = pd.Series(rng.normal(size=len(idx)), index=idx)
    ret = -feat

    res = compute_ic(feat, ret)
    assert res["ic_mean"] == pytest.approx(-1.0)


# ---- decay_curve ----

@pytest.mark.unit
def test_decay_curve_returns_per_horizon() -> None:
    idx = _multi_index(dates=40, stocks=10)
    rng = np.random.default_rng(0)
    feat = pd.Series(rng.normal(size=len(idx)), index=idx)
    returns_by_h = {h: pd.Series(rng.normal(size=len(idx)), index=idx) for h in (1, 5, 20)}

    res = decay_curve(feat, returns_by_h)
    assert set(res.keys()) == {1, 5, 20}
    for h, m in res.items():
        assert "ic_mean" in m


@pytest.mark.unit
def test_decay_curve_decreasing_for_decaying_signal() -> None:
    idx = _multi_index(dates=20, stocks=10)
    rng = np.random.default_rng(0)
    feat = pd.Series(rng.normal(size=len(idx)), index=idx)
    returns_by_h = {
        1: feat * 1.0,
        5: feat * 0.5,
        20: feat * 0.1,
    }
    res = decay_curve(feat, returns_by_h)
    assert res[1]["ic_mean"] >= res[5]["ic_mean"] >= res[20]["ic_mean"] - 0.01


# ---- monotonicity_test ----

@pytest.mark.unit
def test_monotonicity_groups_returns_n_means() -> None:
    idx = _multi_index(dates=20, stocks=15)
    rng = np.random.default_rng(0)
    feat = pd.Series(rng.normal(size=len(idx)), index=idx)
    ret = pd.Series(rng.normal(size=len(idx)), index=idx)

    groups = monotonicity_test(feat, ret, n_groups=5)
    assert len(groups) == 5


@pytest.mark.unit
def test_monotonicity_strong_positive_signal_is_increasing() -> None:
    idx = _multi_index(dates=20, stocks=20)
    rng = np.random.default_rng(0)
    feat = pd.Series(rng.normal(size=len(idx)), index=idx)
    ret = feat * 2.0  # strict positive monotonic

    groups = monotonicity_test(feat, ret, n_groups=5)
    # Lowest quintile mean < highest quintile mean
    assert groups[0] < groups[-1]


# ---- threshold helper ----

@pytest.mark.parametrize(
    "horizon,ic,expected",
    [
        (1, 0.025, True),
        (1, 0.015, False),
        (5, 0.04, True),
        (5, 0.025, False),
        (20, 0.05, True),
        (20, 0.03, False),
    ],
)
@pytest.mark.unit
def test_meets_ic_threshold(horizon: int, ic: float, expected: bool) -> None:
    assert meets_ic_threshold(ic, horizon_days=horizon) is expected


@pytest.mark.unit
def test_ic_thresholds_match_v2_spec() -> None:
    assert IC_THRESHOLDS == {1: 0.02, 5: 0.03, 20: 0.04}
