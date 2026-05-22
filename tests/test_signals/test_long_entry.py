"""TASK-S03 — Long-entry rule (V2 §2 第一版策略)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from src.signals.rules.long_entry import (
    EntryConditions,
    evaluate_long_entry,
)


def _passing() -> EntryConditions:
    """All six entry conditions satisfied + no avoid trigger."""
    return EntryConditions(
        close=110.0,
        open=108.0,
        ma_5=105.0,
        ma_20=100.0,
        ma_60=95.0,
        market_close=18000.0,
        market_ma_60=17000.0,
        spike_severity="mid",          # ≥ MID
        high_20d=109.0,                # close > high_20d → breakout
        foreign_net_streak=3,           # 連 3 日 net buy
        margin_balance_5d_change=-1000, # 融資 5 日減幅 < 0
        is_limit_up=False,
        news_severity=0.0,
        breached_daily_loss=False,
        upper_shadow=0.5,
        candle_body=2.0,
        atr_14=2.0,
    )


@pytest.mark.unit
def test_all_conditions_pass_returns_true() -> None:
    ok, reasons, inv = evaluate_long_entry(_passing())
    assert ok is True
    assert reasons  # non-empty
    assert "break_below_ma20" in inv
    assert "break_below_ma10" in inv or "stop_atr" in inv


@pytest.mark.unit
def test_close_below_ma20_blocks() -> None:
    c = replace(_passing(), close=99.0)
    ok, _, _ = evaluate_long_entry(c)
    assert ok is False


@pytest.mark.unit
def test_close_below_ma60_blocks() -> None:
    c = replace(_passing(), close=94.0, ma_20=90.0)
    ok, _, _ = evaluate_long_entry(c)
    assert ok is False


@pytest.mark.unit
def test_no_volume_spike_blocks() -> None:
    c = replace(_passing(), spike_severity="low")  # < MID
    ok, _, _ = evaluate_long_entry(c)
    assert ok is False


@pytest.mark.unit
def test_red_candle_without_breakout_blocks() -> None:
    c = replace(_passing(), close=108.0, open=110.0, high_20d=120.0)
    ok, _, _ = evaluate_long_entry(c)
    assert ok is False


@pytest.mark.unit
def test_red_candle_but_breakout_passes() -> None:
    c = replace(_passing(), close=108.0, open=110.0, high_20d=107.0, ma_5=106.0, ma_20=100.0)
    ok, _, _ = evaluate_long_entry(c)
    assert ok is True


@pytest.mark.unit
def test_weak_chip_blocks() -> None:
    c = replace(_passing(), foreign_net_streak=1, margin_balance_5d_change=1000)
    ok, _, _ = evaluate_long_entry(c)
    assert ok is False


@pytest.mark.unit
def test_market_below_ma60_blocks() -> None:
    c = replace(_passing(), market_close=16000.0)
    ok, _, _ = evaluate_long_entry(c)
    assert ok is False


@pytest.mark.unit
def test_limit_up_blocks() -> None:
    c = replace(_passing(), is_limit_up=True)
    ok, _, _ = evaluate_long_entry(c)
    assert ok is False


@pytest.mark.unit
def test_long_upper_shadow_blocks() -> None:
    # 上影線 > 實體 × 1.5
    c = replace(_passing(), upper_shadow=4.0, candle_body=2.0)
    ok, _, _ = evaluate_long_entry(c)
    assert ok is False


@pytest.mark.unit
def test_negative_news_blocks() -> None:
    c = replace(_passing(), news_severity=-7.0)
    ok, _, _ = evaluate_long_entry(c)
    assert ok is False


@pytest.mark.unit
def test_daily_loss_breached_blocks() -> None:
    c = replace(_passing(), breached_daily_loss=True)
    ok, _, _ = evaluate_long_entry(c)
    assert ok is False
