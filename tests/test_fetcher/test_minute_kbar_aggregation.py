"""
Unit tests for ShioajiFetcher._aggregate_from_ticks.

Pure-function aggregation — no Shioaji connection needed. Tests the
single-bucket case, multi-bucket case, odd-lot exclusion, and empty
input.
"""

from __future__ import annotations

from datetime import date, datetime, time as dtime
from zoneinfo import ZoneInfo

import pytest

from src.fetcher.shioaji_fetcher import ShioajiFetcher
from src.models import IntradayTick, SpikeSeverity


_TZ = ZoneInfo("Asia/Taipei")


@pytest.fixture
def fetcher():
    """A bare ShioajiFetcher instance — bypasses __init__/login.

    We only call _aggregate_from_ticks which uses no instance state,
    so we don't need a real Shioaji session.
    """
    inst = ShioajiFetcher.__new__(ShioajiFetcher)
    return inst


def _make_tick(hour, minute, sec, *, price, volume, is_odd=False):
    ts = datetime(2026, 5, 15, hour, minute, sec, tzinfo=_TZ)
    return IntradayTick(
        time=dtime(hour, minute, sec),
        price=price,
        volume=volume,
        buy_volume=0,
        sell_volume=0,
        accumulated_volume=volume,
        timestamp=ts,
        is_odd=is_odd,
    )


class TestSingleBucket:
    def test_three_ticks_in_one_minute_yield_one_bar(self, fetcher):
        ticks = [
            _make_tick(10, 35, 5,  price=611.0, volume=10),
            _make_tick(10, 35, 30, price=612.0, volume=20),
            _make_tick(10, 35, 50, price=611.5, volume=5),
        ]
        bars = fetcher._aggregate_from_ticks("2330", date(2026, 5, 15), ticks)
        assert len(bars) == 1
        bar = bars[0]
        assert bar.timestamp.hour == 10 and bar.timestamp.minute == 35
        assert bar.open == 611.0
        assert bar.high == 612.0
        assert bar.low == 611.0
        assert bar.close == 611.5
        assert bar.volume == 35
        assert bar.tick_count == 3
        # vwap = (611*10 + 612*20 + 611.5*5) / 35
        expected_vwap = (611.0 * 10 + 612.0 * 20 + 611.5 * 5) / 35
        assert abs(bar.vwap - expected_vwap) < 1e-6

    def test_timestamp_carries_taipei_tz(self, fetcher):
        ticks = [_make_tick(10, 35, 0, price=600.0, volume=1)]
        bars = fetcher._aggregate_from_ticks("2330", date(2026, 5, 15), ticks)
        assert bars[0].timestamp.tzinfo is not None
        assert bars[0].timestamp.utcoffset().total_seconds() == 8 * 3600


class TestMultiBucket:
    def test_ticks_across_two_minutes_yield_two_bars(self, fetcher):
        ticks = [
            _make_tick(10, 35, 5,  price=600.0, volume=10),
            _make_tick(10, 35, 40, price=601.0, volume=20),
            _make_tick(10, 36, 10, price=602.0, volume=5),
            _make_tick(10, 36, 30, price=601.5, volume=15),
            _make_tick(10, 36, 55, price=603.0, volume=8),
        ]
        bars = fetcher._aggregate_from_ticks("2330", date(2026, 5, 15), ticks)
        assert len(bars) == 2
        b0, b1 = bars

        assert b0.timestamp.minute == 35
        assert b0.volume == 30 and b0.tick_count == 2
        assert b0.open == 600.0 and b0.close == 601.0
        assert b0.high == 601.0 and b0.low == 600.0

        assert b1.timestamp.minute == 36
        assert b1.volume == 28 and b1.tick_count == 3
        assert b1.open == 602.0 and b1.close == 603.0
        assert b1.high == 603.0 and b1.low == 601.5

    def test_buckets_returned_in_chronological_order(self, fetcher):
        # Ticks fed in reverse order — output must still be sorted.
        ticks = [
            _make_tick(10, 36, 5, price=602.0, volume=10),
            _make_tick(10, 35, 5, price=601.0, volume=20),
        ]
        bars = fetcher._aggregate_from_ticks("2330", date(2026, 5, 15), ticks)
        assert [b.timestamp.minute for b in bars] == [35, 36]


class TestOddLotExclusion:
    def test_odd_lot_ticks_skipped(self, fetcher):
        ticks = [
            _make_tick(10, 35, 5,  price=611.0, volume=100),
            _make_tick(10, 35, 30, price=612.0, volume=200),
            # Odd lot whose `volume` is in shares — must NOT contribute.
            _make_tick(10, 35, 50, price=611.5, volume=999, is_odd=True),
        ]
        bars = fetcher._aggregate_from_ticks("2330", date(2026, 5, 15), ticks)
        assert len(bars) == 1
        assert bars[0].volume == 300
        assert bars[0].tick_count == 2


class TestEmptyAndZero:
    def test_empty_list_returns_empty(self, fetcher):
        assert fetcher._aggregate_from_ticks("2330", date(2026, 5, 15), []) == []

    def test_ticks_with_zero_volume_skipped(self, fetcher):
        ticks = [
            _make_tick(10, 35, 5,  price=600.0, volume=0),
            _make_tick(10, 35, 30, price=601.0, volume=0),
        ]
        # All zero → no buckets produced.
        assert fetcher._aggregate_from_ticks("2330", date(2026, 5, 15), ticks) == []

    def test_detection_fields_are_default_normal(self, fetcher):
        ticks = [_make_tick(10, 35, 0, price=600.0, volume=10)]
        bars = fetcher._aggregate_from_ticks("2330", date(2026, 5, 15), ticks)
        bar = bars[0]
        # _aggregate_from_ticks does NOT run detection — it only fills
        # the OHLC/volume fields; spike fields must stay at defaults.
        assert bar.spike_severity == SpikeSeverity.NORMAL
        assert bar.is_volume_spike is False
        assert bar.baseline_volume is None
        assert bar.volume_ratio is None
