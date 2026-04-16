"""
Unit tests for realtime quote caching fallback behavior.
"""

from datetime import datetime
from unittest.mock import MagicMock

from src.fetcher.data_fetcher import DataFetcher
from src.models import PriceDirection, RealtimeQuote, StockInfo


def _make_quote() -> RealtimeQuote:
    return RealtimeQuote(
        stock_id="2330",
        stock_name="台積電",
        current_price=100.0,
        open_price=99.0,
        high_price=101.0,
        low_price=98.5,
        previous_close=98.0,
        change_amount=2.0,
        change_percent=2.04,
        direction=PriceDirection.UP,
        total_volume=1000,
        tick_volume=10,
        best_bid=99.5,
        best_ask=100.0,
        timestamp=datetime.now(),
    )


def test_fetch_realtime_quote_returns_cached_value_on_nonblocking_rate_limit():
    fetcher = DataFetcher()
    fetcher._stock_list_cache = [StockInfo(stock_id="2330", stock_name="台積電")]
    fetcher._stock_list_cache_time = datetime.now()
    fetcher._realtime_quote_cache["2330"] = _make_quote()
    fetcher._make_request = MagicMock(side_effect=BlockingIOError("Rate limit exceeded"))

    quote = fetcher.fetch_realtime_quote("2330", blocking=False)

    assert quote is fetcher._realtime_quote_cache["2330"]
