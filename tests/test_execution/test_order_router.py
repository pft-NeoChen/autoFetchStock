"""TASK-X01 RED tests — OrderRouter + DryRunRouter (V2 §10)."""

from __future__ import annotations

from datetime import datetime

import pytest

from src.execution.order_router import (
    DryRunRouter,
    LiveOrder,
    OrderRouter,
    OrderState,
    UnknownOrderError,
)


pytestmark = pytest.mark.unit


# --- LiveOrder validation ------------------------------------------------


def test_live_order_market_default_valid():
    order = LiveOrder(stock_id="2330", side="buy", shares=1000)
    assert order.order_type == "market"
    assert order.limit_price is None


def test_live_order_limit_requires_price():
    with pytest.raises(ValueError, match="limit_price"):
        LiveOrder(stock_id="2330", side="buy", shares=1000, order_type="limit")


def test_live_order_market_rejects_limit_price():
    with pytest.raises(ValueError, match="market"):
        LiveOrder(
            stock_id="2330", side="buy", shares=1000, limit_price=600.0
        )


def test_live_order_zero_shares_raises():
    with pytest.raises(ValueError, match="shares"):
        LiveOrder(stock_id="2330", side="buy", shares=0)


# --- Protocol conformance ------------------------------------------------


def test_dry_run_router_satisfies_order_router_protocol():
    router = DryRunRouter()
    assert isinstance(router, OrderRouter)


# --- DryRunRouter behaviour ---------------------------------------------


def _mkorder(side: str = "buy") -> LiveOrder:
    return LiveOrder(
        stock_id="2330",
        side=side,
        shares=1000,
        submitted_at=datetime(2026, 5, 23, 9, 5, 0),
    )


def test_dry_run_submit_returns_unique_ids():
    router = DryRunRouter()
    a = router.submit(_mkorder())
    b = router.submit(_mkorder())
    assert a != b
    assert isinstance(a, str)
    assert a.startswith("DRY")


def test_dry_run_submit_with_custom_prefix():
    router = DryRunRouter(id_prefix="SIM")
    oid = router.submit(_mkorder())
    assert oid.startswith("SIM")


def test_dry_run_submit_records_log_entry():
    router = DryRunRouter()
    oid = router.submit(_mkorder())
    events = [e.event for e in router.log]
    assert "submit" in events
    assert any(e.order_id == oid for e in router.log)


def test_dry_run_query_returns_submitted_state():
    router = DryRunRouter()
    oid = router.submit(_mkorder())
    status = router.query(oid)
    assert status.order_id == oid
    assert status.state == OrderState.SUBMITTED
    assert status.filled_shares == 0
    assert status.avg_fill_price is None


def test_dry_run_query_unknown_id_raises():
    router = DryRunRouter()
    with pytest.raises(UnknownOrderError):
        router.query("nope")


def test_dry_run_cancel_marks_cancelled():
    router = DryRunRouter()
    oid = router.submit(_mkorder())
    router.cancel(oid)
    assert router.query(oid).state == OrderState.CANCELLED
    events = [e.event for e in router.log]
    assert "cancel" in events


def test_dry_run_cancel_unknown_id_raises():
    router = DryRunRouter()
    with pytest.raises(UnknownOrderError):
        router.cancel("nope")


def test_dry_run_cancel_terminal_state_raises():
    router = DryRunRouter()
    oid = router.submit(_mkorder())
    router.cancel(oid)
    with pytest.raises(Exception):
        router.cancel(oid)


def test_dry_run_positions_always_empty():
    router = DryRunRouter()
    router.submit(_mkorder("buy"))
    router.submit(_mkorder("sell"))
    assert router.positions() == []


def test_dry_run_multiple_orders_tracked_independently():
    router = DryRunRouter()
    o1 = router.submit(_mkorder("buy"))
    o2 = router.submit(_mkorder("sell"))
    router.cancel(o1)
    assert router.query(o1).state == OrderState.CANCELLED
    assert router.query(o2).state == OrderState.SUBMITTED
