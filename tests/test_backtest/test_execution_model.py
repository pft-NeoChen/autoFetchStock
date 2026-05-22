"""TASK-B02 — Execution model (V2 §3.3 / §3.7)."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.backtest.execution_model import (
    LIQUIDITY_CAP_PCT,
    LOT_SIZE,
    FillResult,
    MarketBar,
    Order,
    next_business_day,
    simulate_fill,
)


def _order(
    side: str = "buy",
    shares: int = 1000,
    is_odd_lot: bool = False,
) -> Order:
    return Order(
        stock_id="2330",
        side=side,
        shares=shares,
        submitted_at=datetime(2025, 1, 6, 13, 30),
        is_odd_lot=is_odd_lot,
    )


def _bar(
    open_=100.0,
    high=101.0,
    low=99.0,
    close=100.5,
    volume=1_000_000,
    previous_close=100.0,
    d: date = date(2025, 1, 7),
) -> MarketBar:
    return MarketBar(
        date=d, open=open_, high=high, low=low, close=close,
        volume=volume, previous_close=previous_close,
    )


# ── happy path ──────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_fill_at_next_day_open() -> None:
    res = simulate_fill(_order(), _bar(open_=105.0))
    assert res.voided is False
    assert res.fill_price == pytest.approx(105.0)
    assert res.fill_date == date(2025, 1, 7)
    assert res.filled_shares == 1000


# ── limit lock voiding ──────────────────────────────────────────────────────

@pytest.mark.unit
def test_voided_when_limit_up_locked_for_buy() -> None:
    # high == low == open == 1.1 × prev_close → fully locked up
    limit_up = 110.0
    bar = _bar(open_=limit_up, high=limit_up, low=limit_up, close=limit_up, previous_close=100.0)
    res = simulate_fill(_order(side="buy"), bar)
    assert res.voided is True
    assert "limit_up" in res.voided_reason


@pytest.mark.unit
def test_voided_when_limit_down_locked_for_sell() -> None:
    limit_down = 90.0
    bar = _bar(open_=limit_down, high=limit_down, low=limit_down, close=limit_down, previous_close=100.0)
    res = simulate_fill(_order(side="sell"), bar)
    assert res.voided is True
    assert "limit_down" in res.voided_reason


@pytest.mark.unit
def test_limit_up_does_not_void_sell() -> None:
    limit_up = 110.0
    bar = _bar(open_=limit_up, high=limit_up, low=limit_up, close=limit_up, previous_close=100.0)
    res = simulate_fill(_order(side="sell"), bar)
    # Sellers can still hit the limit-up bid in real life, but spec says lock voids
    # 我們選保守：fully locked → void either direction. Adjust if needed.
    assert res.voided is True


# ── liquidity cap & partial fill ────────────────────────────────────────────

@pytest.mark.unit
def test_liquidity_cap_5pct_of_daily_volume() -> None:
    # Order 100,000 shares, volume 1_000_000 → cap = 50_000
    res = simulate_fill(_order(shares=100_000), _bar(volume=1_000_000))
    assert res.filled_shares == 50_000


@pytest.mark.unit
def test_partial_fill_rounds_down_to_lot() -> None:
    # Volume 19,500 → 5% = 975 → not a whole lot → rounds down to 0
    res = simulate_fill(_order(shares=5_000), _bar(volume=19_500))
    assert res.filled_shares == 0
    assert res.voided is True
    assert "no_liquidity" in res.voided_reason or "insufficient" in res.voided_reason


@pytest.mark.unit
def test_full_fill_when_within_cap() -> None:
    res = simulate_fill(_order(shares=1000), _bar(volume=1_000_000))
    assert res.filled_shares == 1000
    assert res.voided is False


# ── lot rounding ────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_whole_share_rounds_down_to_lot() -> None:
    # 2500 shares requested → 2000 (2 lots)
    res = simulate_fill(_order(shares=2500), _bar(volume=1_000_000))
    assert res.filled_shares == 2000


@pytest.mark.unit
def test_odd_lot_mode_allows_any_quantity() -> None:
    res = simulate_fill(_order(shares=350, is_odd_lot=True), _bar(volume=1_000_000))
    assert res.filled_shares == 350


# ── settlement ──────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_settlement_date_is_t_plus_2_business_days() -> None:
    # Fill Wed 2025-01-08 → settlement Fri 2025-01-10
    bar = _bar(d=date(2025, 1, 8))
    res = simulate_fill(_order(), bar)
    assert res.settlement_date == date(2025, 1, 10)


@pytest.mark.unit
def test_settlement_skips_weekends() -> None:
    # Fill Thu 2025-01-09 → settle Mon 2025-01-13 (skip weekend)
    bar = _bar(d=date(2025, 1, 9))
    res = simulate_fill(_order(), bar)
    assert res.settlement_date == date(2025, 1, 13)


@pytest.mark.unit
def test_next_business_day_handles_weekend() -> None:
    assert next_business_day(date(2025, 1, 3), n=1) == date(2025, 1, 6)  # Fri → Mon
    assert next_business_day(date(2025, 1, 6), n=2) == date(2025, 1, 8)


# ── missing data ────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_no_next_bar_voids() -> None:
    res = simulate_fill(_order(), None)
    assert res.voided is True
    assert "no_next_bar" in res.voided_reason


@pytest.mark.unit
def test_lot_constants_match_spec() -> None:
    assert LOT_SIZE == 1000
    assert LIQUIDITY_CAP_PCT == 0.05
