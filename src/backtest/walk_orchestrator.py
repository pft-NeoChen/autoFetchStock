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
    "compute_oos_is_ratio_from_result",
    "run_walk_forward_backtest",
]


def _empty_equity(name: str) -> pd.Series:
    return pd.Series(dtype=float, name=name)


@dataclass
class WindowResult:
    window: WalkForwardWindow
    trades: list[Trade]
    per_stock_equity: dict[str, pd.Series]
    combined_equity: pd.Series
    is_trades: list[Trade] = field(default_factory=list)
    is_per_stock_equity: dict[str, pd.Series] = field(default_factory=dict)
    is_combined_equity: pd.Series = field(
        default_factory=lambda: _empty_equity("is_combined_equity")
    )


@dataclass
class OrchestratorResult:
    window_results: list[WindowResult]
    all_trades: list[Trade]
    combined_equity: pd.Series
    experiment_id: Optional[str]
    is_all_trades: list[Trade] = field(default_factory=list)
    is_combined_equity: pd.Series = field(
        default_factory=lambda: _empty_equity("is_combined_equity")
    )


def _slice_range(frame: pd.DataFrame, start, end) -> pd.DataFrame:
    if frame.empty:
        return frame
    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)
    mask = (frame.index >= ts_start) & (frame.index <= ts_end)
    return frame.loc[mask]


def _slice_oos(frame: pd.DataFrame, window: WalkForwardWindow) -> pd.DataFrame:
    return _slice_range(frame, window.oos_start, window.oos_end)


def _slice_is(frame: pd.DataFrame, window: WalkForwardWindow) -> pd.DataFrame:
    return _slice_range(frame, window.is_start, window.is_end)


def _combine_equity(per_stock: dict[str, pd.Series]) -> pd.Series:
    if not per_stock:
        return pd.Series(dtype=float, name="combined_equity")
    df = pd.concat(per_stock.values(), axis=1)
    combined = df.sum(axis=1)
    combined.name = "combined_equity"
    return combined


def _pad_per_stock_equity(
    *,
    per_stock: dict[str, pd.Series],
    universe: list[str],
    date_index: pd.DatetimeIndex,
    initial_cash: float,
) -> pd.DataFrame:
    """Return DataFrame indexed by ``date_index`` with one column per
    ``universe`` stock. Active stocks are reindexed and forward-filled
    from their final known equity; inactive stocks get a flat
    ``initial_cash`` baseline so the universe-wide combined equity has
    no artificial dips on dates where some stocks haven't traded yet.
    """
    cols: dict[str, pd.Series] = {}
    for sid in universe:
        eq = per_stock.get(sid)
        if eq is None or eq.empty:
            cols[sid] = pd.Series(initial_cash, index=date_index, name=sid)
            continue
        reindexed = eq.reindex(date_index)
        # Forward-fill after last known; back-fill at the start with initial_cash.
        reindexed = reindexed.ffill().fillna(initial_cash)
        reindexed.name = sid
        cols[sid] = reindexed
    return pd.DataFrame(cols)


def _chain_window_equities_dollar(segments: list[pd.Series]) -> pd.Series:
    """Concatenate window-level equity curves, shifting each successive
    segment so it starts where the previous one ended. Preserves dollar
    scale and removes the boundary jump caused by each window's engine
    resetting to initial cash.
    """
    nonempty = [s for s in segments if not s.empty]
    if not nonempty:
        return pd.Series(dtype=float, name="combined_equity")

    out: list[pd.Series] = [nonempty[0]]
    offset = float(nonempty[0].iloc[-1])
    for seg in nonempty[1:]:
        shift = offset - float(seg.iloc[0])
        shifted = seg + shift
        out.append(shifted)
        offset = float(shifted.iloc[-1])
    chained = pd.concat(out)
    chained.name = "combined_equity"
    return chained


def _run_slice(
    *,
    universe: list[str],
    feature_frames: Mapping[str, pd.DataFrame],
    slicer: Callable[[pd.DataFrame], pd.DataFrame],
    initial_cash_per_stock: float,
    entry_decider_factory: Callable[[str, pd.DataFrame], Callable],
    exit_decider_factory: Callable[[str, pd.DataFrame], Callable],
) -> tuple[list[Trade], dict[str, pd.Series]]:
    trades: list[Trade] = []
    per_stock_equity: dict[str, pd.Series] = {}
    for stock_id in universe:
        frame = feature_frames.get(stock_id)
        if frame is None or frame.empty:
            continue
        sliced = slicer(frame)
        if sliced.empty:
            continue
        entry_decider = entry_decider_factory(stock_id, sliced)
        exit_decider = exit_decider_factory(stock_id, sliced)
        engine = BacktestEngine(
            initial_cash=initial_cash_per_stock,
            entry_decider=entry_decider,
            exit_decider=exit_decider,
        )
        result = engine.run(stock_id=stock_id, ohlc_df=sliced)
        trades.extend(result.trades)
        per_stock_equity[stock_id] = result.equity_curve
    return trades, per_stock_equity


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
    include_is: bool = False,
) -> OrchestratorResult:
    window_results: list[WindowResult] = []
    all_trades: list[Trade] = []
    is_all_trades: list[Trade] = []

    def _padded_combined(
        per_stock: dict[str, pd.Series], slice_fn
    ) -> pd.Series:
        if per_stock:
            date_index = pd.concat(per_stock.values(), axis=1).index.sort_values()
        else:
            date_index = pd.DatetimeIndex([])
            for f in feature_frames.values():
                sliced_idx = slice_fn(f).index
                if not sliced_idx.empty:
                    date_index = sliced_idx
                    break
        if date_index.empty:
            return _empty_equity("combined_equity")
        padded = _pad_per_stock_equity(
            per_stock=per_stock,
            universe=universe,
            date_index=date_index,
            initial_cash=initial_cash_per_stock,
        )
        combined = padded.sum(axis=1)
        combined.name = "combined_equity"
        return combined

    for window in windows:
        oos_trades, oos_equity = _run_slice(
            universe=universe,
            feature_frames=feature_frames,
            slicer=lambda f, w=window: _slice_oos(f, w),
            initial_cash_per_stock=initial_cash_per_stock,
            entry_decider_factory=entry_decider_factory,
            exit_decider_factory=exit_decider_factory,
        )

        is_trades: list[Trade] = []
        is_equity: dict[str, pd.Series] = {}
        if include_is:
            is_trades, is_equity = _run_slice(
                universe=universe,
                feature_frames=feature_frames,
                slicer=lambda f, w=window: _slice_is(f, w),
                initial_cash_per_stock=initial_cash_per_stock,
                entry_decider_factory=entry_decider_factory,
                exit_decider_factory=exit_decider_factory,
            )
            is_combined = _padded_combined(
                is_equity, lambda f, w=window: _slice_is(f, w)
            )
            is_combined.name = "is_combined_equity"
        else:
            is_combined = _empty_equity("is_combined_equity")

        window_results.append(
            WindowResult(
                window=window,
                trades=oos_trades,
                per_stock_equity=oos_equity,
                combined_equity=_padded_combined(
                    oos_equity, lambda f, w=window: _slice_oos(f, w)
                ),
                is_trades=is_trades,
                is_per_stock_equity=is_equity,
                is_combined_equity=is_combined,
            )
        )
        all_trades.extend(oos_trades)
        is_all_trades.extend(is_trades)

    combined_across_windows = _chain_window_equities_dollar(
        [wr.combined_equity for wr in window_results]
    )
    if include_is and window_results:
        is_combined_across = _chain_window_equities_dollar(
            [wr.is_combined_equity for wr in window_results]
        )
        is_combined_across.name = "is_combined_equity"
    else:
        is_combined_across = _empty_equity("is_combined_equity")

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
        if include_is:
            summary["is_trade_count"] = len(is_all_trades)
            summary["is_total_pnl"] = float(sum(t.pnl for t in is_all_trades))
        record = registry.record(manifest=run_manifest, summary=summary)
        experiment_id = record.experiment_id

    return OrchestratorResult(
        window_results=window_results,
        all_trades=all_trades,
        combined_equity=combined_across_windows,
        experiment_id=experiment_id,
        is_all_trades=is_all_trades,
        is_combined_equity=is_combined_across,
    )


def compute_oos_is_ratio_from_result(result: OrchestratorResult) -> float:
    """OOS/IS total-return ratio. Returns 0.0 when either curve is empty or
    the IS return is 0.
    """
    from src.journal.performance import oos_is_ratio, total_return

    if result.combined_equity.empty or result.is_combined_equity.empty:
        return 0.0
    oos_ret = total_return(result.combined_equity)
    is_ret = total_return(result.is_combined_equity)
    return oos_is_ratio(oos_return=oos_ret, is_return=is_ret)
