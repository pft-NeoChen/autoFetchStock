"""TASK-S04 — Exit rules (V2 §2 出場條件)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.signals.rules.exits import ExitConditions, evaluate_exit


def _holding() -> ExitConditions:
    """Healthy position — no exit triggers."""
    return ExitConditions(
        entry_price=100.0,
        current_close=110.0,
        current_open=109.0,
        ma_10=105.0,
        atr_14=2.0,
        spike_severity="normal",
        candle_body=1.0,
        highest_since_entry=110.0,
        days_held=3,
        trend_active=True,
    )


@pytest.mark.unit
def test_no_exit_when_all_clear() -> None:
    ok, reasons = evaluate_exit(_holding())
    assert ok is False
    assert reasons == []


@pytest.mark.unit
def test_stop_loss_at_1_5_atr() -> None:
    # close < entry - 1.5 × ATR → fixed stop loss
    c = replace(_holding(), current_close=96.5)  # 100 - 1.5*2 = 97, 96.5 < 97
    ok, reasons = evaluate_exit(c)
    assert ok is True
    assert "stop_atr" in reasons


@pytest.mark.unit
def test_stop_loss_exact_boundary_no_exit() -> None:
    c = replace(_holding(), current_close=97.0)
    ok, reasons = evaluate_exit(c)
    assert "stop_atr" not in reasons


@pytest.mark.unit
def test_break_below_ma10_exits() -> None:
    c = replace(_holding(), current_close=104.0, ma_10=105.0)
    ok, reasons = evaluate_exit(c)
    assert ok is True
    assert "break_below_ma10" in reasons


@pytest.mark.unit
def test_bearish_high_spike_with_large_body_exits() -> None:
    c = replace(
        _holding(),
        current_close=108.0,
        current_open=111.0,  # red candle
        candle_body=3.0,     # > atr (2.0)
        spike_severity="high",
    )
    ok, reasons = evaluate_exit(c)
    assert ok is True
    assert "bearish_volume_spike" in reasons


@pytest.mark.unit
def test_bearish_low_severity_does_not_exit() -> None:
    c = replace(
        _holding(),
        current_close=108.0,
        current_open=111.0,
        candle_body=3.0,
        spike_severity="low",
    )
    ok, reasons = evaluate_exit(c)
    assert "bearish_volume_spike" not in reasons


@pytest.mark.unit
def test_trailing_stop_after_atr_drawdown() -> None:
    # high - close > 1.0 × ATR
    c = replace(_holding(), highest_since_entry=120.0, current_close=117.5, atr_14=2.0)
    ok, reasons = evaluate_exit(c)
    assert ok is True
    assert "trailing_atr" in reasons


@pytest.mark.unit
def test_trailing_stop_within_atr_no_exit() -> None:
    c = replace(_holding(), highest_since_entry=120.0, current_close=119.0, atr_14=2.0)
    ok, reasons = evaluate_exit(c)
    assert "trailing_atr" not in reasons


@pytest.mark.unit
def test_time_stop_after_10_days_no_trend() -> None:
    c = replace(_holding(), days_held=11, trend_active=False)
    ok, reasons = evaluate_exit(c)
    assert ok is True
    assert "time_stop_10d" in reasons


@pytest.mark.unit
def test_time_stop_held_but_trend_still_active_no_exit() -> None:
    c = replace(_holding(), days_held=15, trend_active=True)
    ok, reasons = evaluate_exit(c)
    assert "time_stop_10d" not in reasons


@pytest.mark.unit
def test_multiple_triggers_lists_all_reasons() -> None:
    c = replace(
        _holding(),
        current_close=96.0,           # stop_atr
        ma_10=98.0,                   # break_below_ma10
        days_held=20,
        trend_active=False,           # time_stop
    )
    ok, reasons = evaluate_exit(c)
    assert ok is True
    assert {"stop_atr", "break_below_ma10", "time_stop_10d"} <= set(reasons)
