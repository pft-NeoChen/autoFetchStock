"""TASK-S1-E0 — trade-level resample bootstrap helpers."""

from __future__ import annotations

import math

import pytest

from src.research.trade_bootstrap import (
    BootstrapStat,
    bootstrap_trade_metrics,
    expectancy_bp,
    profit_factor,
    sharpe_ratio,
)


pytestmark = pytest.mark.unit


def _trades(pnl_pcts: list[float]) -> list[dict]:
    return [{"pnl_pct": x, "stock_id": "T", "reason": "x"} for x in pnl_pcts]


def test_expectancy_bp_is_mean_pnl_pct_times_10000() -> None:
    trades = _trades([0.01, -0.005, 0.02, -0.01])

    assert expectancy_bp(trades) == pytest.approx(((0.01 - 0.005 + 0.02 - 0.01) / 4) * 10000)


def test_profit_factor_is_sum_wins_over_sum_losses() -> None:
    trades = _trades([0.02, 0.04, -0.01, -0.05])

    # wins = 0.06; losses = 0.06; pf = 1.0
    assert profit_factor(trades) == pytest.approx(1.0)


def test_profit_factor_inf_when_no_losses() -> None:
    trades = _trades([0.01, 0.02])

    assert math.isinf(profit_factor(trades))


def test_sharpe_ratio_uses_mean_over_std_of_pnl_pct() -> None:
    trades = _trades([0.01, -0.01, 0.01, -0.01])

    # mean = 0 → sharpe = 0
    assert sharpe_ratio(trades) == pytest.approx(0.0)


def test_bootstrap_returns_stat_for_each_metric() -> None:
    trades = _trades([0.01, -0.005, 0.02, -0.01, 0.015])

    result = bootstrap_trade_metrics(trades, n_iter=200, seed=42)

    assert {"expectancy_bp", "sharpe", "profit_factor", "n_trades"} == set(result.keys())
    for key in ("expectancy_bp", "sharpe", "profit_factor"):
        stat = result[key]
        assert isinstance(stat, BootstrapStat)
        assert stat.ci_low <= stat.point <= stat.ci_high
        assert stat.n_iter == 200
    assert result["n_trades"].point == 5


def test_bootstrap_seed_is_reproducible() -> None:
    trades = _trades([0.01, -0.005, 0.02, -0.01, 0.015, 0.03, -0.02])

    a = bootstrap_trade_metrics(trades, n_iter=200, seed=7)
    b = bootstrap_trade_metrics(trades, n_iter=200, seed=7)

    assert a["expectancy_bp"].ci_low == pytest.approx(b["expectancy_bp"].ci_low)
    assert a["expectancy_bp"].ci_high == pytest.approx(b["expectancy_bp"].ci_high)


def test_bootstrap_empty_trades_returns_nan() -> None:
    result = bootstrap_trade_metrics([], n_iter=10, seed=1)

    assert math.isnan(result["expectancy_bp"].point)
    assert result["n_trades"].point == 0
