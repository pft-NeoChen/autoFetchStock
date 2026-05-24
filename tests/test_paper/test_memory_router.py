"""TASK-P01 — Memory paper router tests (V2 §8.2)."""

from __future__ import annotations

import pytest

from src.execution.order_router import (
    LiveOrder,
    OrderRouter,
    OrderState,
    UnknownOrderError,
)
from src.paper.memory_router import MemoryRouter


pytestmark = pytest.mark.unit


def _quote_provider(prices: dict[str, float]):
    def lookup(stock_id: str) -> float:
        return prices[stock_id]
    return lookup


def _mkorder(stock_id: str = "2330", side: str = "buy", shares: int = 1000) -> LiveOrder:
    return LiveOrder(stock_id=stock_id, side=side, shares=shares)  # type: ignore[arg-type]


def test_memory_router_satisfies_order_router_protocol() -> None:
    router = MemoryRouter(initial_cash=1_000_000.0, quote_provider=lambda sid: 600.0)
    assert isinstance(router, OrderRouter)


def test_submit_market_buy_fills_immediately_and_creates_position() -> None:
    router = MemoryRouter(
        initial_cash=1_000_000.0,
        quote_provider=_quote_provider({"2330": 600.0}),
    )
    oid = router.submit(_mkorder())
    status = router.query(oid)
    assert status.state == OrderState.FILLED
    assert status.filled_shares == 1000
    assert status.avg_fill_price == pytest.approx(600.0)

    positions = router.positions()
    assert len(positions) == 1
    pos = positions[0]
    assert pos.stock_id == "2330"
    assert pos.shares == 1000
    assert pos.avg_cost == pytest.approx(600.0)


def test_submit_market_sell_closes_position_and_records_pnl() -> None:
    quotes = {"2330": 600.0}
    router = MemoryRouter(
        initial_cash=2_000_000.0,
        quote_provider=lambda sid: quotes[sid],
    )
    router.submit(_mkorder(side="buy"))
    quotes["2330"] = 650.0
    sell_id = router.submit(_mkorder(side="sell"))
    assert router.query(sell_id).state == OrderState.FILLED
    assert router.positions() == []
    assert router.realized_pnl == pytest.approx((650.0 - 600.0) * 1000)


def test_submit_with_insufficient_cash_rejects() -> None:
    router = MemoryRouter(
        initial_cash=10_000.0,  # nowhere near 600 × 1000
        quote_provider=lambda sid: 600.0,
    )
    oid = router.submit(_mkorder(side="buy"))
    status = router.query(oid)
    assert status.state == OrderState.REJECTED
    assert "cash" in (status.reject_reason or "").lower()
    assert router.positions() == []


def test_submit_sell_without_position_rejects() -> None:
    router = MemoryRouter(
        initial_cash=1_000_000.0,
        quote_provider=lambda sid: 600.0,
    )
    oid = router.submit(_mkorder(side="sell"))
    status = router.query(oid)
    assert status.state == OrderState.REJECTED
    assert "no_position" in (status.reject_reason or "")


def test_cancel_on_filled_order_raises() -> None:
    router = MemoryRouter(
        initial_cash=1_000_000.0,
        quote_provider=lambda sid: 600.0,
    )
    oid = router.submit(_mkorder())
    with pytest.raises(Exception):
        router.cancel(oid)


def test_query_unknown_id_raises() -> None:
    router = MemoryRouter(
        initial_cash=1_000_000.0,
        quote_provider=lambda sid: 600.0,
    )
    with pytest.raises(UnknownOrderError):
        router.query("nope")


def test_partial_close_position() -> None:
    quotes = {"2330": 600.0}
    router = MemoryRouter(
        initial_cash=2_000_000.0,
        quote_provider=lambda sid: quotes[sid],
    )
    router.submit(_mkorder(shares=2000))
    quotes["2330"] = 620.0
    router.submit(_mkorder(side="sell", shares=1000))
    positions = router.positions()
    assert len(positions) == 1
    assert positions[0].shares == 1000
    # avg_cost unchanged on partial close
    assert positions[0].avg_cost == pytest.approx(600.0)
    # realized: 1000 × (620-600)
    assert router.realized_pnl == pytest.approx(20_000.0)


def test_quote_lookup_failure_rejects_order() -> None:
    def bad_quote(sid: str) -> float:
        raise KeyError(sid)

    router = MemoryRouter(initial_cash=1_000_000.0, quote_provider=bad_quote)
    oid = router.submit(_mkorder())
    status = router.query(oid)
    assert status.state == OrderState.REJECTED
    assert "quote" in (status.reject_reason or "").lower()
