"""TASK-S3-BACKFILL — Resumable wide-universe OHLC backfill."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.backfill_wide_universe import (
    WideBackfillState,
    load_state,
    run_wide_backfill,
    save_state,
    select_wide_universe,
)


pytestmark = pytest.mark.unit


def _write_sector_map(path: Path, mapping: dict[str, str]) -> None:
    path.write_text(json.dumps(mapping, ensure_ascii=False))


def _stub_stock_file(stocks_dir: Path, stock_id: str) -> None:
    (stocks_dir / f"{stock_id}.json").write_text(
        json.dumps({"stock_id": stock_id, "daily_data": []})
    )


# ── select_wide_universe ─────────────────────────────────────────────────────


def test_select_wide_universe_excludes_already_local_and_non_stocks(tmp_path: Path) -> None:
    sector_map = tmp_path / "sector_map.json"
    _write_sector_map(
        sector_map,
        {
            "1101": "水泥工業",
            "2330": "半導體業",
            "2454": "半導體業",
            "1234": "食品工業",
        },
    )
    stocks_dir = tmp_path / "stocks"
    stocks_dir.mkdir()
    _stub_stock_file(stocks_dir, "1101")  # already local → skip
    _stub_stock_file(stocks_dir, "2330")  # already local → skip
    data_dir = tmp_path

    targets = select_wide_universe(
        sector_map_path=sector_map,
        data_dir=data_dir,
        exclude=("0050", "9110"),
    )

    assert set(targets) == {"1234", "2454"}
    assert targets == sorted(targets)


def test_select_wide_universe_explicit_exclude_skips_etf(tmp_path: Path) -> None:
    sector_map = tmp_path / "sector_map.json"
    _write_sector_map(sector_map, {"0050": "ETF", "2330": "半導體業"})
    stocks_dir = tmp_path / "stocks"
    stocks_dir.mkdir()
    data_dir = tmp_path

    targets = select_wide_universe(
        sector_map_path=sector_map,
        data_dir=data_dir,
        exclude=("0050",),
    )

    assert targets == ["2330"]


# ── WideBackfillState round-trip ─────────────────────────────────────────────


def test_wide_backfill_state_round_trip(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state = WideBackfillState(
        started_at="2026-05-25T10:00:00",
        last_update="2026-05-25T10:05:00",
        stock_ids=["1234", "2454", "3008"],
        completed={"1234": "ok", "2454": "failed"},
        current="3008",
        errors={"2454": "timeout"},
    )

    save_state(state_path, state)
    loaded = load_state(state_path)

    assert loaded is not None
    assert loaded.stock_ids == ["1234", "2454", "3008"]
    assert loaded.completed == {"1234": "ok", "2454": "failed"}
    assert loaded.current == "3008"
    assert loaded.errors == {"2454": "timeout"}


def test_load_state_returns_none_when_missing(tmp_path: Path) -> None:
    assert load_state(tmp_path / "missing.json") is None


# ── run_wide_backfill ────────────────────────────────────────────────────────


class _StubFetcher:
    def __init__(self, fail_for: set[str] | None = None) -> None:
        self.fail_for = fail_for or set()
        self.calls: list[tuple[str, int, int]] = []

    def fetch_daily_history(self, stock_id: str, year: int, month: int):
        self.calls.append((stock_id, year, month))
        if stock_id in self.fail_for:
            raise RuntimeError(f"simulated failure for {stock_id}")
        # Return a minimal record (real fetcher returns list of DailyOHLC; we use dicts).
        return [{"date": date(year, month, 15), "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1000}]


class _StubStorage:
    def __init__(self) -> None:
        self.saved: dict[str, list] = {}

    def load_daily_data(self, stock_id: str):
        return None

    def save_daily_data(self, stock_id: str, stock_name: str, records) -> bool:
        self.saved.setdefault(stock_id, []).extend(records)
        return True


def test_run_wide_backfill_processes_pending_stocks_and_persists_state(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    fetcher = _StubFetcher()
    storage = _StubStorage()

    state = run_wide_backfill(
        fetcher=fetcher,
        storage=storage,
        stock_ids=["1234", "2454"],
        state_path=state_path,
        target_start=date(2026, 4, 1),
        today=date(2026, 5, 1),
        sleep_seconds=0,
    )

    assert set(state.completed) == {"1234", "2454"}
    assert state.completed["1234"] == "ok"
    assert state.completed["2454"] == "ok"
    assert state.current is None
    loaded = load_state(state_path)
    assert loaded is not None
    assert loaded.completed == state.completed


def test_run_wide_backfill_resume_skips_completed_stocks(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    # Pre-existing state where stock "1234" already ok
    pre = WideBackfillState(
        started_at="2026-05-25T09:00:00",
        last_update="2026-05-25T09:05:00",
        stock_ids=["1234", "2454"],
        completed={"1234": "ok"},
        current=None,
        errors={},
    )
    save_state(state_path, pre)

    fetcher = _StubFetcher()
    storage = _StubStorage()

    state = run_wide_backfill(
        fetcher=fetcher,
        storage=storage,
        stock_ids=["1234", "2454"],
        state_path=state_path,
        target_start=date(2026, 4, 1),
        today=date(2026, 5, 1),
        sleep_seconds=0,
        resume=True,
    )

    # 1234 should be skipped (no fetch calls for it)
    assert "1234" not in {sid for sid, _, _ in fetcher.calls}
    # 2454 should be processed
    assert state.completed["2454"] == "ok"


def test_run_wide_backfill_records_failed_stock_but_continues(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    fetcher = _StubFetcher(fail_for={"2454"})
    storage = _StubStorage()

    state = run_wide_backfill(
        fetcher=fetcher,
        storage=storage,
        stock_ids=["1234", "2454", "3008"],
        state_path=state_path,
        target_start=date(2026, 4, 1),
        today=date(2026, 5, 1),
        sleep_seconds=0,
    )

    assert state.completed["1234"] == "ok"
    assert state.completed["2454"] == "failed"
    assert state.completed["3008"] == "ok"
    assert "2454" in state.errors


def test_run_wide_backfill_persists_state_after_each_stock(tmp_path: Path) -> None:
    """Per-stock flush so SIGINT mid-run still leaves recoverable state."""
    state_path = tmp_path / "state.json"
    fetcher = _StubFetcher()
    storage = _StubStorage()

    flush_history: list[set[str]] = []

    original_save = save_state

    def spy_save(path, state):
        flush_history.append(set(state.completed))
        original_save(path, state)

    import scripts.backfill_wide_universe as mod

    mod.save_state = spy_save  # type: ignore[assignment]
    try:
        run_wide_backfill(
            fetcher=fetcher,
            storage=storage,
            stock_ids=["1234", "2454"],
            state_path=state_path,
            target_start=date(2026, 4, 1),
            today=date(2026, 5, 1),
            sleep_seconds=0,
        )
    finally:
        mod.save_state = original_save  # type: ignore[assignment]

    # At least one flush after "1234" was marked but before "2454" finished.
    assert any(snapshot == {"1234"} for snapshot in flush_history)
    # And a final flush with both done.
    assert any({"1234", "2454"} <= snapshot for snapshot in flush_history)
