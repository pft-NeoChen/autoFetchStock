"""
Unit tests for favorites sidebar rendering helpers.
"""

from datetime import datetime
from unittest.mock import MagicMock

from src.app.callbacks import CallbackManager
from src.models import PriceDirection, RealtimeQuote


def _make_quote(
    current_price: float = 103.0,
    open_price: float = 100.0,
    high_price: float = 105.0,
    low_price: float = 99.0,
    is_simtrade: bool = False,
) -> RealtimeQuote:
    return RealtimeQuote(
        stock_id="2330",
        stock_name="台積電",
        current_price=current_price,
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        previous_close=98.0,
        change_amount=current_price - 98.0,
        change_percent=round(((current_price - 98.0) / 98.0) * 100, 2),
        direction=PriceDirection.UP,
        total_volume=1234,
        tick_volume=12,
        best_bid=current_price - 0.5,
        best_ask=current_price + 0.5,
        timestamp=datetime.now(),
        is_simtrade=is_simtrade,
    )


class TestFavoritesSidebarHelpers:
    def setup_method(self):
        self.fetcher = MagicMock()
        self.fetcher.get_cached_quote.return_value = None
        self.storage = MagicMock()
        self.manager = CallbackManager(
            app=None,
            fetcher=self.fetcher,
            storage=self.storage,
            processor=MagicMock(),
            renderer=MagicMock(),
            scheduler=MagicMock(),
        )

    def test_render_favorite_item_hides_stock_id_and_includes_kbar(self):
        self.fetcher.fetch_realtime_quote.return_value = _make_quote()

        item = self.manager._render_favorite_item(
            {"id": "2330", "name": "台積電"},
            current_stock="2330",
        )

        left = item.children[0]
        kbar = left.children[0]
        name = left.children[1]
        price = item.children[1]

        assert kbar.className == "favorite-item-kbar"
        assert name.children == "台積電"
        assert "2330" not in name.children
        assert price.children == "103.00"

    def test_render_favorite_item_uses_cached_quote_without_wiping_price(self):
        self.fetcher.get_cached_quote.return_value = _make_quote(current_price=101.5)

        item = self.manager._render_favorite_item(
            {"id": "2330", "name": "台積電"},
            current_stock=None,
        )

        assert item.children[1].children == "101.50"
        self.fetcher.fetch_realtime_quote.assert_not_called()

    def test_save_quote_as_tick_skips_simtrade_quotes(self):
        simtrade_quote = _make_quote(is_simtrade=True)

        self.manager._save_quote_as_tick(simtrade_quote)

        self.storage.save_intraday_data.assert_not_called()

    def test_save_quote_as_tick_does_not_treat_first_total_volume_as_single_tick(self):
        quote = _make_quote()
        quote.total_volume = 1234
        quote.tick_volume = 12
        self.storage.load_intraday_data.return_value = None

        self.manager._save_quote_as_tick(quote)

        saved_tick = self.storage.save_intraday_data.call_args.kwargs["ticks"][0]
        assert saved_tick.volume == 12
        assert saved_tick.accumulated_volume == 1234
