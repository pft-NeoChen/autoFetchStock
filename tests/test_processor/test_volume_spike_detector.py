"""
Unit tests for VolumeSpikeDetector (Volume Spike Detection).

Covers severity ladder, absolute-volume floor, hybrid baseline
(法 B preferred, 法 A fallback), trimmed mean, ex-dividend skip,
and zero-volume short-circuit.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.models import MinuteKBar, StockMinuteKFile, SpikeSeverity, PriceDirection
from src.processor.volume_spike_detector import VolumeSpikeDetector
from src.storage.minute_kbar_storage import MinuteKBarStorage


_TZ = ZoneInfo("Asia/Taipei")


def _make_bar(
    stock_id: str,
    ts: datetime,
    *,
    volume: int = 500,
    open_: float = 600.0,
    close: float = 602.0,
) -> MinuteKBar:
    return MinuteKBar(
        stock_id=stock_id,
        timestamp=ts,
        open=open_,
        high=max(open_, close) + 0.5,
        low=min(open_, close) - 0.5,
        close=close,
        volume=volume,
        amount=volume * close * 1000.0,
        tick_count=10,
        vwap=close,
    )


@pytest.fixture
def storage(tmp_path):
    return MinuteKBarStorage(
        data_dir=tmp_path / "kbars",
        backup_dir=tmp_path / "backup",
    )


def _seed_history(storage, stock_id, target_time, volumes):
    """Seed N prior trading days at the given time-of-day (datetime.time)."""
    days = []
    cursor = date(2026, 5, 4)  # Mon
    while len(days) < len(volumes):
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    for d, v in zip(days, volumes):
        ts = datetime(
            d.year, d.month, d.day,
            target_time.hour, target_time.minute, tzinfo=_TZ,
        )
        storage.save(StockMinuteKFile(
            stock_id=stock_id, stock_name="X", date=d,
            bars=[_make_bar(stock_id, ts, volume=v)],
        ))
    return days


def _next_trading_day_after(d):
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


class TestSeverityLadder:
    def test_low_severity(self, storage):
        days = _seed_history(storage, "2330", time(10, 35), [100] * 5)
        target_d = _next_trading_day_after(days[-1])
        bar = _make_bar("2330",
            datetime(target_d.year, target_d.month, target_d.day, 10, 35, tzinfo=_TZ),
            volume=250)  # 2.5x

        result = VolumeSpikeDetector(storage).detect(bar)
        assert result.spike_severity == SpikeSeverity.LOW
        assert result.is_volume_spike is True
        assert abs(result.volume_ratio - 2.5) < 1e-6

    def test_mid_severity(self, storage):
        days = _seed_history(storage, "2330", time(10, 35), [100] * 5)
        target_d = _next_trading_day_after(days[-1])
        bar = _make_bar("2330",
            datetime(target_d.year, target_d.month, target_d.day, 10, 35, tzinfo=_TZ),
            volume=400)  # 4.0x

        result = VolumeSpikeDetector(storage).detect(bar)
        assert result.spike_severity == SpikeSeverity.MID

    def test_high_severity(self, storage):
        days = _seed_history(storage, "2330", time(10, 35), [100] * 5)
        target_d = _next_trading_day_after(days[-1])
        bar = _make_bar("2330",
            datetime(target_d.year, target_d.month, target_d.day, 10, 35, tzinfo=_TZ),
            volume=600)  # 6.0x

        result = VolumeSpikeDetector(storage).detect(bar)
        assert result.spike_severity == SpikeSeverity.HIGH

    def test_extreme_severity(self, storage):
        days = _seed_history(storage, "2330", time(10, 35), [100] * 5)
        target_d = _next_trading_day_after(days[-1])
        bar = _make_bar("2330",
            datetime(target_d.year, target_d.month, target_d.day, 10, 35, tzinfo=_TZ),
            volume=1500)  # 15x

        result = VolumeSpikeDetector(storage).detect(bar)
        assert result.spike_severity == SpikeSeverity.EXTREME

    def test_below_low_threshold_is_normal(self, storage):
        days = _seed_history(storage, "2330", time(10, 35), [100] * 5)
        target_d = _next_trading_day_after(days[-1])
        bar = _make_bar("2330",
            datetime(target_d.year, target_d.month, target_d.day, 10, 35, tzinfo=_TZ),
            volume=180)  # 1.8x — under LOW threshold

        result = VolumeSpikeDetector(storage).detect(bar)
        assert result.spike_severity == SpikeSeverity.NORMAL
        assert result.is_volume_spike is False


class TestAbsoluteVolumeFloor:
    def test_under_floor_forces_normal(self, storage):
        # baseline 10 lots → ratio 5.0 BUT volume only 50 < 100 floor
        days = _seed_history(storage, "2330", time(10, 35), [10] * 5)
        target_d = _next_trading_day_after(days[-1])
        bar = _make_bar("2330",
            datetime(target_d.year, target_d.month, target_d.day, 10, 35, tzinfo=_TZ),
            volume=50)

        result = VolumeSpikeDetector(storage).detect(bar)
        # Severity forced NORMAL by absolute-volume floor.
        assert result.spike_severity == SpikeSeverity.NORMAL
        # Baseline + ratio should still be filled for tooltip use.
        assert result.baseline_volume == 10
        assert abs(result.volume_ratio - 5.0) < 1e-6


class TestZeroVolumeShortCircuit:
    def test_zero_volume_returns_normal_with_no_baseline(self, storage):
        _seed_history(storage, "2330", time(10, 35), [100] * 5)
        bar = _make_bar("2330",
            datetime(2026, 5, 15, 10, 35, tzinfo=_TZ),
            volume=0, open_=600.0, close=600.0)

        result = VolumeSpikeDetector(storage).detect(bar)
        assert result.spike_severity == SpikeSeverity.NORMAL
        assert result.baseline_volume is None


class TestBaselineHybrid:
    def test_method_b_used_when_min_days_met(self, storage):
        # 5 days at 10:35 with [100, 110, 120, 90, 105]
        # Trimmed (drop max 120, min 90) -> [100, 105, 110] mean=105
        days = _seed_history(storage, "2330",
                             time(10, 35),
                             [100, 110, 120, 90, 105])
        target_d = _next_trading_day_after(days[-1])
        bar = _make_bar("2330",
            datetime(target_d.year, target_d.month, target_d.day, 10, 35, tzinfo=_TZ),
            volume=600)

        result = VolumeSpikeDetector(storage).detect(bar)
        assert result.baseline_volume == 105
        assert result.baseline_low_confidence is False

    def test_falls_back_to_method_a_when_history_insufficient(self, storage):
        # Only 2 historical days — below SPIKE_BASELINE_MIN_DAYS (3) → 法 A
        target_d = date(2026, 5, 18)  # Mon
        # Same-day intraday: 25 bars, opening 5 high-volume + 20 baseline=200
        intraday = []
        for i in range(25):
            ts = datetime(target_d.year, target_d.month, target_d.day, 9, i, tzinfo=_TZ)
            intraday.append(_make_bar("2454", ts, volume=1000 if i < 5 else 200))
        storage.save(StockMinuteKFile(
            stock_id="2454", stock_name="聯發科", date=target_d, bars=intraday,
        ))

        new_bar = _make_bar("2454",
            datetime(target_d.year, target_d.month, target_d.day, 9, 25, tzinfo=_TZ),
            volume=600)

        result = VolumeSpikeDetector(storage).detect(new_bar)
        # Fallback baseline = mean of bars[5:25] all volume=200 → 200
        assert result.baseline_low_confidence is True
        assert result.baseline_volume == 200
        assert abs(result.volume_ratio - 3.0) < 1e-6
        assert result.spike_severity == SpikeSeverity.MID

    def test_no_history_at_all_returns_normal(self, storage):
        bar = _make_bar("9999",
            datetime(2026, 5, 15, 10, 35, tzinfo=_TZ),
            volume=600)
        result = VolumeSpikeDetector(storage).detect(bar)
        assert result.baseline_volume is None
        assert result.baseline_low_confidence is True
        assert result.spike_severity == SpikeSeverity.NORMAL


class TestTrimmedMean:
    def test_drops_top_and_bottom_when_5_or_more(self):
        # [100, 110, 1000, 90, 105] sorted = [90, 100, 105, 110, 1000]
        # trim → [100, 105, 110] mean = 105
        assert VolumeSpikeDetector._trimmed_mean([100, 110, 1000, 90, 105]) == 105

    def test_no_trim_below_5(self):
        # 4 samples: keep all
        assert VolumeSpikeDetector._trimmed_mean([10, 20, 30, 40]) == 25


class TestExDividendSkip:
    def test_ex_div_day_returns_normal_with_no_baseline_lookup(self, storage):
        days = _seed_history(storage, "2330", time(10, 35), [100] * 5)
        target_d = _next_trading_day_after(days[-1])
        bar = _make_bar("2330",
            datetime(target_d.year, target_d.month, target_d.day, 10, 35, tzinfo=_TZ),
            volume=600)

        detector = VolumeSpikeDetector(
            storage,
            events_provider=lambda sid, d: True,
        )
        result = detector.detect(bar)
        assert result.spike_severity == SpikeSeverity.NORMAL
        assert result.baseline_volume is None

    def test_ex_div_provider_exception_does_not_break_detection(self, storage):
        days = _seed_history(storage, "2330", time(10, 35), [100] * 5)
        target_d = _next_trading_day_after(days[-1])
        bar = _make_bar("2330",
            datetime(target_d.year, target_d.month, target_d.day, 10, 35, tzinfo=_TZ),
            volume=600)

        def bad(sid, d):
            raise RuntimeError("boom")

        detector = VolumeSpikeDetector(storage, events_provider=bad)
        # Should not raise; falls through to normal detection.
        result = detector.detect(bar)
        assert result.spike_severity == SpikeSeverity.HIGH


class TestPriceDirection:
    @pytest.mark.parametrize(
        "open_,close,expected",
        [
            (600.0, 602.0, PriceDirection.UP),
            (602.0, 600.0, PriceDirection.DOWN),
            (600.0, 600.0, PriceDirection.FLAT),
        ],
    )
    def test_direction_matches_open_close(self, storage, open_, close, expected):
        ts = datetime(2026, 5, 15, 10, 35, tzinfo=_TZ)
        bar = _make_bar("2330", ts, volume=100, open_=open_, close=close)
        result = VolumeSpikeDetector(storage).detect(bar)
        assert result.price_direction == expected
