"""TASK-D03a — Adapter wrapping signal rules into BacktestEngine deciders."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.backtest.adapters.signal_adapter import (
    build_entry_conditions,
    build_exit_conditions,
    make_entry_decider,
    make_exit_decider,
)
from src.backtest.engine import Position


def _entry_row(**overrides) -> pd.Series:
    base = {
        "open": 108.0,
        "high": 112.0,
        "low": 107.0,
        "close": 110.0,
        "ma_5": 105.0,
        "ma_20": 100.0,
        "ma_60": 95.0,
        "spike_severity": "mid",
        "high_20d": 109.0,
        "foreign_net_streak": 3,
        "margin_balance_5d_change": -1000.0,
        "atr_14": 2.0,
        "is_limit_up": False,
        "news_severity": 0.0,
    }
    base.update(overrides)
    return pd.Series(base)


def _market_at(d: date, close: float = 18000.0, ma_60: float = 17000.0) -> dict:
    return {d: {"market_close": close, "market_ma_60": ma_60}}


# ── build_entry_conditions ──────────────────────────────────────────────────

@pytest.mark.unit
def test_build_entry_conditions_extracts_fields() -> None:
    row = _entry_row()
    c = build_entry_conditions(
        row=row,
        market_close=18000.0,
        market_ma_60=17000.0,
        breached_daily_loss=False,
    )
    assert c.close == 110.0
    assert c.ma_5 == 105.0
    assert c.spike_severity == "mid"
    assert c.foreign_net_streak == 3
    # candle_body = |close - open| = 2; upper_shadow = high - max(close, open) = 2
    assert c.candle_body == pytest.approx(2.0)
    assert c.upper_shadow == pytest.approx(2.0)


@pytest.mark.unit
def test_build_entry_conditions_missing_columns_use_safe_defaults() -> None:
    row = pd.Series({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
                     "atr_14": 1.0})
    c = build_entry_conditions(row=row, market_close=18000.0, market_ma_60=17000.0,
                                breached_daily_loss=False)
    assert c.spike_severity == "normal"  # safe default → blocks signal
    assert c.foreign_net_streak == 0
    assert c.ma_5 == 0.0  # missing → 0 (will fail trend check)


# ── build_exit_conditions ───────────────────────────────────────────────────

@pytest.mark.unit
def test_build_exit_conditions_uses_position_state() -> None:
    row = _entry_row(close=108.0, open=110.0)
    pos = Position(
        stock_id="2330",
        entry_date=date(2025, 1, 3),
        entry_price=100.0,
        shares=1000,
        fees_in=300.0,
        highest_since_entry=115.0,
    )
    c = build_exit_conditions(row=row, position=pos, days_held=7, ma_10_value=104.0,
                              trend_active=True)
    assert c.entry_price == 100.0
    assert c.current_close == 108.0
    assert c.highest_since_entry == 115.0
    assert c.days_held == 7
    assert c.atr_14 == 2.0


# ── make_entry_decider ──────────────────────────────────────────────────────

@pytest.mark.unit
def test_entry_decider_returns_dict_when_passing() -> None:
    row = _entry_row()
    feature_df = pd.DataFrame([row.to_dict()],
                              index=pd.DatetimeIndex([pd.Timestamp("2025-01-06")]))
    feature_df.index.name = "date"

    decider = make_entry_decider(
        feature_df=feature_df,
        market_state={pd.Timestamp("2025-01-06"): {"market_close": 18000.0, "market_ma_60": 17000.0}},
        target_shares=1000,
    )
    decision = decider(date(2025, 1, 6), feature_df.loc[pd.Timestamp("2025-01-06")], False)
    assert decision is not None
    assert decision["target_shares"] == 1000


@pytest.mark.unit
def test_entry_decider_returns_none_when_has_position() -> None:
    row = _entry_row()
    feature_df = pd.DataFrame([row.to_dict()],
                              index=pd.DatetimeIndex([pd.Timestamp("2025-01-06")]))
    decider = make_entry_decider(
        feature_df=feature_df,
        market_state={pd.Timestamp("2025-01-06"): {"market_close": 18000.0, "market_ma_60": 17000.0}},
        target_shares=1000,
    )
    assert decider(date(2025, 1, 6), row, True) is None


@pytest.mark.unit
def test_entry_decider_returns_none_when_blocked() -> None:
    row = _entry_row(spike_severity="normal")  # no spike → blocks
    feature_df = pd.DataFrame([row.to_dict()],
                              index=pd.DatetimeIndex([pd.Timestamp("2025-01-06")]))
    decider = make_entry_decider(
        feature_df=feature_df,
        market_state={pd.Timestamp("2025-01-06"): {"market_close": 18000.0, "market_ma_60": 17000.0}},
        target_shares=1000,
    )
    assert decider(date(2025, 1, 6), feature_df.loc[pd.Timestamp("2025-01-06")], False) is None


# ── make_exit_decider ───────────────────────────────────────────────────────

@pytest.mark.unit
def test_exit_decider_returns_reason_when_stop_hit() -> None:
    # entry 100, atr 2 → stop 97; close 96 → trigger
    row = _entry_row(close=96.0, open=99.0, ma_5=98.0, ma_20=100.0, atr_14=2.0)
    feature_df = pd.DataFrame([row.to_dict()],
                              index=pd.DatetimeIndex([pd.Timestamp("2025-01-10")]))
    decider = make_exit_decider(feature_df=feature_df)
    pos = Position(
        stock_id="2330",
        entry_date=date(2025, 1, 3),
        entry_price=100.0,
        shares=1000,
        fees_in=300.0,
        highest_since_entry=100.0,
    )
    reason = decider(date(2025, 1, 10), feature_df.loc[pd.Timestamp("2025-01-10")], pos)
    assert reason is not None
    assert "stop_atr" in reason or "break" in reason


@pytest.mark.unit
def test_exit_decider_returns_none_when_holding_fine() -> None:
    row = _entry_row(close=115.0, open=114.0, ma_5=110.0, ma_20=100.0, atr_14=2.0)
    feature_df = pd.DataFrame([row.to_dict()],
                              index=pd.DatetimeIndex([pd.Timestamp("2025-01-10")]))
    # ma_10 not in row → adapter falls back to ma_5 or close as proxy
    decider = make_exit_decider(feature_df=feature_df)
    pos = Position(
        stock_id="2330",
        entry_date=date(2025, 1, 3),
        entry_price=100.0,
        shares=1000,
        fees_in=300.0,
        highest_since_entry=115.0,
    )
    reason = decider(date(2025, 1, 10), feature_df.loc[pd.Timestamp("2025-01-10")], pos)
    assert reason is None
