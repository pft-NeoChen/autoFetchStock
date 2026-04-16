"""
Unit tests for Shioaji quote handling behavior.
"""

from types import SimpleNamespace

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
    fetcher._on_quote_callback = None
    fetcher._on_tick_callback = None
    return fetcher


def test_handle_quote_keeps_simtrade_quote_for_display_cache():
    fetcher = _make_fetcher()
    quote = SimpleNamespace(
        code="2330",
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
