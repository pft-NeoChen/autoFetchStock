"""
Phase 7.1 — Shioaji timestamp timezone normalization tests.

Covers all input flavours the Shioaji SDK 1.3.2 emits for tick/quote
timestamps and the boundary windows that previously triggered the
hour-band heuristic (>= 15 / < 8 in raw UTC hours).
"""

from datetime import datetime, timezone, timedelta

import pytest

from src.fetcher.shioaji_fetcher import ShioajiFetcher, get_tz_stats


_TPE_OFFSET = timedelta(hours=8)


def _utc(year, month, day, hour, minute, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


class TestNormalizeDatetime:
    """All branches must yield Asia/Taipei naive datetime."""

    def test_none_returns_none(self):
        assert ShioajiFetcher._normalize_datetime(None) is None

    def test_empty_string_returns_none(self):
        assert ShioajiFetcher._normalize_datetime("") is None

    def test_zero_epoch_returns_none(self):
        assert ShioajiFetcher._normalize_datetime(0) is None

    # ------- naive datetime path (most common: tick.datetime) -------
    # Shioaji 1.3.2 emits naive datetime where literal HH:MM is already
    # Taipei wall-clock (SDK uses utcfromtimestamp on Taipei-encoded
    # epoch). Must NOT add 8h — that double-shifts opening 09:00 → 17:00.

    def test_naive_datetime_is_taipei_wall_clock(self):
        raw = datetime(2026, 4, 23, 9, 0, 0)
        result = ShioajiFetcher._normalize_datetime(raw)
        assert result == datetime(2026, 4, 23, 9, 0, 0)
        assert result.tzinfo is None

    def test_naive_datetime_market_close(self):
        raw = datetime(2026, 4, 23, 13, 30, 0)
        assert ShioajiFetcher._normalize_datetime(raw) == datetime(
            2026, 4, 23, 13, 30, 0
        )

    def test_naive_datetime_pre_open_window(self):
        raw = datetime(2026, 4, 23, 8, 30, 0)
        assert ShioajiFetcher._normalize_datetime(raw) == datetime(
            2026, 4, 23, 8, 30, 0
        )

    # ------- aware datetime path -------

    def test_aware_datetime_utc(self):
        raw = _utc(2026, 4, 23, 6, 30, 0)
        assert ShioajiFetcher._normalize_datetime(raw) == datetime(
            2026, 4, 23, 14, 30, 0
        )

    def test_aware_datetime_taipei_passthrough(self):
        raw = datetime(2026, 4, 23, 14, 30, 0, tzinfo=timezone(_TPE_OFFSET))
        assert ShioajiFetcher._normalize_datetime(raw) == datetime(
            2026, 4, 23, 14, 30, 0
        )

    # ------- epoch path -------
    # Shioaji encodes Taipei wall-clock into the epoch (utcfromtimestamp
    # decode yields the same literal HH:MM), so a ns whose UTC decode is
    # 09:00 corresponds to Taipei 09:00.

    def test_epoch_seconds(self):
        raw_dt = _utc(2026, 4, 23, 9, 0, 0)
        assert ShioajiFetcher._normalize_datetime(raw_dt.timestamp()) == datetime(
            2026, 4, 23, 9, 0, 0
        )

    def test_epoch_nanoseconds(self):
        raw_dt = _utc(2026, 4, 23, 9, 0, 0)
        ns = int(raw_dt.timestamp() * 1_000_000_000)
        assert ShioajiFetcher._normalize_datetime(ns) == datetime(
            2026, 4, 23, 9, 0, 0
        )

    def test_epoch_boundary_post_close(self):
        ns = int(_utc(2026, 4, 23, 13, 30, 0).timestamp() * 1_000_000_000)
        assert ShioajiFetcher._normalize_datetime(ns).hour == 13

    # ------- string path -------

    def test_iso_string_with_utc_z(self):
        raw = "2026-04-23T06:30:00Z"
        assert ShioajiFetcher._normalize_datetime(raw) == datetime(
            2026, 4, 23, 14, 30, 0
        )

    def test_iso_string_naive(self):
        raw = "2026-04-23T09:00:00"
        assert ShioajiFetcher._normalize_datetime(raw) == datetime(
            2026, 4, 23, 9, 0, 0
        )

    def test_iso_string_offset(self):
        raw = "2026-04-23T14:30:00+08:00"
        assert ShioajiFetcher._normalize_datetime(raw) == datetime(
            2026, 4, 23, 14, 30, 0
        )

    def test_bad_string_returns_none(self):
        assert ShioajiFetcher._normalize_datetime("not-a-date") is None

    # ------- counter -------

    def test_counter_increments(self):
        before = get_tz_stats()["total"]
        ShioajiFetcher._normalize_datetime(datetime(2026, 4, 23, 9, 0, 0))
        ShioajiFetcher._normalize_datetime(0)  # none path, not counted
        ShioajiFetcher._normalize_datetime("2026-04-23T06:30:00Z")
        after = get_tz_stats()
        assert after["total"] == before + 2
        assert after["by_source"]["datetime_naive"] >= 1
        assert after["by_source"]["string"] >= 1
