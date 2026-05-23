"""V1 verdict-fix — combined equity padding + window chaining (V2 §3.4).

After the first V1 §6.1 run produced a spurious 97% max drawdown caused by
two bugs in equity aggregation:
  1. ``_combine_equity`` summed only stocks that actually traded → universe
     baseline ($N × initial_cash) was never present, so dates with fewer
     active stocks produced artificial dips.
  2. Cross-window combined equity was ``pd.concat(per_window_equity)`` —
     each new window resets to initial cash, creating a boundary jump.

These tests pin the corrected behaviour:
  * ``_pad_per_stock_equity`` — pad inactive stocks with a flat
    initial-cash baseline across the window date range.
  * ``_chain_window_equities_dollar`` — shift each successive window so
    it continues from the prior window's final value (dollar-scale, no
    jumps).
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.backtest.walk_orchestrator import (
    _chain_window_equities_dollar,
    _pad_per_stock_equity,
)


pytestmark = pytest.mark.unit


# ── _pad_per_stock_equity ───────────────────────────────────────────────────


def test_pad_includes_inactive_stocks_at_initial_cash():
    idx = pd.date_range("2025-06-02", periods=5, freq="B")
    active = pd.Series([1_000_000.0, 1_010_000, 1_020_000, 1_015_000, 1_025_000],
                       index=idx, name="equity")
    padded = _pad_per_stock_equity(
        per_stock={"A": active},
        universe=["A", "B"],
        date_index=idx,
        initial_cash=1_000_000.0,
    )
    # B inactive → flat $1M throughout
    assert (padded["B"] == 1_000_000.0).all()
    # A passthrough
    assert padded["A"].iloc[-1] == pytest.approx(1_025_000)


def test_pad_reindexes_partial_stock_curve_to_full_window():
    full_idx = pd.date_range("2025-06-02", periods=5, freq="B")
    short = pd.Series(
        [1_000_000.0, 1_050_000, 1_100_000],
        index=full_idx[:3],
    )
    padded = _pad_per_stock_equity(
        per_stock={"A": short},
        universe=["A"],
        date_index=full_idx,
        initial_cash=1_000_000.0,
    )
    # Beginning preserved
    assert padded["A"].iloc[0] == pytest.approx(1_000_000)
    # Tail carried forward from last known value (not reset to cash)
    assert padded["A"].iloc[-1] == pytest.approx(1_100_000)


def test_pad_empty_per_stock_returns_universe_baseline():
    idx = pd.date_range("2025-06-02", periods=3, freq="B")
    padded = _pad_per_stock_equity(
        per_stock={},
        universe=["A", "B"],
        date_index=idx,
        initial_cash=500_000.0,
    )
    assert (padded["A"] == 500_000.0).all()
    assert (padded["B"] == 500_000.0).all()


# ── _chain_window_equities_dollar ───────────────────────────────────────────


def test_chain_single_window_unchanged():
    idx = pd.date_range("2025-06-02", periods=3, freq="B")
    seg = pd.Series([100.0, 105.0, 110.0], index=idx)
    chained = _chain_window_equities_dollar([seg])
    pd.testing.assert_series_equal(chained, seg, check_names=False)


def test_chain_two_windows_no_boundary_jump():
    idx1 = pd.date_range("2025-06-02", periods=3, freq="B")
    idx2 = pd.date_range("2025-09-01", periods=3, freq="B")
    # Window 1: $1M → $1.1M (gain $100k)
    seg1 = pd.Series([1_000_000.0, 1_050_000, 1_100_000], index=idx1)
    # Window 2 starts fresh at $1M (engine reset) → ends $0.95M (loss $50k)
    seg2 = pd.Series([1_000_000.0, 980_000, 950_000], index=idx2)

    chained = _chain_window_equities_dollar([seg1, seg2])

    # Window 1 portion unchanged.
    assert chained.iloc[2] == pytest.approx(1_100_000)
    # Window 2 shifted so first value matches window 1 ending.
    assert chained.loc[idx2[0]] == pytest.approx(1_100_000)
    # Window 2 last value = previous_end + window_2_return (-50k) = 1.05M.
    assert chained.iloc[-1] == pytest.approx(1_050_000)


def test_chain_skips_empty_segments():
    idx = pd.date_range("2025-06-02", periods=3, freq="B")
    seg = pd.Series([100.0, 110.0, 120.0], index=idx)
    chained = _chain_window_equities_dollar(
        [seg, pd.Series(dtype=float), seg]
    )
    # Two non-empty windows concatenated with continuity.
    assert chained.iloc[2] == pytest.approx(120.0)
    assert chained.iloc[3] == pytest.approx(120.0)  # 2nd seg shifted +20
    assert chained.iloc[-1] == pytest.approx(140.0)


def test_chain_empty_list_returns_empty_series():
    chained = _chain_window_equities_dollar([])
    assert chained.empty
