"""TASK-D03b — Cross-stock walk-forward orchestrator (skeleton).

GREEN implementation TBD. RED stage exposes the names so tests collect.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

import pandas as pd

from src.backtest.engine import Trade
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
    raise NotImplementedError("TASK-D03b GREEN stage pending")
