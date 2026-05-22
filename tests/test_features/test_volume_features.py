"""TASK-F05 — Volume features (V2 §0.3)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.features.store import FeatureStore
from src.features.volume_features import (
    classify_volume_severity,
    daily_volume_baseline,
    daily_volume_ratio,
    volume_feature_providers,
)
from src.models import SpikeSeverity


@pytest.mark.unit
def test_baseline_uses_only_prior_days() -> None:
    vol = pd.Series([10.0, 10.0, 10.0, 10.0, 1000.0], dtype=float)
    baseline, _ = daily_volume_baseline(vol, window=3, min_periods=1)
    # Baseline at index 4 must be mean of indices 1..3 = 10.0,
    # never touch the 1000 at idx 4.
    assert baseline.iloc[4] == pytest.approx(10.0)


@pytest.mark.unit
def test_baseline_low_confidence_when_below_window() -> None:
    vol = pd.Series([5.0, 5.0, 5.0, 5.0], dtype=float)
    baseline, low_conf = daily_volume_baseline(vol, window=20, min_periods=1)
    # All rows have <20 prior obs → low_conf True (rows with baseline available)
    assert bool(low_conf.iloc[1]) is True
    assert bool(low_conf.iloc[3]) is True


@pytest.mark.unit
def test_baseline_full_window_not_low_confidence() -> None:
    vol = pd.Series([10.0] * 5 + [20.0], dtype=float)
    baseline, low_conf = daily_volume_baseline(vol, window=5, min_periods=5)
    # idx 5 has exactly 5 prior obs → not low_conf
    assert bool(low_conf.iloc[5]) is False
    assert baseline.iloc[5] == pytest.approx(10.0)


@pytest.mark.unit
def test_volume_ratio_known() -> None:
    vol = pd.Series([100.0, 100.0, 100.0, 100.0, 500.0], dtype=float)
    ratio = daily_volume_ratio(vol, window=3, min_periods=1)
    assert ratio.iloc[4] == pytest.approx(5.0)


@pytest.mark.parametrize(
    "ratio,expected",
    [
        (1.5, SpikeSeverity.NORMAL),
        (2.0, SpikeSeverity.LOW),
        (3.5, SpikeSeverity.MID),
        (6.0, SpikeSeverity.HIGH),
        (15.0, SpikeSeverity.EXTREME),
    ],
)
@pytest.mark.unit
def test_severity_classification(ratio: float, expected: SpikeSeverity) -> None:
    assert classify_volume_severity(ratio) is expected


@pytest.mark.unit
def test_severity_normal_when_volume_below_min_abs() -> None:
    sev = classify_volume_severity(15.0, volume=10, min_abs_volume=100)
    assert sev is SpikeSeverity.NORMAL


@pytest.mark.unit
def test_severity_normal_when_ratio_nan() -> None:
    assert classify_volume_severity(float("nan")) is SpikeSeverity.NORMAL


@pytest.mark.unit
def test_volume_providers_integrate_with_store(tmp_path: Path) -> None:
    n = 30
    idx = pd.date_range("2025-01-02", periods=n, freq="B")
    volumes = [1_000_000] * (n - 1) + [10_000_000]  # last day = 10x spike
    df = pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": volumes,
        },
        index=idx,
    )
    raw = {"2330": df}
    providers = volume_feature_providers(window=20, min_periods=10)
    store = FeatureStore(
        providers=providers,
        raw_daily=raw,
        universe_version="u",
        corp_action_version="c",
        git_commit="g",
        cache_dir=tmp_path,
    )

    out = store.build(["2330"], date(2025, 1, 2), date(2025, 3, 31))

    for col in ("volume_ratio", "spike_severity", "baseline_low_confidence"):
        assert col in out.columns

    series = out.xs("2330", level="stock_id")
    last_ratio = series["volume_ratio"].iloc[-1]
    assert last_ratio == pytest.approx(10.0)
    assert series["spike_severity"].iloc[-1] == SpikeSeverity.EXTREME.value
    assert bool(series["baseline_low_confidence"].iloc[-1]) is False
