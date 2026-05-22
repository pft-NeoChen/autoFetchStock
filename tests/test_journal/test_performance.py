"""TASK-D03c — Performance metrics (V2 §5.3 / §6.1)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.backtest.engine import Trade
from src.journal.performance import (
    PerformanceMetrics,
    expectancy_bp,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    summarize_performance,
    total_return,
    turnover,
    win_rate,
)


def _trade(pnl: float, pnl_pct: float, shares: int = 1000, price: float = 100.0) -> Trade:
    return Trade(
        stock_id="A",
        entry_date=date(2025, 1, 2),
        entry_price=price,
        exit_date=date(2025, 1, 5),
        exit_price=price + pnl / shares,
        shares=shares,
        pnl=pnl,
        pnl_pct=pnl_pct,
        fees=20.0,
        tax=30.0,
        reason="manual",
    )


# ── total_return ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_total_return_known_value() -> None:
    eq = pd.Series([1_000_000.0, 1_100_000.0, 1_200_000.0])
    assert total_return(eq) == pytest.approx(0.20)


@pytest.mark.unit
def test_total_return_empty_series_is_zero() -> None:
    assert total_return(pd.Series(dtype=float)) == 0.0


@pytest.mark.unit
def test_total_return_negative_path() -> None:
    eq = pd.Series([1_000_000.0, 900_000.0])
    assert total_return(eq) == pytest.approx(-0.10)


# ── sharpe / sortino ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_sharpe_positive_for_uptrend() -> None:
    eq = pd.Series([1_000_000.0 * (1.001 ** i) for i in range(252)])
    assert sharpe_ratio(eq) > 0.0


@pytest.mark.unit
def test_sharpe_zero_when_equity_flat() -> None:
    eq = pd.Series([1_000_000.0] * 100)
    assert sharpe_ratio(eq) == 0.0


@pytest.mark.unit
def test_sortino_only_penalises_downside() -> None:
    # Two series with same volatility, one with downside, one all upside.
    np.random.seed(0)
    up_only = pd.Series(np.cumprod(1 + np.abs(np.random.randn(252)) * 0.001) * 1_000_000)
    mixed = pd.Series(np.cumprod(1 + np.random.randn(252) * 0.001) * 1_000_000)
    # Sortino on up-only path should be at least as high as on mixed
    # (downside deviation is smaller).
    s_up = sortino_ratio(up_only)
    s_mix = sortino_ratio(mixed)
    assert s_up >= s_mix


# ── max_drawdown ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_max_drawdown_known_value() -> None:
    eq = pd.Series([1.0, 1.5, 1.0])
    # peak 1.5 → 1.0 → DD = 0.333...
    assert max_drawdown(eq) == pytest.approx(1 / 3, abs=1e-6)


@pytest.mark.unit
def test_max_drawdown_zero_when_monotonic_up() -> None:
    eq = pd.Series([1.0, 1.1, 1.2, 1.3])
    assert max_drawdown(eq) == 0.0


@pytest.mark.unit
def test_max_drawdown_returns_positive_fraction() -> None:
    eq = pd.Series([1.0, 1.2, 0.6])
    assert max_drawdown(eq) == pytest.approx(0.5)


# ── win_rate / profit_factor / expectancy ───────────────────────────────────


@pytest.mark.unit
def test_win_rate_known() -> None:
    trades = [_trade(100, 0.01), _trade(200, 0.02), _trade(-50, -0.005)]
    assert win_rate(trades) == pytest.approx(2 / 3)


@pytest.mark.unit
def test_win_rate_empty_is_zero() -> None:
    assert win_rate([]) == 0.0


@pytest.mark.unit
def test_profit_factor_known() -> None:
    trades = [_trade(100, 0.01), _trade(200, 0.02), _trade(-150, -0.015)]
    assert profit_factor(trades) == pytest.approx(300 / 150)


@pytest.mark.unit
def test_profit_factor_no_losses_returns_inf() -> None:
    trades = [_trade(100, 0.01), _trade(200, 0.02)]
    assert profit_factor(trades) == float("inf")


@pytest.mark.unit
def test_expectancy_bp_known() -> None:
    # mean(pnl_pct) over trades, in basis points (×10_000)
    trades = [_trade(100, 0.001), _trade(200, 0.002), _trade(-50, -0.0005)]
    expected_bp = ((0.001 + 0.002 - 0.0005) / 3) * 10_000
    assert expectancy_bp(trades) == pytest.approx(expected_bp)


@pytest.mark.unit
def test_expectancy_bp_empty_is_zero() -> None:
    assert expectancy_bp([]) == 0.0


# ── turnover ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_turnover_known() -> None:
    # 2 trades; per trade gross = entry_price * shares (one-way).
    # entry_price=100, shares=1000 → 100_000 per side, round-trip ≈ 200_000.
    trades = [_trade(100, 0.001), _trade(-50, -0.0005)]
    # turnover defined as (sum of round-trip notionals) / initial_capital
    t = turnover(trades, initial_capital=1_000_000.0)
    assert t == pytest.approx((2 * 2 * 100_000) / 1_000_000.0)


@pytest.mark.unit
def test_turnover_zero_when_no_trades() -> None:
    assert turnover([], initial_capital=1_000_000.0) == 0.0


# ── summarize_performance ───────────────────────────────────────────────────


@pytest.mark.unit
def test_summarize_returns_dataclass_with_all_fields() -> None:
    trades = [_trade(100, 0.001), _trade(-50, -0.0005)]
    equity = pd.Series([1_000_000.0, 1_000_500.0, 1_000_050.0])
    metrics = summarize_performance(
        trades=trades, equity=equity, initial_capital=1_000_000.0
    )
    assert isinstance(metrics, PerformanceMetrics)
    assert metrics.n_trades == 2
    assert metrics.total_return == pytest.approx(0.00005)
    assert metrics.win_rate == pytest.approx(0.5)
    # Field presence smoke
    for attr in ("sharpe", "sortino", "max_drawdown", "profit_factor",
                 "expectancy_bp", "turnover"):
        assert hasattr(metrics, attr)
