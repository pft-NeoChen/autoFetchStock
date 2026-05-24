"""TASK-S1-E3 — sector-neutralization + momentum helpers."""

from __future__ import annotations

import pandas as pd
import pytest

from src.signals.sector_neutral import (
    compute_12_1m_return,
    compute_forward_return,
    cost_adjusted_decile_spread,
    decile_spread,
    infer_sector,
    sector_neutralize,
)


pytestmark = pytest.mark.unit


def test_infer_sector_groups_by_first_two_digits_of_stock_id() -> None:
    # 2330 / 2317 share "23" prefix; 2454 lives in "24"; 1101 / 1102 in "11"
    assert infer_sector("2330") == infer_sector("2317")
    assert infer_sector("1101") != infer_sector("2330")
    assert infer_sector("1102") == infer_sector("1101")
    assert infer_sector("2454") != infer_sector("2330")


def test_compute_12_1m_return_skips_month_1() -> None:
    dates = pd.date_range("2024-01-01", periods=260, freq="B")
    idx = pd.MultiIndex.from_product([dates, ["AAA"]], names=["date", "stock_id"])
    closes = pd.Series([float(i + 1) for i in range(260)], index=idx)

    result = compute_12_1m_return(closes, skip=21, lookback=252)

    expected = (260 - 21) / (260 - 252) - 1
    assert result.loc[(dates[-1], "AAA")] == pytest.approx(expected, rel=1e-9)


def test_compute_forward_return_uses_close_horizon_days_ahead() -> None:
    dates = pd.date_range("2024-01-01", periods=30, freq="B")
    idx = pd.MultiIndex.from_product([dates, ["AAA"]], names=["date", "stock_id"])
    closes = pd.Series([float(i + 100) for i in range(30)], index=idx)

    result = compute_forward_return(closes, horizon=5)

    expected = (105 / 100) - 1
    assert result.loc[(dates[0], "AAA")] == pytest.approx(expected, rel=1e-9)
    assert pd.isna(result.loc[(dates[-1], "AAA")])


def test_sector_neutralize_subtracts_per_date_per_sector_mean() -> None:
    idx = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2024-01-01"), "1101"),
            (pd.Timestamp("2024-01-01"), "1102"),
            (pd.Timestamp("2024-01-01"), "2330"),
            (pd.Timestamp("2024-01-01"), "2454"),
        ],
        names=["date", "stock_id"],
    )
    feat = pd.Series([1.0, 3.0, 5.0, 9.0], index=idx)
    sectors = pd.Series(["11", "11", "23", "23"], index=idx)

    result = sector_neutralize(feat, sectors)

    assert result.loc[(pd.Timestamp("2024-01-01"), "1101")] == pytest.approx(-1.0)
    assert result.loc[(pd.Timestamp("2024-01-01"), "1102")] == pytest.approx(1.0)
    assert result.loc[(pd.Timestamp("2024-01-01"), "2330")] == pytest.approx(-2.0)
    assert result.loc[(pd.Timestamp("2024-01-01"), "2454")] == pytest.approx(2.0)


def test_decile_spread_positive_for_monotonic_feature() -> None:
    idx = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2024-01-01"), f"S{i:02d}") for i in range(10)],
        names=["date", "stock_id"],
    )
    feat = pd.Series([float(i) for i in range(10)], index=idx)
    ret = pd.Series([float(i) * 0.01 for i in range(10)], index=idx)

    spread = decile_spread(feat, ret, n_buckets=10)

    # Top bucket = stock 9 → 0.09; bottom = stock 0 → 0.0 → spread = 0.09
    assert spread == pytest.approx(0.09, rel=1e-9)


def test_cost_adjusted_decile_spread_subtracts_monthly_cost() -> None:
    idx = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2024-01-01"), f"S{i:02d}") for i in range(10)],
        names=["date", "stock_id"],
    )
    feat = pd.Series([float(i) for i in range(10)], index=idx)
    ret = pd.Series([float(i) * 0.01 for i in range(10)], index=idx)

    raw = decile_spread(feat, ret, n_buckets=10)
    adjusted = cost_adjusted_decile_spread(
        feat, ret, n_buckets=10, monthly_cost=0.006
    )

    assert adjusted == pytest.approx(raw - 0.006, abs=1e-12)
