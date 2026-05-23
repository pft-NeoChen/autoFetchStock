"""TASK-D01c — Historical chip-flow backfill orchestrator."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from scripts.backfill_historical_chips import (
    ChipsBackfillReport,
    compute_missing_dates,
    is_trading_day,
    run_chips_backfill,
)


# ---- is_trading_day ----

@pytest.mark.unit
def test_is_trading_day_weekday() -> None:
    assert is_trading_day(date(2024, 6, 3)) is True  # Mon
    assert is_trading_day(date(2024, 6, 7)) is True  # Fri


@pytest.mark.unit
def test_is_trading_day_weekend() -> None:
    assert is_trading_day(date(2024, 6, 8)) is False  # Sat
    assert is_trading_day(date(2024, 6, 9)) is False  # Sun


# ---- compute_missing_dates ----

@pytest.mark.unit
def test_compute_missing_dates_returns_all_weekdays_when_empty() -> None:
    missing = compute_missing_dates(
        target_start=date(2024, 6, 3),  # Mon
        today=date(2024, 6, 7),  # Fri
        has_t86=lambda d: False,
        has_margin=lambda d: False,
    )
    assert missing == [
        date(2024, 6, 3),
        date(2024, 6, 4),
        date(2024, 6, 5),
        date(2024, 6, 6),
        date(2024, 6, 7),
    ]


@pytest.mark.unit
def test_compute_missing_dates_skips_weekends() -> None:
    missing = compute_missing_dates(
        target_start=date(2024, 6, 7),  # Fri
        today=date(2024, 6, 10),  # Mon
        has_t86=lambda d: False,
        has_margin=lambda d: False,
    )
    assert date(2024, 6, 8) not in missing  # Sat
    assert date(2024, 6, 9) not in missing  # Sun
    assert date(2024, 6, 7) in missing
    assert date(2024, 6, 10) in missing


@pytest.mark.unit
def test_compute_missing_dates_skips_when_both_snapshots_exist() -> None:
    covered = {date(2024, 6, 4)}
    missing = compute_missing_dates(
        target_start=date(2024, 6, 3),
        today=date(2024, 6, 5),
        has_t86=lambda d: d in covered,
        has_margin=lambda d: d in covered,
    )
    assert date(2024, 6, 4) not in missing
    assert date(2024, 6, 3) in missing
    assert date(2024, 6, 5) in missing


@pytest.mark.unit
def test_compute_missing_dates_includes_when_only_one_snapshot_exists() -> None:
    # T86 exists but margin missing → still need fetch
    missing = compute_missing_dates(
        target_start=date(2024, 6, 4),
        today=date(2024, 6, 4),
        has_t86=lambda d: True,
        has_margin=lambda d: False,
    )
    assert missing == [date(2024, 6, 4)]


# ---- run_chips_backfill ----

def _empty_storage() -> MagicMock:
    storage = MagicMock()
    storage.load_t86_day.return_value = None
    storage.load_margin_day.return_value = None
    return storage


def _stub_fetcher(
    t86: Optional[dict] = None,
    tpex_t86: Optional[dict] = None,
    margin: Optional[dict] = None,
    tpex_margin: Optional[dict] = None,
) -> MagicMock:  # type: ignore[name-defined]
    fetcher = MagicMock()
    fetcher.fetch_t86.return_value = t86 or {}
    fetcher.fetch_tpex_t86.return_value = tpex_t86 or {}
    fetcher.fetch_margin.return_value = margin or {}
    fetcher.fetch_tpex_margin.return_value = tpex_margin or {}
    return fetcher


# late import to keep helper signature compact
from typing import Optional  # noqa: E402


@pytest.mark.unit
def test_run_calls_all_four_endpoints_per_day() -> None:
    fetcher = _stub_fetcher(t86={"2330": {"foreign_net": 1}}, margin={"2330": {"margin_balance": 1}})
    storage = _empty_storage()

    run_chips_backfill(
        fetcher=fetcher,
        storage=storage,
        target_start=date(2024, 6, 3),  # Mon
        today=date(2024, 6, 3),
        sleep_seconds=0,
    )

    assert fetcher.fetch_t86.call_count == 1
    assert fetcher.fetch_tpex_t86.call_count == 1
    assert fetcher.fetch_margin.call_count == 1
    assert fetcher.fetch_tpex_margin.call_count == 1


@pytest.mark.unit
def test_run_merges_twse_and_tpex_before_save() -> None:
    fetcher = _stub_fetcher(
        t86={"2330": {"foreign_net": 1}},
        tpex_t86={"3081": {"foreign_net": 2}},
        margin={"2330": {"margin_balance": 100}},
        tpex_margin={"3081": {"margin_balance": 200}},
    )
    storage = _empty_storage()

    run_chips_backfill(
        fetcher=fetcher,
        storage=storage,
        target_start=date(2024, 6, 3),
        today=date(2024, 6, 3),
        sleep_seconds=0,
    )

    saved_t86 = storage.save_t86_snapshot.call_args.args[1]
    assert "2330" in saved_t86 and "3081" in saved_t86
    saved_margin = storage.save_margin_snapshot.call_args.args[1]
    assert "2330" in saved_margin and "3081" in saved_margin


@pytest.mark.unit
def test_run_skips_dates_with_both_snapshots_present() -> None:
    fetcher = _stub_fetcher()
    storage = MagicMock()
    storage.load_t86_day.return_value = {"2330": {}}
    storage.load_margin_day.return_value = {"2330": {}}

    run_chips_backfill(
        fetcher=fetcher,
        storage=storage,
        target_start=date(2024, 6, 3),
        today=date(2024, 6, 3),
        sleep_seconds=0,
    )

    assert fetcher.fetch_t86.call_count == 0
    assert fetcher.fetch_margin.call_count == 0


@pytest.mark.unit
def test_run_skips_weekends() -> None:
    fetcher = _stub_fetcher(t86={"2330": {}}, margin={"2330": {}})
    storage = _empty_storage()

    run_chips_backfill(
        fetcher=fetcher,
        storage=storage,
        target_start=date(2024, 6, 8),  # Sat
        today=date(2024, 6, 9),  # Sun
        sleep_seconds=0,
    )

    assert fetcher.fetch_t86.call_count == 0


@pytest.mark.unit
def test_run_continues_on_endpoint_error() -> None:
    fetcher = _stub_fetcher()
    fetcher.fetch_t86.side_effect = RuntimeError("twse down")
    fetcher.fetch_tpex_t86.return_value = {"3081": {"foreign_net": 9}}
    fetcher.fetch_margin.return_value = {"2330": {"margin_balance": 1}}
    storage = _empty_storage()

    report = run_chips_backfill(
        fetcher=fetcher,
        storage=storage,
        target_start=date(2024, 6, 3),
        today=date(2024, 6, 3),
        sleep_seconds=0,
    )

    # TWSE failure does NOT block TPEX save
    storage.save_t86_snapshot.assert_called_once()
    saved_t86 = storage.save_t86_snapshot.call_args.args[1]
    assert "3081" in saved_t86
    assert isinstance(report, ChipsBackfillReport)


@pytest.mark.unit
def test_run_records_empty_day_when_all_endpoints_return_nothing() -> None:
    fetcher = _stub_fetcher()  # all empty
    storage = _empty_storage()

    report = run_chips_backfill(
        fetcher=fetcher,
        storage=storage,
        target_start=date(2024, 6, 3),
        today=date(2024, 6, 3),
        sleep_seconds=0,
    )

    storage.save_t86_snapshot.assert_not_called()
    storage.save_margin_snapshot.assert_not_called()
    assert date(2024, 6, 3) in report.skipped_empty_days


@pytest.mark.unit
def test_run_respects_sleep_between_requests() -> None:
    fetcher = _stub_fetcher(t86={"2330": {}}, margin={"2330": {}})
    storage = _empty_storage()
    sleep_calls: list[float] = []

    run_chips_backfill(
        fetcher=fetcher,
        storage=storage,
        target_start=date(2024, 6, 3),  # Mon
        today=date(2024, 6, 5),  # Wed → 3 trading days × 4 endpoints = 12 requests
        sleep_seconds=3.0,
        sleep_fn=sleep_calls.append,
    )

    # 12 requests → at least 11 inter-request sleeps
    assert len(sleep_calls) >= 11
    assert all(s == 3.0 for s in sleep_calls)


@pytest.mark.unit
def test_run_report_counts_saved_days() -> None:
    fetcher = _stub_fetcher(t86={"2330": {}}, margin={"2330": {}})
    storage = _empty_storage()

    report = run_chips_backfill(
        fetcher=fetcher,
        storage=storage,
        target_start=date(2024, 6, 3),
        today=date(2024, 6, 4),
        sleep_seconds=0,
    )

    assert report.saved_t86_days == 2
    assert report.saved_margin_days == 2
    assert report.fetched_days == 2
    assert report.failed_days == []
