"""TASK-M02 — Live ↔ Backtest consistency check tests (V2 §9.2)."""

from __future__ import annotations

import pytest

from src.monitor.consistency_check import (
    ConsistencyMetric,
    ConsistencyResult,
    compare_live_to_backtest,
)


pytestmark = pytest.mark.unit


def test_consistency_pass_when_metrics_within_sigma_band() -> None:
    bt = ConsistencyMetric(trade_count=100.0, mean_slippage_bp=5.0, std_slippage_bp=1.0)
    live = ConsistencyMetric(trade_count=102.0, mean_slippage_bp=5.5, std_slippage_bp=1.0)
    result = compare_live_to_backtest(live=live, backtest=bt, sigma=2.0)
    assert result.passed is True
    assert result.violations == []


def test_consistency_fail_when_trade_count_outside_2sigma() -> None:
    bt = ConsistencyMetric(trade_count=100.0, mean_slippage_bp=5.0, std_slippage_bp=10.0)
    # Backtest std 10 → 2σ band 80-120; live 130 outside.
    live = ConsistencyMetric(trade_count=130.0, mean_slippage_bp=5.0, std_slippage_bp=10.0)
    result = compare_live_to_backtest(live=live, backtest=bt, sigma=2.0)
    assert result.passed is False
    assert "trade_count" in " ".join(result.violations)


def test_consistency_fail_when_mean_slippage_outside_band() -> None:
    bt = ConsistencyMetric(trade_count=100.0, mean_slippage_bp=5.0, std_slippage_bp=1.0)
    # 2σ band on slippage = [3, 7]; live 12 outside.
    live = ConsistencyMetric(trade_count=100.0, mean_slippage_bp=12.0, std_slippage_bp=1.0)
    result = compare_live_to_backtest(live=live, backtest=bt, sigma=2.0)
    assert result.passed is False
    assert "slippage" in " ".join(result.violations)


def test_consistency_uses_backtest_std_to_widen_band() -> None:
    # Larger backtest std → wider band → live can stray more.
    bt = ConsistencyMetric(trade_count=100.0, mean_slippage_bp=5.0, std_slippage_bp=10.0)
    live = ConsistencyMetric(trade_count=100.0, mean_slippage_bp=20.0, std_slippage_bp=10.0)
    result = compare_live_to_backtest(live=live, backtest=bt, sigma=2.0)
    assert result.passed is True


def test_consistency_zero_std_still_works_with_safety_floor() -> None:
    bt = ConsistencyMetric(trade_count=100.0, mean_slippage_bp=5.0, std_slippage_bp=0.0)
    # std=0 → use min_std floor; live 5.5 should still pass narrow band
    live = ConsistencyMetric(trade_count=100.0, mean_slippage_bp=5.5, std_slippage_bp=0.0)
    result = compare_live_to_backtest(
        live=live, backtest=bt, sigma=2.0, min_std=1.0
    )
    assert result.passed is True


def test_consistency_result_recommends_fallback_when_failed() -> None:
    bt = ConsistencyMetric(trade_count=100.0, mean_slippage_bp=5.0, std_slippage_bp=1.0)
    live = ConsistencyMetric(trade_count=200.0, mean_slippage_bp=20.0, std_slippage_bp=1.0)
    result = compare_live_to_backtest(live=live, backtest=bt, sigma=2.0)
    assert result.passed is False
    assert result.recommended_action == "fallback_to_paper"


def test_consistency_result_recommends_continue_when_passed() -> None:
    bt = ConsistencyMetric(trade_count=100.0, mean_slippage_bp=5.0, std_slippage_bp=1.0)
    live = ConsistencyMetric(trade_count=100.0, mean_slippage_bp=5.0, std_slippage_bp=1.0)
    result = compare_live_to_backtest(live=live, backtest=bt, sigma=2.0)
    assert result.recommended_action == "continue"
