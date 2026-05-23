"""TASK-M01 RED tests — Data Freshness Guard (V2 §9.1)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.monitor.data_freshness_guard import (
    DataFreshnessGuard,
    DataSource,
    FreshnessConfig,
    HaltReason,
    check_staleness,
    detect_gaps,
)


pytestmark = pytest.mark.unit


# --- pure helpers ---------------------------------------------------------


def test_check_staleness_within_threshold_is_fresh():
    last = datetime(2026, 5, 23, 13, 0, 0)
    now = last + timedelta(seconds=5)
    fresh, age = check_staleness(last, now, max_sec=10.0)
    assert fresh is True
    assert age == pytest.approx(5.0)


def test_check_staleness_beyond_threshold_is_stale():
    last = datetime(2026, 5, 23, 13, 0, 0)
    now = last + timedelta(seconds=20)
    fresh, age = check_staleness(last, now, max_sec=10.0)
    assert fresh is False
    assert age == pytest.approx(20.0)


def test_check_staleness_none_last_ts_returns_not_fresh():
    fresh, age = check_staleness(None, datetime(2026, 5, 23), max_sec=10.0)
    assert fresh is False
    assert age is None


def test_detect_gaps_uniform_series_returns_empty():
    base = datetime(2026, 5, 23, 9, 0, 0)
    ts = [base + timedelta(seconds=5 * i) for i in range(5)]
    assert detect_gaps(ts, max_gap_sec=10.0) == []


def test_detect_gaps_finds_one_gap():
    base = datetime(2026, 5, 23, 9, 0, 0)
    ts = [base, base + timedelta(seconds=5), base + timedelta(seconds=25)]
    gaps = detect_gaps(ts, max_gap_sec=10.0)
    assert len(gaps) == 1
    before, after, span = gaps[0]
    assert before == base + timedelta(seconds=5)
    assert after == base + timedelta(seconds=25)
    assert span == pytest.approx(20.0)


def test_detect_gaps_short_series_no_pair_returns_empty():
    assert detect_gaps([datetime(2026, 5, 23)], max_gap_sec=1.0) == []
    assert detect_gaps([], max_gap_sec=1.0) == []


# --- guard stateful behaviour --------------------------------------------


def _cfg(**kw) -> FreshnessConfig:
    base = dict(max_staleness_sec=10.0, max_gap_sec=10.0, stream_timeout_sec=30.0)
    base.update(kw)
    return FreshnessConfig(**base)


def test_guard_no_data_reports_no_data_reason():
    guard = DataFreshnessGuard(_cfg())
    status = guard.check(DataSource.TWSE, datetime(2026, 5, 23))
    assert status.is_fresh is False
    assert status.last_ts is None
    assert HaltReason.NO_DATA.value in status.reasons


def test_guard_record_then_check_within_threshold_fresh():
    guard = DataFreshnessGuard(_cfg())
    t0 = datetime(2026, 5, 23, 13, 0, 0)
    guard.record_tick(DataSource.TWSE, t0)
    status = guard.check(DataSource.TWSE, t0 + timedelta(seconds=5))
    assert status.is_fresh is True
    assert status.age_sec == pytest.approx(5.0)
    assert status.reasons == ()


def test_guard_stale_when_age_exceeds_max_staleness():
    guard = DataFreshnessGuard(_cfg(max_staleness_sec=10.0))
    t0 = datetime(2026, 5, 23, 13, 0, 0)
    guard.record_tick(DataSource.TWSE, t0)
    status = guard.check(DataSource.TWSE, t0 + timedelta(seconds=20))
    assert status.is_fresh is False
    assert HaltReason.STALE.value in status.reasons


def test_guard_stream_stop_when_age_exceeds_stream_timeout():
    guard = DataFreshnessGuard(_cfg(max_staleness_sec=10.0, stream_timeout_sec=30.0))
    t0 = datetime(2026, 5, 23, 13, 0, 0)
    guard.record_tick(DataSource.TWSE, t0)
    status = guard.check(DataSource.TWSE, t0 + timedelta(seconds=45))
    assert status.is_fresh is False
    assert HaltReason.STREAM_STOP.value in status.reasons
    assert HaltReason.STALE.value in status.reasons


def test_guard_gap_in_recent_history_flagged():
    guard = DataFreshnessGuard(_cfg(max_gap_sec=10.0))
    base = datetime(2026, 5, 23, 13, 0, 0)
    guard.record_tick(DataSource.TWSE, base)
    guard.record_tick(DataSource.TWSE, base + timedelta(seconds=5))
    guard.record_tick(DataSource.TWSE, base + timedelta(seconds=30))
    status = guard.check(DataSource.TWSE, base + timedelta(seconds=32))
    assert HaltReason.GAP.value in status.reasons
    assert status.is_fresh is False


def test_guard_per_source_independent():
    guard = DataFreshnessGuard(_cfg())
    t0 = datetime(2026, 5, 23, 13, 0, 0)
    guard.record_tick(DataSource.TWSE, t0)
    # Shioaji never registered.
    twse = guard.check(DataSource.TWSE, t0 + timedelta(seconds=2))
    shi = guard.check(DataSource.SHIOAJI, t0 + timedelta(seconds=2))
    assert twse.is_fresh is True
    assert shi.is_fresh is False
    assert HaltReason.NO_DATA.value in shi.reasons


def test_guard_should_halt_true_when_any_source_stale():
    guard = DataFreshnessGuard(_cfg(max_staleness_sec=10.0))
    t0 = datetime(2026, 5, 23, 13, 0, 0)
    guard.record_tick(DataSource.TWSE, t0)
    guard.record_tick(DataSource.SHIOAJI, t0)
    halt, statuses = guard.should_halt(t0 + timedelta(seconds=25))
    assert halt is True
    assert DataSource.TWSE in statuses
    assert DataSource.SHIOAJI in statuses
    assert all(not s.is_fresh for s in statuses.values())


def test_guard_should_halt_false_when_all_registered_sources_fresh():
    guard = DataFreshnessGuard(_cfg(max_staleness_sec=10.0))
    t0 = datetime(2026, 5, 23, 13, 0, 0)
    guard.record_tick(DataSource.TWSE, t0)
    guard.record_tick(DataSource.SHIOAJI, t0 + timedelta(seconds=1))
    halt, statuses = guard.should_halt(t0 + timedelta(seconds=5))
    assert halt is False
    assert all(s.is_fresh for s in statuses.values())


def test_guard_record_out_of_order_keeps_latest_for_staleness():
    guard = DataFreshnessGuard(_cfg())
    t0 = datetime(2026, 5, 23, 13, 0, 0)
    guard.record_tick(DataSource.TWSE, t0 + timedelta(seconds=10))
    guard.record_tick(DataSource.TWSE, t0)  # late-arriving older tick
    status = guard.check(DataSource.TWSE, t0 + timedelta(seconds=12))
    # age measured against the latest known timestamp, not insertion order.
    assert status.age_sec == pytest.approx(2.0)


def test_guard_history_window_trims_old_ticks():
    guard = DataFreshnessGuard(_cfg(gap_history_window=3))
    base = datetime(2026, 5, 23, 13, 0, 0)
    for i in range(10):
        guard.record_tick(DataSource.TWSE, base + timedelta(seconds=i))
    # latest 3 ticks should be uniform 1s apart → no gap.
    status = guard.check(DataSource.TWSE, base + timedelta(seconds=10))
    assert HaltReason.GAP.value not in status.reasons
