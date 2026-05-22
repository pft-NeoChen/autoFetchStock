"""TASK-D03c — Markdown report renderer — RED skeleton."""

from __future__ import annotations

from typing import Any, Mapping

from src.journal.decision import DecisionResult
from src.journal.performance import PerformanceMetrics

__all__ = ["render_backtest_report"]


def render_backtest_report(
    *,
    metrics: PerformanceMetrics,
    benchmarks_table: Mapping[str, float],
    decision: DecisionResult,
    manifest: Mapping[str, Any],
) -> str:
    raise NotImplementedError("TASK-D03c GREEN pending")
