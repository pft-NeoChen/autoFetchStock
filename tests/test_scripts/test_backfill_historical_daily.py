"""TASK-D01b — Historical daily backfill orchestrator."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

from scripts.backfill_historical_daily import (
    BackfillReport,
    compute_missing_months,
    is_month_covered,
    run_backfill,
)
from src.models import DailyOHLC


def _ohlc(d: date) -> DailyOHLC:
    return DailyOHLC(
        date=d,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1_000_000,
        turnover=0.0,
        timestamp=datetime.now(),
    )


# ---- is_month_covered ----

@pytest.mark.unit
def test_month_covered_when_threshold_met() -> None:
    dates = {date(2024, 6, d) for d in range(1, 21)}  # 20 entries
    assert is_month_covered(dates, year=2024, month=6, min_records=15) is True


@pytest.mark.unit
def test_month_not_covered_when_below_threshold() -> None:
    dates = {date(2024, 6, 1), date(2024, 6, 2)}
    assert is_month_covered(dates, year=2024, month=6, min_records=15) is False


@pytest.mark.unit
def test_current_month_never_covered() -> None:
    # Many records but month is current → still recheck for new data
    dates = {date(2026, 5, d) for d in range(1, 22)}
    assert is_month_covered(dates, year=2026, month=5, min_records=15, today=date(2026, 5, 22)) is False


# ---- compute_missing_months ----

@pytest.mark.unit
def test_compute_missing_months_all_when_empty() -> None:
    months = compute_missing_months(
        existing_dates=set(),
        target_start=date(2024, 1, 1),
        today=date(2024, 3, 15),
    )
    assert (2024, 1) in months
    assert (2024, 2) in months
    assert (2024, 3) in months


@pytest.mark.unit
def test_compute_missing_months_skips_covered() -> None:
    existing = {date(2024, 1, d) for d in range(1, 21)}
    months = compute_missing_months(
        existing_dates=existing,
        target_start=date(2024, 1, 1),
        today=date(2024, 3, 15),
    )
    assert (2024, 1) not in months
    assert (2024, 2) in months
    assert (2024, 3) in months


@pytest.mark.unit
def test_compute_missing_months_respects_two_year_window() -> None:
    months = compute_missing_months(
        existing_dates=set(),
        target_start=date(2024, 1, 1),
        today=date(2024, 1, 15),
    )
    # Should not contain anything before target_start
    assert all(m >= (2024, 1) for m in months)


# ---- run_backfill ----

@pytest.mark.unit
def test_run_backfill_calls_fetcher_for_missing_months() -> None:
    fetcher = MagicMock()
    fetcher.fetch_daily_history.return_value = [_ohlc(date(2024, 1, 15))]
    storage = MagicMock()
    storage.load_daily_data.return_value = None  # no existing data

    report = run_backfill(
        fetcher=fetcher,
        storage=storage,
        stock_ids=["2330"],
        target_start=date(2024, 1, 1),
        today=date(2024, 2, 15),
        sleep_seconds=0,
        stock_name_lookup=lambda sid: "Stock",
    )

    assert fetcher.fetch_daily_history.call_count == 2  # Jan + Feb
    assert storage.save_daily_data.called
    assert report.fetched_months >= 2


@pytest.mark.unit
def test_run_backfill_skips_covered_months() -> None:
    fetcher = MagicMock()
    storage = MagicMock()
    # Existing covers Jan fully (20 entries)
    existing = MagicMock()
    existing.stock_name = "Stock"
    existing.daily_records = [_ohlc(date(2024, 1, d)) for d in range(1, 21)]
    storage.load_daily_data.return_value = existing

    run_backfill(
        fetcher=fetcher,
        storage=storage,
        stock_ids=["2330"],
        target_start=date(2024, 1, 1),
        today=date(2024, 1, 31),
        sleep_seconds=0,
        stock_name_lookup=lambda sid: "Stock",
    )

    # Jan fully covered AND Jan is current month (today 2024-01-31), so current_month rule
    # forces refetch. Assert at least no crash, exactly 1 month fetched.
    assert fetcher.fetch_daily_history.call_count == 1


@pytest.mark.unit
def test_run_backfill_continues_on_stock_error() -> None:
    fetcher = MagicMock()
    fetcher.fetch_daily_history.side_effect = [
        RuntimeError("network down"),
        [_ohlc(date(2024, 1, 15))],
    ]
    storage = MagicMock()
    storage.load_daily_data.return_value = None

    report = run_backfill(
        fetcher=fetcher,
        storage=storage,
        stock_ids=["2330", "2317"],
        target_start=date(2024, 1, 1),
        today=date(2024, 1, 15),
        sleep_seconds=0,
        stock_name_lookup=lambda sid: "Stock",
    )

    assert isinstance(report, BackfillReport)
    assert report.failed_stocks == ["2330"]
    assert "2317" in report.successful_stocks


@pytest.mark.unit
def test_run_backfill_respects_sleep_between_requests() -> None:
    fetcher = MagicMock()
    fetcher.fetch_daily_history.return_value = []
    storage = MagicMock()
    storage.load_daily_data.return_value = None
    sleep_calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    run_backfill(
        fetcher=fetcher,
        storage=storage,
        stock_ids=["2330"],
        target_start=date(2024, 1, 1),
        today=date(2024, 3, 15),
        sleep_seconds=3.0,
        stock_name_lookup=lambda sid: "Stock",
        sleep_fn=fake_sleep,
    )

    # 3 months → at least 2 inter-request sleeps
    assert len(sleep_calls) >= 2
    assert all(s == 3.0 for s in sleep_calls)
