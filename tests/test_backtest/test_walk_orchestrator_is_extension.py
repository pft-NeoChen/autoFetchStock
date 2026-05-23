"""TASK-D03e — Walk-forward orchestrator IS extension (V2 §6.1 caveats #4).

Adds IS-pass support to run_walk_forward_backtest so we can compute
oos_is_ratio for the decision evaluator. New behaviour is gated behind
``include_is=True`` to preserve existing OOS-only orchestrator tests.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.backtest.walk_forward import WalkForwardWindow
from src.backtest.walk_orchestrator import (
    OrchestratorResult,
    WindowResult,
    compute_oos_is_ratio_from_result,
    run_walk_forward_backtest,
)


def _make_frame(start: date, n_days: int, close_start: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range(start=start, periods=n_days, freq="B")
    return pd.DataFrame(
        {
            "open": [close_start + i * 0.1 for i in range(n_days)],
            "high": [close_start + i * 0.1 + 0.5 for i in range(n_days)],
            "low": [close_start + i * 0.1 - 0.5 for i in range(n_days)],
            "close": [close_start + i * 0.1 for i in range(n_days)],
            "volume": [1_000_000] * n_days,
        },
        index=idx,
    )


def _noop_decider_factory(_stock: str, _frame: pd.DataFrame):
    return MagicMock(return_value=None)


# ---- include_is default behaviour ----

@pytest.mark.unit
def test_default_include_is_false_keeps_is_fields_empty() -> None:
    frame = _make_frame(date(2024, 1, 1), 120)
    window = WalkForwardWindow(
        is_start=date(2024, 1, 1),
        is_end=date(2024, 3, 1),
        oos_start=date(2024, 3, 15),
        oos_end=date(2024, 5, 1),
    )

    result = run_walk_forward_backtest(
        universe=["2330"],
        feature_frames={"2330": frame},
        windows=[window],
        initial_cash_per_stock=100_000,
        entry_decider_factory=_noop_decider_factory,
        exit_decider_factory=_noop_decider_factory,
    )

    assert result.is_all_trades == []
    assert result.is_combined_equity.empty
    assert result.window_results[0].is_trades == []
    assert result.window_results[0].is_combined_equity.empty


# ---- include_is=True ----

@pytest.mark.unit
def test_include_is_runs_engine_on_is_slice(monkeypatch) -> None:
    frame = _make_frame(date(2024, 1, 1), 250)
    window = WalkForwardWindow(
        is_start=date(2024, 1, 1),
        is_end=date(2024, 4, 1),
        oos_start=date(2024, 4, 15),
        oos_end=date(2024, 6, 1),
    )

    seen_slices: list[pd.DataFrame] = []

    class _RecordingEngine:
        def __init__(self, *, initial_cash, entry_decider, exit_decider):
            self.initial_cash = initial_cash

        def run(self, *, stock_id, ohlc_df):
            seen_slices.append(ohlc_df)
            from src.backtest.engine import BacktestResult

            equity = pd.Series([self.initial_cash] * len(ohlc_df), index=ohlc_df.index)
            return BacktestResult(
                trades=[],
                equity_curve=equity,
                cash_curve=equity.copy(),
                final_equity=float(self.initial_cash),
                final_cash=float(self.initial_cash),
            )

    monkeypatch.setattr("src.backtest.walk_orchestrator.BacktestEngine", _RecordingEngine)

    run_walk_forward_backtest(
        universe=["2330"],
        feature_frames={"2330": frame},
        windows=[window],
        initial_cash_per_stock=100_000,
        entry_decider_factory=_noop_decider_factory,
        exit_decider_factory=_noop_decider_factory,
        include_is=True,
    )

    # Two engine.run calls — one IS, one OOS — with disjoint date ranges
    assert len(seen_slices) == 2
    spans = [(s.index.min().date(), s.index.max().date()) for s in seen_slices]
    has_is = any(
        s_min >= window.is_start and s_max <= window.is_end for s_min, s_max in spans
    )
    has_oos = any(
        s_min >= window.oos_start and s_max <= window.oos_end for s_min, s_max in spans
    )
    assert has_is and has_oos


@pytest.mark.unit
def test_include_is_populates_aggregate_fields(monkeypatch) -> None:
    frame = _make_frame(date(2024, 1, 1), 250)
    window = WalkForwardWindow(
        is_start=date(2024, 1, 1),
        is_end=date(2024, 4, 1),
        oos_start=date(2024, 4, 15),
        oos_end=date(2024, 6, 1),
    )

    from src.backtest.engine import BacktestResult, Trade

    fake_trade = Trade(
        stock_id="2330",
        entry_date=date(2024, 1, 6),
        entry_price=100.0,
        exit_date=date(2024, 1, 12),
        exit_price=101.0,
        shares=1000,
        pnl=500.0,
        pnl_pct=0.01,
        fees=100.0,
        tax=30.0,
        reason="time_stop",
    )

    class _StubEngine:
        def __init__(self, *, initial_cash, entry_decider, exit_decider):
            self.initial_cash = initial_cash

        def run(self, *, stock_id, ohlc_df):
            equity = pd.Series([float(self.initial_cash)] * len(ohlc_df), index=ohlc_df.index)
            return BacktestResult(
                trades=[fake_trade],
                equity_curve=equity,
                cash_curve=equity.copy(),
                final_equity=float(self.initial_cash),
                final_cash=float(self.initial_cash),
            )

    monkeypatch.setattr("src.backtest.walk_orchestrator.BacktestEngine", _StubEngine)

    result = run_walk_forward_backtest(
        universe=["2330"],
        feature_frames={"2330": frame},
        windows=[window],
        initial_cash_per_stock=100_000,
        entry_decider_factory=_noop_decider_factory,
        exit_decider_factory=_noop_decider_factory,
        include_is=True,
    )

    assert len(result.all_trades) == 1  # OOS
    assert len(result.is_all_trades) == 1  # IS
    assert not result.is_combined_equity.empty
    assert result.window_results[0].is_trades == [fake_trade]


@pytest.mark.unit
def test_include_is_does_not_pollute_oos_trades(monkeypatch) -> None:
    """Regression: include_is=True must not add IS trades to all_trades."""
    frame = _make_frame(date(2024, 1, 1), 250)
    window = WalkForwardWindow(
        is_start=date(2024, 1, 1),
        is_end=date(2024, 4, 1),
        oos_start=date(2024, 4, 15),
        oos_end=date(2024, 6, 1),
    )

    from src.backtest.engine import BacktestResult, Trade

    counter = {"n": 0}

    def _stub_run(self, *, stock_id, ohlc_df):  # noqa: ANN001
        counter["n"] += 1
        trade = Trade(
            stock_id=stock_id,
            entry_date=ohlc_df.index[0].date(),
            entry_price=100.0,
            exit_date=ohlc_df.index[-1].date(),
            exit_price=101.0,
            shares=1000,
            pnl=float(counter["n"]),
            pnl_pct=0.01,
            fees=100.0,
            tax=30.0,
            reason="time_stop",
        )
        equity = pd.Series([100_000.0] * len(ohlc_df), index=ohlc_df.index)
        return BacktestResult(
            trades=[trade],
            equity_curve=equity,
            cash_curve=equity.copy(),
            final_equity=100_000.0,
            final_cash=100_000.0,
        )

    from src.backtest import engine as engine_mod
    monkeypatch.setattr(engine_mod.BacktestEngine, "run", _stub_run)

    result = run_walk_forward_backtest(
        universe=["2330"],
        feature_frames={"2330": frame},
        windows=[window],
        initial_cash_per_stock=100_000,
        entry_decider_factory=_noop_decider_factory,
        exit_decider_factory=_noop_decider_factory,
        include_is=True,
    )

    # OOS trades exclusive; IS trades exclusive — never crossed
    oos_pnls = {t.pnl for t in result.all_trades}
    is_pnls = {t.pnl for t in result.is_all_trades}
    assert oos_pnls.isdisjoint(is_pnls)


# ---- compute_oos_is_ratio_from_result ----

@pytest.mark.unit
def test_oos_is_ratio_helper_returns_ratio_of_total_returns() -> None:
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    oos = pd.Series([100.0, 110.0, 120.0], index=idx)  # +20%
    is_ = pd.Series([100.0, 105.0, 110.0], index=idx)  # +10%
    result = OrchestratorResult(
        window_results=[],
        all_trades=[],
        combined_equity=oos,
        experiment_id=None,
        is_all_trades=[],
        is_combined_equity=is_,
    )
    assert compute_oos_is_ratio_from_result(result) == pytest.approx(2.0)


@pytest.mark.unit
def test_oos_is_ratio_helper_handles_zero_is_return() -> None:
    idx = pd.date_range("2024-01-01", periods=2, freq="B")
    oos = pd.Series([100.0, 110.0], index=idx)
    is_ = pd.Series([100.0, 100.0], index=idx)  # 0%
    result = OrchestratorResult(
        window_results=[],
        all_trades=[],
        combined_equity=oos,
        experiment_id=None,
        is_all_trades=[],
        is_combined_equity=is_,
    )
    assert compute_oos_is_ratio_from_result(result) == 0.0


@pytest.mark.unit
def test_oos_is_ratio_helper_returns_zero_when_either_curve_empty() -> None:
    idx = pd.date_range("2024-01-01", periods=2, freq="B")
    result = OrchestratorResult(
        window_results=[],
        all_trades=[],
        combined_equity=pd.Series([100.0, 110.0], index=idx),
        experiment_id=None,
        is_all_trades=[],
        is_combined_equity=pd.Series(dtype=float),
    )
    assert compute_oos_is_ratio_from_result(result) == 0.0
