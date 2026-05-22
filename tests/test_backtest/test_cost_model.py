"""TASK-B01 — Cost model (V2 §3.2)."""

from __future__ import annotations

import pytest

from src.backtest import cost_model as cm


# ── round_to_tick (台交所 tick rule, 2020+) ─────────────────────────────────

@pytest.mark.parametrize(
    "price,expected_tick",
    [
        (5.07, 0.01),
        (8.99, 0.01),
        (12.13, 0.05),
        (49.87, 0.05),
        (50.05, 0.1),
        (75.22, 0.1),
        (99.55, 0.1),
        (150.7, 0.5),
        (499.49, 0.5),
        (501.7, 1.0),
        (999.4, 1.0),
        (1503.0, 5.0),
        (5000.0, 5.0),
    ],
)
@pytest.mark.unit
def test_tick_size_by_band(price: float, expected_tick: float) -> None:
    assert cm.tick_size_for(price) == pytest.approx(expected_tick)


@pytest.mark.unit
def test_round_to_tick_under_10() -> None:
    assert cm.round_to_tick(5.073) == pytest.approx(5.07)
    assert cm.round_to_tick(5.075) == pytest.approx(5.08)


@pytest.mark.unit
def test_round_to_tick_50_to_100() -> None:
    assert cm.round_to_tick(75.22) == pytest.approx(75.2)
    assert cm.round_to_tick(75.27) == pytest.approx(75.3)


@pytest.mark.unit
def test_round_to_tick_above_1000() -> None:
    assert cm.round_to_tick(1503.0) == pytest.approx(1505.0)
    assert cm.round_to_tick(1502.0) == pytest.approx(1500.0)


# ── commission / round_trip_cost ────────────────────────────────────────────

@pytest.mark.unit
def test_commission_single_side() -> None:
    # 100 元 × 0.001425 × 0.38 折扣
    expected = 100.0 * cm.COMMISSION_RATE * cm.COMMISSION_DISCOUNT
    assert cm.commission(100.0) == pytest.approx(expected)


@pytest.mark.unit
def test_round_trip_cost_normal_breakdown() -> None:
    res = cm.round_trip_cost(price_in=100.0, price_out=110.0, shares=1000, is_daytrade=False)
    expected_fee_in = 100.0 * cm.COMMISSION_RATE * cm.COMMISSION_DISCOUNT * 1000
    expected_fee_out = 110.0 * cm.COMMISSION_RATE * cm.COMMISSION_DISCOUNT * 1000
    expected_tax = 110.0 * cm.TRANSACTION_TAX_NORMAL * 1000
    assert res["fee_in"] == pytest.approx(expected_fee_in)
    assert res["fee_out"] == pytest.approx(expected_fee_out)
    assert res["tax"] == pytest.approx(expected_tax)
    assert res["total"] == pytest.approx(expected_fee_in + expected_fee_out + expected_tax)


@pytest.mark.unit
def test_round_trip_cost_daytrade_uses_lower_tax() -> None:
    normal = cm.round_trip_cost(100.0, 110.0, 1000, is_daytrade=False)
    daytrade = cm.round_trip_cost(100.0, 110.0, 1000, is_daytrade=True)
    assert daytrade["tax"] < normal["tax"]
    # Daytrade tax = 0.15% × 110 × 1000
    assert daytrade["tax"] == pytest.approx(110.0 * cm.TRANSACTION_TAX_DAYTRADE * 1000)


# ── slippage ────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_slippage_buy_adds_cost() -> None:
    # buy → spread side positive
    s = cm.slippage(price=100.0, side="buy", tick_size=0.5, spread=0.2)
    assert s == pytest.approx(0.5 + 0.5 * 0.2)


@pytest.mark.unit
def test_slippage_sell_subtracts_cost() -> None:
    s = cm.slippage(price=100.0, side="sell", tick_size=0.5, spread=0.2)
    assert s == pytest.approx(0.5 - 0.5 * 0.2)


@pytest.mark.unit
def test_slippage_invalid_side_raises() -> None:
    with pytest.raises(ValueError):
        cm.slippage(price=100.0, side="diagonal", tick_size=0.5, spread=0.2)


# ── monkeypatch ─────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_constants_are_monkeypatchable(monkeypatch) -> None:
    monkeypatch.setattr(cm, "COMMISSION_RATE", 0.002)
    assert cm.commission(100.0) == pytest.approx(100.0 * 0.002 * cm.COMMISSION_DISCOUNT)
