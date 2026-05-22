"""TASK-D03c — V2 §6.1 quantitative threshold gating — RED skeleton."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.journal.performance import PerformanceMetrics

__all__ = [
    "DecisionInput",
    "DecisionResult",
    "evaluate_v2_thresholds",
]


@dataclass
class DecisionInput:
    metrics: PerformanceMetrics
    oos_is_ratio: float
    top5_excluded_return: float
    beats_weighted_index: bool
    beats_etf_0050: bool
    oos_alpha: float
    regime_coverage_bull: int
    regime_coverage_bear: int
    regime_coverage_range: int


@dataclass
class DecisionResult:
    passed: bool
    checks: dict[str, bool]
    reasons: list[str] = field(default_factory=list)


def evaluate_v2_thresholds(inp: DecisionInput) -> DecisionResult:
    raise NotImplementedError("TASK-D03c GREEN pending")
