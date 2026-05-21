"""TASK-D01 RED tests: audit_local_data."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from scripts.audit_local_data import (
    audit_local_data,
    render_markdown_report,
)


pytestmark = pytest.mark.unit


def _write_daily(data_root: Path, stock_id: str, name: str, dates: list[date]) -> None:
    p = data_root / "stocks" / f"{stock_id}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stock_id": stock_id,
        "stock_name": name,
        "last_updated": datetime.now().isoformat(),
        "daily_data": [
            {
                "date": d.isoformat(),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1000,
                "turnover": 100500.0,
                "timestamp": d.isoformat() + "T13:30:00",
            }
            for d in dates
        ],
    }
    p.write_text(json.dumps(payload), encoding="utf-8")


def _write_intraday(data_root: Path, stock_id: str, name: str, day: date, n_ticks: int = 3) -> None:
    p = data_root / "intraday" / f"{stock_id}_{day.strftime('%Y%m%d')}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stock_id": stock_id,
        "stock_name": name,
        "date": day.isoformat(),
        "previous_close": 100.0,
        "ticks": [
            {
                "time": f"09:0{i}:00",
                "price": 100.0 + i * 0.1,
                "volume": 100,
                "buy_volume": 0,
                "sell_volume": 0,
                "accumulated_volume": 100 * (i + 1),
                "timestamp": f"{day.isoformat()}T09:0{i}:00",
            }
            for i in range(n_ticks)
        ],
    }
    p.write_text(json.dumps(payload), encoding="utf-8")


def _write_minute_kbar(data_root: Path, stock_id: str, name: str, day: date, n_bars: int = 4) -> None:
    p = data_root / "minute_kbars" / f"{stock_id}_{day.strftime('%Y%m%d')}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stock_id": stock_id,
        "stock_name": name,
        "date": day.isoformat(),
        "bars": [
            {
                "stock_id": stock_id,
                "timestamp": f"{day.isoformat()}T09:0{i}:00+08:00",
                "open": 100.0,
                "high": 100.5,
                "low": 99.5,
                "close": 100.2,
                "volume": 500,
                "amount": 50100.0,
                "tick_count": 10,
                "vwap": 100.1,
                "baseline_volume": None,
                "volume_severity": None,
            }
            for i in range(n_bars)
        ],
    }
    p.write_text(json.dumps(payload), encoding="utf-8")


# --------------------------------------------------------------------- TESTS


def test_audit_returns_per_stock_coverage(tmp_path: Path) -> None:
    """Every stock found on disk gets first_date / last_date / record_count for each data kind."""
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(5)]
    _write_daily(tmp_path, "2330", "台積電", dates)
    _write_intraday(tmp_path, "2330", "台積電", date(2024, 1, 5), n_ticks=3)

    report = audit_local_data(tmp_path)

    assert "2330" in report
    cov = report["2330"]
    assert cov.stock_id == "2330"
    assert cov.daily is not None
    assert cov.daily.first_date == date(2024, 1, 1)
    assert cov.daily.last_date == date(2024, 1, 5)
    assert cov.daily.record_count == 5
    assert cov.intraday is not None
    assert cov.intraday.record_count == 3
    assert cov.intraday.first_date == date(2024, 1, 5)
    assert cov.intraday.last_date == date(2024, 1, 5)


def test_audit_flags_incomplete_stocks(tmp_path: Path) -> None:
    """Stock with < 2 years of daily data must NOT be marked backtest_ready; >= 2 years must be."""
    short_dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(30)]
    _write_daily(tmp_path, "9999", "短檔", short_dates)

    long_dates = [date(2022, 1, 1) + timedelta(days=i * 5) for i in range(200)]
    _write_daily(tmp_path, "2330", "台積電", long_dates)

    report = audit_local_data(tmp_path)

    assert report["9999"].backtest_ready is False
    assert report["2330"].backtest_ready is True


def test_audit_separates_daily_and_minute(tmp_path: Path) -> None:
    """Daily, intraday, and minute_kbar are counted as independent coverage records."""
    _write_daily(tmp_path, "2330", "台積電", [date(2024, 1, 1)])
    _write_intraday(tmp_path, "2330", "台積電", date(2024, 6, 1), n_ticks=2)
    _write_minute_kbar(tmp_path, "2330", "台積電", date(2024, 6, 1), n_bars=4)
    _write_minute_kbar(tmp_path, "2330", "台積電", date(2024, 6, 2), n_bars=5)

    report = audit_local_data(tmp_path)
    cov = report["2330"]

    assert cov.daily is not None and cov.daily.record_count == 1
    assert cov.intraday is not None and cov.intraday.record_count == 2
    assert cov.minute_kbar is not None
    assert cov.minute_kbar.record_count == 9  # 4 + 5 bars
    assert cov.minute_kbar.first_date == date(2024, 6, 1)
    assert cov.minute_kbar.last_date == date(2024, 6, 2)


def test_render_markdown_report_includes_sections(tmp_path: Path) -> None:
    """Bonus smoke test on markdown renderer; keeps RED list tight but proves API surface."""
    _write_daily(tmp_path, "2330", "台積電", [date(2024, 1, 1) + timedelta(days=i) for i in range(3)])
    report = audit_local_data(tmp_path)
    md = render_markdown_report(report)
    assert "2330" in md
    assert "daily" in md.lower()
