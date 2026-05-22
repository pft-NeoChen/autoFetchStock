"""TASK-D03c — Markdown report renderer."""

from __future__ import annotations

import pytest

from src.journal.backtest_report import render_backtest_report
from src.journal.decision import DecisionInput, DecisionResult, evaluate_v2_thresholds
from src.journal.performance import PerformanceMetrics


def _metrics(**overrides) -> PerformanceMetrics:
    base = dict(
        n_trades=80,
        total_return=0.15,
        sharpe=1.2,
        sortino=1.5,
        max_drawdown=0.15,
        win_rate=0.55,
        profit_factor=1.6,
        expectancy_bp=8.0,
        turnover=2.5,
    )
    base.update(overrides)
    return PerformanceMetrics(**base)


def _decision(passed: bool = True) -> DecisionResult:
    inp = DecisionInput(
        metrics=_metrics() if passed else _metrics(expectancy_bp=2.0),
        oos_is_ratio=0.85,
        top5_excluded_return=0.05,
        beats_weighted_index=True,
        beats_etf_0050=True,
        oos_alpha=0.04,
        regime_coverage_bull=1,
        regime_coverage_bear=1,
        regime_coverage_range=1,
    )
    return evaluate_v2_thresholds(inp)


@pytest.mark.unit
def test_report_contains_required_sections() -> None:
    md = render_backtest_report(
        metrics=_metrics(),
        benchmarks_table={"weighted_index": 0.08, "etf_0050": 0.07,
                          "equal_weight": 0.06, "ma_strategy": 0.04, "cash": 0.0},
        decision=_decision(passed=True),
        manifest={"strategy": "long_entry_v1", "universe_size": 38},
    )
    assert "# Backtest Report" in md
    assert "## Performance Metrics" in md
    assert "## Benchmark 對照" in md or "## Benchmarks" in md
    assert "## V2 §6.1 量化門檻" in md or "## Decision" in md


@pytest.mark.unit
def test_report_includes_metric_values() -> None:
    md = render_backtest_report(
        metrics=_metrics(sharpe=1.234, profit_factor=1.78),
        benchmarks_table={"weighted_index": 0.08},
        decision=_decision(passed=True),
        manifest={"strategy": "long_entry_v1"},
    )
    assert "1.23" in md  # sharpe rounded
    assert "1.78" in md  # profit factor


@pytest.mark.unit
def test_report_shows_pass_verdict() -> None:
    md = render_backtest_report(
        metrics=_metrics(),
        benchmarks_table={"weighted_index": 0.08},
        decision=_decision(passed=True),
        manifest={},
    )
    assert "PASS" in md or "✅" in md


@pytest.mark.unit
def test_report_shows_fail_verdict_with_reasons() -> None:
    md = render_backtest_report(
        metrics=_metrics(expectancy_bp=2.0),
        benchmarks_table={"weighted_index": 0.08},
        decision=_decision(passed=False),
        manifest={},
    )
    assert "FAIL" in md or "❌" in md
    # Failed checks should be enumerated somewhere
    assert "expectancy" in md.lower()
