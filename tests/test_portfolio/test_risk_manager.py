"""TASK-R01 — RiskManager."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.portfolio.risk_manager import (
    PositionSnapshot,
    RiskConfig,
    RiskManager,
    RiskState,
)


def _position(stock_id: str, market_value: float = 100_000.0) -> PositionSnapshot:
    return PositionSnapshot(stock_id=stock_id, market_value=market_value)


@pytest.mark.unit
def test_allows_order_within_single_trade_risk_budget() -> None:
    manager = RiskManager(RiskConfig(max_single_trade_risk_pct=0.01))

    decision = manager.evaluate_entry(
        account_equity=1_000_000,
        stock_id="2330",
        entry_price=100.0,
        stop_price=95.0,
        target_shares=1000,
    )

    assert decision.allowed is True
    assert decision.approved_shares == 1000
    assert decision.risk_amount == pytest.approx(5000.0)


@pytest.mark.unit
def test_blocks_order_exceeding_single_trade_risk_budget() -> None:
    manager = RiskManager(RiskConfig(max_single_trade_risk_pct=0.005))

    decision = manager.evaluate_entry(
        account_equity=1_000_000,
        stock_id="2330",
        entry_price=100.0,
        stop_price=90.0,
        target_shares=1000,
    )

    assert decision.allowed is False
    assert decision.approved_shares == 0
    assert "single_trade_risk" in decision.reasons


@pytest.mark.unit
def test_reduces_shares_to_single_trade_risk_budget_when_requested() -> None:
    manager = RiskManager(RiskConfig(max_single_trade_risk_pct=0.005))

    decision = manager.evaluate_entry(
        account_equity=1_000_000,
        stock_id="2330",
        entry_price=100.0,
        stop_price=90.0,
        target_shares=2000,
        reduce_to_fit=True,
    )

    assert decision.allowed is True
    assert decision.approved_shares == 500
    assert "reduced_single_trade_risk" in decision.reasons


@pytest.mark.unit
def test_blocks_when_max_positions_reached_for_new_stock() -> None:
    manager = RiskManager(RiskConfig(max_positions=2))

    decision = manager.evaluate_entry(
        account_equity=1_000_000,
        stock_id="2454",
        entry_price=100.0,
        stop_price=98.0,
        target_shares=1000,
        open_positions=[_position("2330"), _position("2317")],
    )

    assert decision.allowed is False
    assert "max_positions" in decision.reasons


@pytest.mark.unit
def test_existing_stock_does_not_count_against_max_positions() -> None:
    manager = RiskManager(RiskConfig(max_positions=2))

    decision = manager.evaluate_entry(
        account_equity=1_000_000,
        stock_id="2330",
        entry_price=100.0,
        stop_price=98.0,
        target_shares=1000,
        open_positions=[_position("2330"), _position("2317")],
    )

    assert decision.allowed is True


@pytest.mark.unit
def test_blocks_when_single_stock_allocation_exceeds_cap() -> None:
    manager = RiskManager(RiskConfig(max_stock_allocation_pct=0.15))

    decision = manager.evaluate_entry(
        account_equity=1_000_000,
        stock_id="2330",
        entry_price=100.0,
        stop_price=99.0,
        target_shares=2000,
    )

    assert decision.allowed is False
    assert "stock_allocation" in decision.reasons


@pytest.mark.unit
def test_blocks_remaining_day_after_daily_loss_limit_hit() -> None:
    state = RiskState(current_date=date(2026, 5, 22), realized_pnl_today=-20_000)
    manager = RiskManager(RiskConfig(max_daily_loss_pct=0.02), state=state)

    decision = manager.evaluate_entry(
        account_equity=1_000_000,
        stock_id="2330",
        entry_price=100.0,
        stop_price=99.0,
        target_shares=1000,
        trade_date=date(2026, 5, 22),
    )

    assert decision.allowed is False
    assert "daily_loss_limit" in decision.reasons


@pytest.mark.unit
def test_record_trade_loss_triggers_half_size_after_three_losses() -> None:
    manager = RiskManager(RiskConfig(losses_before_half_size=3))

    manager.record_trade_result(-1000, trade_date=date(2026, 5, 20))
    manager.record_trade_result(-1000, trade_date=date(2026, 5, 21))
    manager.record_trade_result(-1000, trade_date=date(2026, 5, 22))

    assert manager.state.consecutive_losses == 3
    assert manager.position_size_multiplier(on_date=date(2026, 5, 22)) == pytest.approx(0.5)


@pytest.mark.unit
def test_record_trade_loss_triggers_one_trading_day_cooldown_after_five_losses() -> None:
    manager = RiskManager(RiskConfig(losses_before_cooldown=5, cooldown_trading_days=1))
    start = date(2026, 5, 18)

    for i in range(5):
        manager.record_trade_result(-1000, trade_date=start + timedelta(days=i))

    assert manager.state.cooldown_until == date(2026, 5, 25)
    assert manager.is_paused(on_date=date(2026, 5, 25)) is True
    assert manager.is_paused(on_date=date(2026, 5, 26)) is False


@pytest.mark.unit
def test_profitable_trade_resets_consecutive_losses_and_cooldown() -> None:
    manager = RiskManager(RiskConfig(losses_before_cooldown=5, cooldown_trading_days=1))
    for i in range(5):
        manager.record_trade_result(-1000, trade_date=date(2026, 5, 18) + timedelta(days=i))

    manager.record_trade_result(5000, trade_date=date(2026, 5, 26))

    assert manager.state.consecutive_losses == 0
    assert manager.state.cooldown_until is None
    assert manager.position_size_multiplier(on_date=date(2026, 5, 26)) == pytest.approx(1.0)
