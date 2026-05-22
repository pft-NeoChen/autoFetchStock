"""TASK-B04 — Single-stock backtester engine."""

from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd
import pytest

from src.backtest.engine import (
    BacktestEngine,
    BacktestResult,
    Position,
    Trade,
)


def _ohlc(closes: list[float], start: str = "2025-01-02") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(closes), freq="B")
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.005 for c in closes],
            "low": [c * 0.995 for c in closes],
            "close": closes,
            "volume": [1_000_000] * len(closes),
            "previous_close": [closes[0]] + [closes[i - 1] for i in range(1, len(closes))],
        },
        index=idx,
    )


def _entry_at(target_date: date, shares: int = 1000):
    def decider(d, row, has_position):
        if has_position:
            return None
        if d == target_date:
            return {"target_shares": shares}
        return None
    return decider


def _exit_at(target_date: date, reason: str = "manual"):
    def decider(d, row, position):
        if d == target_date:
            return reason
        return None
    return decider


def _never_entry(d, row, has_position):
    return None


def _never_exit(d, row, position):
    return None


# ── basic flow ──────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_no_signals_yields_no_trades() -> None:
    df = _ohlc([100.0, 101.0, 102.0])
    engine = BacktestEngine(
        initial_cash=1_000_000,
        entry_decider=_never_entry,
        exit_decider=_never_exit,
    )
    result = engine.run(stock_id="2330", ohlc_df=df)
    assert result.trades == []
    assert result.final_equity == pytest.approx(1_000_000)


@pytest.mark.unit
def test_entry_filled_at_next_day_open() -> None:
    df = _ohlc([100.0, 110.0, 115.0, 120.0])
    # Entry decision at 2025-01-02 → fill at next bar 2025-01-03 open = 110
    engine = BacktestEngine(
        initial_cash=1_000_000,
        entry_decider=_entry_at(date(2025, 1, 2)),
        exit_decider=_exit_at(date(2025, 1, 6)),
    )
    result = engine.run(stock_id="2330", ohlc_df=df)
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_price == pytest.approx(110.0)
    assert trade.entry_date == date(2025, 1, 3)


@pytest.mark.unit
def test_exit_filled_at_next_day_open() -> None:
    df = _ohlc([100.0, 110.0, 115.0, 120.0, 125.0])
    engine = BacktestEngine(
        initial_cash=1_000_000,
        entry_decider=_entry_at(date(2025, 1, 2)),
        exit_decider=_exit_at(date(2025, 1, 6), reason="manual"),
    )
    result = engine.run(stock_id="2330", ohlc_df=df)
    trade = result.trades[0]
    # Exit decision on 2025-01-06 → fill 2025-01-07 open = 120
    assert trade.exit_date == date(2025, 1, 7)
    assert trade.exit_price == pytest.approx(120.0)


@pytest.mark.unit
def test_pnl_deducts_fees_and_tax() -> None:
    df = _ohlc([100.0, 110.0, 115.0, 120.0, 125.0])
    engine = BacktestEngine(
        initial_cash=1_000_000,
        entry_decider=_entry_at(date(2025, 1, 2), shares=1000),
        exit_decider=_exit_at(date(2025, 1, 6)),
    )
    result = engine.run(stock_id="2330", ohlc_df=df)
    trade = result.trades[0]
    gross = (125.0 - 110.0) * 1000
    assert trade.pnl < gross  # fees + tax subtracted
    assert trade.fees > 0
    assert trade.tax > 0


@pytest.mark.unit
def test_no_double_entry_while_position_open() -> None:
    df = _ohlc([100.0, 110.0, 115.0, 120.0, 125.0, 130.0])

    def always_entry(d, row, has_position):
        if has_position:
            return None
        return {"target_shares": 1000}

    engine = BacktestEngine(
        initial_cash=1_000_000,
        entry_decider=always_entry,
        exit_decider=_never_exit,
    )
    result = engine.run(stock_id="2330", ohlc_df=df)
    # Only one entry should be filled; position held until end → no exit
    assert len(result.trades) == 0  # no closed trade
    # But equity should reflect mark-to-market
    assert result.final_equity != 1_000_000


@pytest.mark.unit
def test_open_position_marked_to_market_at_end() -> None:
    df = _ohlc([100.0, 110.0, 120.0])
    engine = BacktestEngine(
        initial_cash=1_000_000,
        entry_decider=_entry_at(date(2025, 1, 2), shares=1000),
        exit_decider=_never_exit,
    )
    result = engine.run(stock_id="2330", ohlc_df=df)
    # Equity = cash − cost_in × 1000 + last_close × 1000 ≈ 1M + (120-110)×1000 − fees
    assert result.final_equity > 1_000_000


# ── cash ledger ─────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_cash_ledger_t_plus_2_settlement_for_sell() -> None:
    df = _ohlc([100.0, 110.0, 115.0, 120.0, 125.0, 128.0, 130.0, 132.0])
    engine = BacktestEngine(
        initial_cash=1_000_000,
        entry_decider=_entry_at(date(2025, 1, 2), shares=1000),
        exit_decider=_exit_at(date(2025, 1, 6)),
    )
    result = engine.run(stock_id="2330", ohlc_df=df)
    # Available cash on settlement date should reflect sale proceeds.
    # Trade exit at 2025-01-07 → settle 2025-01-09.
    # cash_curve.available at 2025-01-08 (T+1 after fill) should NOT yet reflect sale,
    # but cash_curve at 2025-01-09 should.
    available = result.cash_curve
    assert available.loc[pd.Timestamp("2025-01-08")] < available.loc[pd.Timestamp("2025-01-09")]


@pytest.mark.unit
def test_buy_blocked_when_cash_insufficient() -> None:
    df = _ohlc([100.0, 110.0, 115.0])

    def big_entry(d, row, has_position):
        if has_position:
            return None
        return {"target_shares": 100_000}  # 100k shares × 110 = 11M, only 1M cash

    engine = BacktestEngine(
        initial_cash=1_000_000,
        entry_decider=big_entry,
        exit_decider=_never_exit,
    )
    result = engine.run(stock_id="2330", ohlc_df=df)
    # Cash insufficient → never filled in full 100k size. Engine may either
    # void the order entirely or open a smaller position; both acceptable.
    if result.trades:
        assert result.trades[0].shares < 100_000
    # In all cases final_equity should not exceed initial cash + small mtm slack.
    # (Sanity: should not blow up to negative or unrealistic gains.)
    assert result.final_equity > 0


# ── equity curve shape ──────────────────────────────────────────────────────

@pytest.mark.unit
def test_equity_curve_length_matches_bars() -> None:
    df = _ohlc([100.0] * 10)
    engine = BacktestEngine(
        initial_cash=1_000_000,
        entry_decider=_never_entry,
        exit_decider=_never_exit,
    )
    result = engine.run(stock_id="2330", ohlc_df=df)
    assert len(result.equity_curve) == len(df)


@pytest.mark.unit
def test_limit_up_lock_voids_entry() -> None:
    # Construct a bar where open=high=low=close=110 (locked-up after prev=100)
    idx = pd.date_range("2025-01-02", periods=3, freq="B")
    df = pd.DataFrame(
        {
            "open":  [100.0, 110.0, 115.0],
            "high":  [101.0, 110.0, 116.0],
            "low":   [99.0,  110.0, 114.0],
            "close": [100.0, 110.0, 115.0],
            "volume": [1_000_000] * 3,
            "previous_close": [100.0, 100.0, 110.0],
        },
        index=idx,
    )
    engine = BacktestEngine(
        initial_cash=1_000_000,
        entry_decider=_entry_at(date(2025, 1, 2), shares=1000),
        exit_decider=_never_exit,
    )
    result = engine.run(stock_id="2330", ohlc_df=df)
    # Bar at 2025-01-03 is fully locked-up → entry voided
    assert result.trades == []
    assert result.final_equity == pytest.approx(1_000_000)
