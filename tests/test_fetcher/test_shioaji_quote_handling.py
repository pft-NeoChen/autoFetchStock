"""
Unit tests for Shioaji quote handling behavior.
"""

import threading
from datetime import datetime
from types import SimpleNamespace

import shioaji as sj

from src.fetcher.shioaji_fetcher import ShioajiFetcher


def _make_fetcher() -> ShioajiFetcher:
    fetcher = object.__new__(ShioajiFetcher)
    fetcher._subscriptions = {
        "2330": {
            "name": "台積電",
            "reference": 100.0,
            "contract": SimpleNamespace(limit_up=110.0, limit_down=90.0),
        }
    }
    fetcher._last_quotes = {}
    fetcher._last_bidask = {}
    fetcher._subscription_failures = {}
    fetcher._active_streams = {}
    fetcher._subscription_lock = threading.RLock()
    fetcher._on_quote_callback = None
    fetcher._on_tick_callback = None
    return fetcher


def test_handle_quote_keeps_simtrade_quote_for_display_cache():
    fetcher = _make_fetcher()
    source_time = datetime(2026, 4, 23, 9, 1, 2, 345678)
    quote = SimpleNamespace(
        code="2330",
        datetime=source_time,
        simtrade=True,
        close=101.0,
        open=100.0,
        high=102.0,
        low=99.0,
        total_volume=1234,
        volume=15,
        bid_price=[100.5],
        ask_price=[101.0],
        bid_volume=[50],
        ask_volume=[60],
        bid_side_total_vol=300,
        ask_side_total_vol=400,
    )

    fetcher._handle_quote(None, quote)

    cached = fetcher._last_quotes["2330"]
    assert cached.current_price == 101.0
    assert cached.is_simtrade is True
    assert cached.timestamp == source_time


def test_handle_tick_uses_shioaji_total_volume_as_accumulated_volume():
    fetcher = _make_fetcher()
    received = []
    source_time = datetime(2026, 4, 23, 9, 2, 3, 456789)
    fetcher._on_tick_callback = received.append
    tick = SimpleNamespace(
        code="2330",
        datetime=source_time,
        simtrade=False,
        close=101.5,
        volume=7,
        total_volume=12345,
        tick_type=1,
        intraday_odd=False,
    )

    fetcher._handle_tick(None, tick)

    assert len(received) == 1
    assert received[0].volume == 7
    assert received[0].accumulated_volume == 12345
    assert received[0].timestamp == source_time


def test_handle_tick_refreshes_realtime_quote_cache():
    fetcher = _make_fetcher()
    source_time = datetime(2026, 4, 23, 9, 2, 3, 456789)
    tick = SimpleNamespace(
        code="2330",
        datetime=source_time,
        simtrade=False,
        close=101.5,
        open=100.0,
        high=102.0,
        low=99.5,
        volume=7,
        total_volume=12345,
        tick_type=1,
        price_chg=1.5,
        pct_chg=1.5,
        intraday_odd=False,
    )

    fetcher._handle_tick(None, tick)

    cached = fetcher._last_quotes["2330"]
    assert cached.current_price == 101.5
    assert cached.total_volume == 12345
    assert cached.tick_volume == 7
    assert cached.timestamp == source_time


def test_tick_subscription_error_disables_subscribed_state():
    fetcher = _make_fetcher()

    fetcher._handle_event(
        0,
        4,
        "TIC/v1/STK/*/TSE/2330",
        "Subscription problem on session",
    )

    assert fetcher.is_subscribed("2330") is False


def test_bidask_subscription_error_keeps_tick_subscription_active():
    fetcher = _make_fetcher()

    fetcher._handle_event(
        0,
        4,
        "QUO/v2/STK/*/TSE/2330",
        "Subscription problem on session",
    )

    assert fetcher.is_subscribed("2330") is True


def test_subscribe_uses_tick_and_bidask_streams():
    fetcher = _make_fetcher()
    fetcher.is_connected = True
    fetcher._subscriptions = {}
    contract = SimpleNamespace(name="台積電", reference=100.0)
    calls = []

    fetcher.api = SimpleNamespace(
        Contracts=SimpleNamespace(Stocks={"2330": contract}),
        quote=SimpleNamespace(
            subscribe=lambda contract, quote_type, version: calls.append(quote_type)
        ),
    )

    assert fetcher.subscribe("2330") is True
    assert calls == [sj.constant.QuoteType.Tick, sj.constant.QuoteType.BidAsk]


def test_subscribe_skips_duplicate_active_subscription():
    fetcher = _make_fetcher()
    fetcher.is_connected = True
    calls = []
    fetcher.api = SimpleNamespace(
        Contracts=SimpleNamespace(Stocks={}),
        quote=SimpleNamespace(
            subscribe=lambda contract, quote_type, version: calls.append(quote_type)
        ),
    )

    assert fetcher.subscribe("2330") is True
    assert calls == []
