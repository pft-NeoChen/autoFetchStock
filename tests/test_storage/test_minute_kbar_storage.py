"""
Unit tests for MinuteKBarStorage (Volume Spike Detection).

Covers atomic round-trip, corrupted-file backup, same-time-slot
historical query (skip weekends + end_date exclusivity), and
concurrent append_bar safety.
"""

from __future__ import annotations

import threading
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.models import MinuteKBar, StockMinuteKFile
from src.storage.minute_kbar_storage import MinuteKBarStorage


_TZ = ZoneInfo("Asia/Taipei")


def _make_bar(
    stock_id: str,
    ts: datetime,
    *,
    volume: int = 500,
    close: float = 602.0,
    open_: float = 600.0,
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


class TestRoundTrip:
    def test_save_then_load_preserves_fields(self, storage):
        bar = _make_bar("2330", datetime(2026, 5, 15, 10, 35, tzinfo=_TZ))
        file = StockMinuteKFile(
            stock_id="2330", stock_name="台積電",
            date=date(2026, 5, 15), bars=[bar],
        )
        storage.save(file)

        loaded = storage.load("2330", date(2026, 5, 15))
        assert loaded is not None
        assert loaded.stock_id == "2330"
        assert loaded.stock_name == "台積電"
        assert len(loaded.bars) == 1
        assert loaded.bars[0].volume == 500
        assert loaded.bars[0].vwap == 602.0
        assert loaded.bars[0].timestamp == bar.timestamp

    def test_load_missing_returns_none(self, storage):
        assert storage.load("9999", date(2026, 5, 15)) is None

    def test_append_bar_replaces_same_timestamp(self, storage):
        ts = datetime(2026, 5, 15, 10, 36, tzinfo=_TZ)
        storage.append_bar("2330", "台積電", _make_bar("2330", ts, volume=100))
        storage.append_bar("2330", "台積電", _make_bar("2330", ts, volume=999))

        loaded = storage.load("2330", date(2026, 5, 15))
        assert len(loaded.bars) == 1
        assert loaded.bars[0].volume == 999


class TestCorruptedBackup:
    def test_invalid_json_is_backed_up_and_load_returns_none(self, storage, tmp_path):
        path = storage._file_path("9999", date(2026, 5, 15))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")

        assert storage.load("9999", date(2026, 5, 15)) is None

        backups = list((tmp_path / "backup").glob("*.corrupted"))
        assert len(backups) == 1
        assert "9999_20260515" in backups[0].name


class TestSameTimeBars:
    def test_returns_n_trading_days_skipping_weekends(self, storage):
        # 7 consecutive trading days starting Mon 2026-05-04.
        days = []
        cursor = date(2026, 5, 4)
        while len(days) < 7:
            if cursor.weekday() < 5:
                days.append(cursor)
            cursor += timedelta(days=1)

        for d in days:
            ts = datetime(d.year, d.month, d.day, 10, 35, tzinfo=_TZ)
            storage.save(StockMinuteKFile(
                stock_id="2330", stock_name="台積電", date=d,
                bars=[_make_bar("2330", ts)],
            ))

        # end_date exclusive: pick the next trading day after the last
        # one with data, so we look back into the 7 stored days.
        end_d = days[-1] + timedelta(days=1)
        while end_d.weekday() >= 5:
            end_d += timedelta(days=1)

        result = storage.load_same_time_bars(
            "2330", time(10, 35), days=5, end_date=end_d,
        )
        assert len(result) == 5
        # Newest first.
        assert result[0].timestamp.date() == days[-1]
        assert result[-1].timestamp.date() == days[-5]

    def test_skips_days_with_no_file(self, storage):
        # Only seed 3 trading days out of the past 5.
        days = [date(2026, 5, 4), date(2026, 5, 6), date(2026, 5, 8)]  # Mon, Wed, Fri
        for d in days:
            ts = datetime(d.year, d.month, d.day, 10, 35, tzinfo=_TZ)
            storage.save(StockMinuteKFile(
                stock_id="2330", stock_name="台積電", date=d,
                bars=[_make_bar("2330", ts)],
            ))

        end_d = date(2026, 5, 11)  # Mon after that week
        result = storage.load_same_time_bars(
            "2330", time(10, 35), days=5, end_date=end_d,
        )
        assert len(result) == 3
        assert {b.timestamp.date() for b in result} == set(days)

    def test_zero_days_returns_empty(self, storage):
        assert storage.load_same_time_bars(
            "2330", time(10, 35), days=0, end_date=date(2026, 5, 15),
        ) == []


class TestRecentBars:
    def test_filters_before_timestamp_and_limits_n(self, storage):
        target = date(2026, 5, 15)
        bars = [
            _make_bar("2330", datetime(2026, 5, 15, 9, m, tzinfo=_TZ))
            for m in range(10)
        ]
        storage.save(StockMinuteKFile(
            stock_id="2330", stock_name="台積電", date=target, bars=bars,
        ))

        result = storage.load_recent_bars(
            "2330", target,
            before_timestamp=datetime(2026, 5, 15, 9, 7, tzinfo=_TZ),
            n=3,
        )
        assert len(result) == 3
        # Last 3 strictly before 09:07: 09:04, 09:05, 09:06
        assert [b.timestamp.minute for b in result] == [4, 5, 6]

    def test_no_file_returns_empty(self, storage):
        assert storage.load_recent_bars(
            "9999", date(2026, 5, 15),
            before_timestamp=datetime(2026, 5, 15, 10, 0, tzinfo=_TZ),
            n=10,
        ) == []


class TestConcurrentAppend:
    def test_append_from_multiple_threads_does_not_lose_bars(self, storage):
        target = date(2026, 5, 15)
        bars = [
            _make_bar("2330", datetime(2026, 5, 15, 9, m, tzinfo=_TZ))
            for m in range(20)
        ]

        errors: list = []

        def worker(b):
            try:
                storage.append_bar("2330", "台積電", b)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(b,)) for b in bars]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        loaded = storage.load("2330", target)
        assert loaded is not None
        # All 20 unique minutes should be present.
        minutes = sorted(b.timestamp.minute for b in loaded.bars)
        assert minutes == list(range(20))
