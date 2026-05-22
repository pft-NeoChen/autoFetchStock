"""TASK-D03b — Cross-stock walk-forward orchestrator.

Drives BacktestEngine across (universe × walk-forward windows), aggregates
trades + equity, and optionally records to ExperimentRegistry.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable, Optional

import pandas as pd
import pytest

from src.backtest.engine import Position
from src.backtest.walk_forward import WalkForwardWindow
from src.backtest.walk_orchestrator import (
    OrchestratorResult,
    WindowResult,
    run_walk_forward_backtest,
)
from src.journal.experiment_registry import ExperimentRegistry


# ── helpers ─────────────────────────────────────────────────────────────────


def _ohlc(closes: list[float], start: str = "2025-01-02") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(closes), freq="B")
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1_000_000] * len(closes),
            "previous_close": [closes[0]] + [closes[i - 1] for i in range(1, len(closes))],
        },
        index=idx,
    )


def _entry_at(target_date: date, shares: int = 1000):
    def factory(stock_id: str, frame: pd.DataFrame):
        def decider(d, row, has_position):
            if has_position:
                return None
            if d == target_date:
                return {"target_shares": shares}
            return None
        return decider
    return factory


def _exit_at(target_date: date, reason: str = "manual"):
    def factory(stock_id: str, frame: pd.DataFrame):
        def decider(d, row, position):
            if d == target_date:
                return reason
            return None
        return decider
    return factory


def _never_entry_factory(stock_id: str, frame: pd.DataFrame):
    def decider(d, row, has_position):
        return None
    return decider


def _never_exit_factory(stock_id: str, frame: pd.DataFrame):
    def decider(d, row, position):
        return None
    return decider


def _full_window(start: str, end: str) -> WalkForwardWindow:
    return WalkForwardWindow(
        is_start=date(2024, 1, 1),
        is_end=date(2024, 12, 31),
        oos_start=pd.Timestamp(start).date(),
        oos_end=pd.Timestamp(end).date(),
    )


# ── 1. engine.run called per stock per window ───────────────────────────────


@pytest.mark.unit
def test_orchestrator_runs_engine_per_stock_per_window() -> None:
    frame_a = _ohlc([100.0, 102.0, 104.0, 106.0, 108.0], start="2025-06-02")
    frame_b = _ohlc([50.0, 51.0, 52.0, 53.0, 54.0], start="2025-06-02")
    window = _full_window("2025-06-02", "2025-06-30")
    calls: list[str] = []

    def entry_factory(stock_id, frame):
        calls.append(f"entry:{stock_id}")
        return _never_entry_factory(stock_id, frame)

    def exit_factory(stock_id, frame):
        calls.append(f"exit:{stock_id}")
        return _never_exit_factory(stock_id, frame)

    result = run_walk_forward_backtest(
        universe=["A", "B"],
        feature_frames={"A": frame_a, "B": frame_b},
        windows=[window],
        initial_cash_per_stock=1_000_000.0,
        entry_decider_factory=entry_factory,
        exit_decider_factory=exit_factory,
    )

    assert isinstance(result, OrchestratorResult)
    assert "entry:A" in calls and "entry:B" in calls
    assert "exit:A" in calls and "exit:B" in calls
    assert len(result.window_results) == 1


# ── 2. feature frame sliced to OOS ──────────────────────────────────────────


@pytest.mark.unit
def test_orchestrator_slices_feature_frame_to_oos_dates() -> None:
    # Frame spans 2025-01-02 ~ 2025-12-31 business days; OOS only mid-year.
    closes = [100.0 + i * 0.1 for i in range(250)]
    frame = _ohlc(closes, start="2025-01-02")
    window = _full_window("2025-06-02", "2025-06-30")
    seen_dates: list[date] = []

    def entry_factory(stock_id, frame_slice):
        def decider(d, row, has_position):
            seen_dates.append(d)
            return None
        return decider

    run_walk_forward_backtest(
        universe=["A"],
        feature_frames={"A": frame},
        windows=[window],
        initial_cash_per_stock=1_000_000.0,
        entry_decider_factory=entry_factory,
        exit_decider_factory=_never_exit_factory,
    )

    assert seen_dates, "decider should be invoked at least once"
    assert min(seen_dates) >= date(2025, 6, 2)
    assert max(seen_dates) <= date(2025, 6, 30)


# ── 3. aggregate trades across stocks ───────────────────────────────────────


@pytest.mark.unit
def test_orchestrator_aggregates_trades_across_stocks() -> None:
    frame_a = _ohlc([100.0, 102.0, 104.0, 106.0, 108.0], start="2025-06-02")
    frame_b = _ohlc([50.0, 51.0, 52.0, 53.0, 54.0], start="2025-06-02")
    window = _full_window("2025-06-02", "2025-06-30")

    result = run_walk_forward_backtest(
        universe=["A", "B"],
        feature_frames={"A": frame_a, "B": frame_b},
        windows=[window],
        initial_cash_per_stock=1_000_000.0,
        entry_decider_factory=_entry_at(date(2025, 6, 2)),
        exit_decider_factory=_exit_at(date(2025, 6, 4)),
    )

    stock_ids = {t.stock_id for t in result.all_trades}
    assert stock_ids == {"A", "B"}
    assert len(result.all_trades) == 2


# ── 4. empty OOS slice → skip without crash ─────────────────────────────────


@pytest.mark.unit
def test_orchestrator_skips_stock_with_empty_oos_data() -> None:
    # Frame ends before OOS window.
    frame = _ohlc([100.0, 101.0, 102.0], start="2025-01-02")
    window = _full_window("2025-06-02", "2025-06-30")

    result = run_walk_forward_backtest(
        universe=["A"],
        feature_frames={"A": frame},
        windows=[window],
        initial_cash_per_stock=1_000_000.0,
        entry_decider_factory=_entry_at(date(2025, 6, 2)),
        exit_decider_factory=_exit_at(date(2025, 6, 4)),
    )

    assert result.all_trades == []
    assert len(result.window_results) == 1


# ── 5. combined equity = sum of per-stock equity ────────────────────────────


@pytest.mark.unit
def test_orchestrator_combined_equity_sums_per_stock() -> None:
    frame_a = _ohlc([100.0, 100.0, 100.0], start="2025-06-02")
    frame_b = _ohlc([50.0, 50.0, 50.0], start="2025-06-02")
    window = _full_window("2025-06-02", "2025-06-30")

    result = run_walk_forward_backtest(
        universe=["A", "B"],
        feature_frames={"A": frame_a, "B": frame_b},
        windows=[window],
        initial_cash_per_stock=500_000.0,
        entry_decider_factory=_never_entry_factory,
        exit_decider_factory=_never_exit_factory,
    )

    # Two stocks × 500k initial each, no trades → combined ≈ 1_000_000 throughout
    combined = result.window_results[0].combined_equity
    assert not combined.empty
    assert combined.iloc[0] == pytest.approx(1_000_000.0)
    assert combined.iloc[-1] == pytest.approx(1_000_000.0)


# ── 6. registry record ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_orchestrator_records_to_registry_when_provided(tmp_path: Path) -> None:
    frame = _ohlc([100.0, 101.0, 102.0], start="2025-06-02")
    window = _full_window("2025-06-02", "2025-06-30")
    registry = ExperimentRegistry(tmp_path / "registry")

    result = run_walk_forward_backtest(
        universe=["A"],
        feature_frames={"A": frame},
        windows=[window],
        initial_cash_per_stock=1_000_000.0,
        entry_decider_factory=_never_entry_factory,
        exit_decider_factory=_never_exit_factory,
        registry=registry,
        manifest={"strategy": "long_entry_v1", "universe_size": 1},
    )

    assert result.experiment_id is not None
    record = registry.lookup(result.experiment_id)
    assert record is not None
    assert record.manifest["strategy"] == "long_entry_v1"
    assert "trade_count" in record.summary or "n_trades" in record.summary


# ── 7. no registry → experiment_id is None ──────────────────────────────────


@pytest.mark.unit
def test_orchestrator_skips_registry_when_none() -> None:
    frame = _ohlc([100.0, 101.0, 102.0], start="2025-06-02")
    window = _full_window("2025-06-02", "2025-06-30")

    result = run_walk_forward_backtest(
        universe=["A"],
        feature_frames={"A": frame},
        windows=[window],
        initial_cash_per_stock=1_000_000.0,
        entry_decider_factory=_never_entry_factory,
        exit_decider_factory=_never_exit_factory,
    )

    assert result.experiment_id is None


# ── 8. window result fields ─────────────────────────────────────────────────


@pytest.mark.unit
def test_orchestrator_window_result_carries_window_and_trades() -> None:
    frame = _ohlc([100.0, 102.0, 104.0, 106.0], start="2025-06-02")
    window = _full_window("2025-06-02", "2025-06-30")

    result = run_walk_forward_backtest(
        universe=["A"],
        feature_frames={"A": frame},
        windows=[window],
        initial_cash_per_stock=1_000_000.0,
        entry_decider_factory=_entry_at(date(2025, 6, 2)),
        exit_decider_factory=_exit_at(date(2025, 6, 4)),
    )

    wr = result.window_results[0]
    assert isinstance(wr, WindowResult)
    assert wr.window == window
    assert len(wr.trades) == 1
    assert wr.trades[0].stock_id == "A"


# ── 9. multiple windows produce multiple window_results ─────────────────────


@pytest.mark.unit
def test_orchestrator_handles_multiple_windows() -> None:
    closes = [100.0 + i * 0.1 for i in range(180)]
    frame = _ohlc(closes, start="2025-01-02")
    w1 = _full_window("2025-03-03", "2025-03-31")
    w2 = _full_window("2025-06-02", "2025-06-30")

    result = run_walk_forward_backtest(
        universe=["A"],
        feature_frames={"A": frame},
        windows=[w1, w2],
        initial_cash_per_stock=1_000_000.0,
        entry_decider_factory=_never_entry_factory,
        exit_decider_factory=_never_exit_factory,
    )

    assert len(result.window_results) == 2
    assert result.window_results[0].window == w1
    assert result.window_results[1].window == w2
