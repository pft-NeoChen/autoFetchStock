"""TASK-D03c — V2 §6.1 量化門檻判定."""

from __future__ import annotations

import pytest

from src.journal.decision import (
    DecisionInput,
    DecisionResult,
    evaluate_v2_thresholds,
)
from src.journal.performance import PerformanceMetrics


def _passing_metrics(**overrides) -> PerformanceMetrics:
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


def _passing_input(**overrides) -> DecisionInput:
    base = dict(
        metrics=_passing_metrics(),
        oos_is_ratio=0.85,
        top5_excluded_return=0.05,
        beats_weighted_index=True,
        beats_etf_0050=True,
        oos_alpha=0.04,
        regime_coverage_bull=1,
        regime_coverage_bear=1,
        regime_coverage_range=1,
    )
    base.update(overrides)
    return DecisionInput(**base)


@pytest.mark.unit
def test_all_thresholds_pass_returns_passed_true() -> None:
    result = evaluate_v2_thresholds(_passing_input())
    assert isinstance(result, DecisionResult)
    assert result.passed is True
    assert all(result.checks.values())


@pytest.mark.unit
def test_expectancy_below_5bp_fails() -> None:
    inp = _passing_input(metrics=_passing_metrics(expectancy_bp=3.0))
    result = evaluate_v2_thresholds(inp)
    assert result.passed is False
    assert result.checks["expectancy_bp"] is False
    assert any("expectancy" in r.lower() for r in result.reasons)


@pytest.mark.unit
def test_profit_factor_below_1_3_fails() -> None:
    inp = _passing_input(metrics=_passing_metrics(profit_factor=1.1))
    result = evaluate_v2_thresholds(inp)
    assert result.passed is False
    assert result.checks["profit_factor"] is False


@pytest.mark.unit
def test_max_drawdown_above_20pct_fails() -> None:
    inp = _passing_input(metrics=_passing_metrics(max_drawdown=0.25))
    result = evaluate_v2_thresholds(inp)
    assert result.passed is False
    assert result.checks["max_drawdown"] is False


@pytest.mark.unit
def test_sharpe_below_1_fails() -> None:
    inp = _passing_input(metrics=_passing_metrics(sharpe=0.8))
    result = evaluate_v2_thresholds(inp)
    assert result.passed is False
    assert result.checks["sharpe"] is False


@pytest.mark.unit
def test_oos_is_ratio_below_0_7_fails() -> None:
    inp = _passing_input(oos_is_ratio=0.6)
    result = evaluate_v2_thresholds(inp)
    assert result.passed is False
    assert result.checks["oos_is_ratio"] is False


@pytest.mark.unit
def test_top5_excluded_negative_fails() -> None:
    inp = _passing_input(top5_excluded_return=-0.02)
    result = evaluate_v2_thresholds(inp)
    assert result.passed is False
    assert result.checks["top5_excluded"] is False


@pytest.mark.unit
def test_benchmark_lose_fails() -> None:
    inp = _passing_input(beats_weighted_index=False)
    result = evaluate_v2_thresholds(inp)
    assert result.passed is False
    assert result.checks["beats_benchmarks"] is False


@pytest.mark.unit
def test_alpha_not_positive_fails() -> None:
    inp = _passing_input(oos_alpha=-0.01)
    result = evaluate_v2_thresholds(inp)
    assert result.passed is False
    assert result.checks["oos_alpha"] is False


@pytest.mark.unit
def test_regime_coverage_missing_one_fails() -> None:
    inp = _passing_input(regime_coverage_bear=0)
    result = evaluate_v2_thresholds(inp)
    assert result.passed is False
    assert result.checks["regime_coverage"] is False


@pytest.mark.unit
def test_trade_count_below_50_fails() -> None:
    inp = _passing_input(metrics=_passing_metrics(n_trades=30))
    result = evaluate_v2_thresholds(inp)
    assert result.passed is False
    assert result.checks["n_trades"] is False
