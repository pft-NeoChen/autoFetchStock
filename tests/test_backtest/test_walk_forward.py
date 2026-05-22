"""TASK-B05 — Walk-forward + embargo (V2 §3.4)."""

from __future__ import annotations

from datetime import date

import pytest

from src.backtest.walk_forward import (
    WalkForwardWindow,
    classify_oos_confidence,
    merge_small_windows,
    walk_forward_windows,
)


@pytest.mark.unit
def test_windows_have_is_then_embargo_then_oos() -> None:
    windows = walk_forward_windows(
        start=date(2023, 1, 2),
        end=date(2024, 12, 31),
        is_months=12,
        oos_months=3,
        embargo_business_days=15,
    )
    assert len(windows) > 0
    w = windows[0]
    assert w.is_start == date(2023, 1, 2)
    # IS ends 12 months later (calendar)
    assert w.is_end > w.is_start
    # OOS starts after embargo (≥ 15 business days gap from is_end)
    embargo_days = (w.oos_start - w.is_end).days
    assert embargo_days >= 15  # business days ≤ calendar days


@pytest.mark.unit
def test_windows_roll_by_oos_size() -> None:
    windows = walk_forward_windows(
        start=date(2022, 1, 3),
        end=date(2024, 12, 31),
        is_months=12,
        oos_months=3,
        embargo_business_days=15,
    )
    # Each subsequent window's IS shifts by oos_months
    for prev, curr in zip(windows, windows[1:]):
        diff = (curr.is_start.year - prev.is_start.year) * 12 + (curr.is_start.month - prev.is_start.month)
        assert diff == 3


@pytest.mark.unit
def test_windows_stop_before_exceeding_end() -> None:
    windows = walk_forward_windows(
        start=date(2023, 1, 2),
        end=date(2024, 6, 30),
        is_months=12,
        oos_months=3,
        embargo_business_days=15,
    )
    assert all(w.oos_end <= date(2024, 6, 30) for w in windows)


@pytest.mark.unit
def test_merge_small_window_combines_into_next() -> None:
    """OOS with < 10 trades merged with the next window."""
    windows = [
        WalkForwardWindow(date(2023, 1, 1), date(2023, 12, 31),
                          date(2024, 1, 22), date(2024, 3, 31), trade_count=5),
        WalkForwardWindow(date(2023, 4, 1), date(2024, 3, 31),
                          date(2024, 4, 22), date(2024, 6, 30), trade_count=12),
    ]
    merged = merge_small_windows(windows, min_trades=10)
    # The 5-trade window is fused into the next; result has 1 entry with combined trades
    assert len(merged) == 1
    assert merged[0].trade_count == 5 + 12
    assert merged[0].oos_start == date(2024, 1, 22)
    assert merged[0].oos_end == date(2024, 6, 30)


@pytest.mark.unit
def test_merged_still_small_is_marked_low_confidence() -> None:
    windows = [
        WalkForwardWindow(date(2023, 1, 1), date(2023, 12, 31),
                          date(2024, 1, 22), date(2024, 3, 31), trade_count=3),
        WalkForwardWindow(date(2023, 4, 1), date(2024, 3, 31),
                          date(2024, 4, 22), date(2024, 6, 30), trade_count=4),
    ]
    merged = merge_small_windows(windows, min_trades=10)
    # All fused into final window with 7 trades total; flagged LOW_CONFIDENCE
    flagged = [classify_oos_confidence(w, min_trades=10) for w in merged]
    assert "LOW_CONFIDENCE" in flagged


@pytest.mark.unit
def test_classify_normal_confidence() -> None:
    w = WalkForwardWindow(
        date(2023, 1, 1), date(2023, 12, 31),
        date(2024, 1, 22), date(2024, 3, 31),
        trade_count=15,
    )
    assert classify_oos_confidence(w, min_trades=10) == "OK"


@pytest.mark.unit
def test_no_overlap_between_is_and_oos() -> None:
    windows = walk_forward_windows(
        start=date(2022, 1, 3),
        end=date(2024, 12, 31),
        is_months=12,
        oos_months=3,
        embargo_business_days=15,
    )
    for w in windows:
        assert w.oos_start > w.is_end
