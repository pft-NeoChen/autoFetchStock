"""TASK-D03b — Cross-stock walk-forward orchestrator (V2 §3.4 / §3.7).

Drives ``BacktestEngine`` across (universe × walk-forward windows). For each
window, slices each stock's feature frame to the OOS date range, runs the
engine independently, then aggregates trades and per-stock equity curves.
Optionally records the run summary to ``ExperimentRegistry``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

import pandas as pd

from src.backtest.engine import BacktestEngine, Trade
from src.backtest.walk_forward import WalkForwardWindow
from src.journal.experiment_registry import ExperimentRegistry

__all__ = [
    "OrchestratorResult",
    "WindowResult",
    "run_walk_forward_backtest",
]


@dataclass
class WindowResult:
    window: WalkForwardWindow
    trades: list[Trade]
    per_stock_equity: dict[str, pd.Series]
    combined_equity: pd.Series


@dataclass
class OrchestratorResult:
    window_results: list[WindowResult]
    all_trades: list[Trade]
    combined_equity: pd.Series
    experiment_id: Optional[str]


def _slice_oos(frame: pd.DataFrame, window: WalkForwardWindow) -> pd.DataFrame:
    if frame.empty:
        return frame
    start = pd.Timestamp(window.oos_start)
    end = pd.Timestamp(window.oos_end)
    mask = (frame.index >= start) & (frame.index <= end)
    return frame.loc[mask]


def _combine_equity(per_stock: dict[str, pd.Series]) -> pd.Series:
    if not per_stock:
        return pd.Series(dtype=float, name="combined_equity")
    df = pd.concat(per_stock.values(), axis=1)
    combined = df.sum(axis=1)
    combined.name = "combined_equity"
    return combined


def run_walk_forward_backtest(
    *,
    universe: list[str],
    feature_frames: Mapping[str, pd.DataFrame],
    windows: list[WalkForwardWindow],
    initial_cash_per_stock: float,
    entry_decider_factory: Callable[[str, pd.DataFrame], Callable],
    exit_decider_factory: Callable[[str, pd.DataFrame], Callable],
    registry: Optional[ExperimentRegistry] = None,
    manifest: Optional[Mapping[str, Any]] = None,
) -> OrchestratorResult:
    window_results: list[WindowResult] = []
    all_trades: list[Trade] = []

    for window in windows:
        trades_in_window: list[Trade] = []
        per_stock_equity: dict[str, pd.Series] = {}

        for stock_id in universe:
            frame = feature_frames.get(stock_id)
            if frame is None or frame.empty:
                continue
            oos_slice = _slice_oos(frame, window)
            if oos_slice.empty:
                continue

            entry_decider = entry_decider_factory(stock_id, oos_slice)
            exit_decider = exit_decider_factory(stock_id, oos_slice)
            engine = BacktestEngine(
                initial_cash=initial_cash_per_stock,
                entry_decider=entry_decider,
                exit_decider=exit_decider,
            )
            result = engine.run(stock_id=stock_id, ohlc_df=oos_slice)
            trades_in_window.extend(result.trades)
            per_stock_equity[stock_id] = result.equity_curve

        window_results.append(
            WindowResult(
                window=window,
                trades=trades_in_window,
                per_stock_equity=per_stock_equity,
                combined_equity=_combine_equity(per_stock_equity),
            )
        )
        all_trades.extend(trades_in_window)

    combined_across_windows = (
        pd.concat([wr.combined_equity for wr in window_results])
        if window_results
        else pd.Series(dtype=float, name="combined_equity")
    )

    experiment_id: Optional[str] = None
    if registry is not None:
        run_manifest = dict(manifest or {})
        run_manifest.setdefault("universe", list(universe))
        run_manifest.setdefault(
            "windows",
            [
                {
                    "oos_start": w.oos_start.isoformat(),
                    "oos_end": w.oos_end.isoformat(),
                }
                for w in windows
            ],
        )
        summary = {
            "trade_count": len(all_trades),
            "n_windows": len(windows),
            "total_pnl": float(sum(t.pnl for t in all_trades)),
        }
        record = registry.record(manifest=run_manifest, summary=summary)
        experiment_id = record.experiment_id

    return OrchestratorResult(
        window_results=window_results,
        all_trades=all_trades,
        combined_equity=combined_across_windows,
        experiment_id=experiment_id,
    )
