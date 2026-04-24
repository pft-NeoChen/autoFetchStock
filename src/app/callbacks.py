"""
Dash callbacks for autoFetchStock.

This module implements all Dash callback functions:
- Stock search and selection
- Tab switching
- K-line period changes
- Auto-update mechanism
- OHLC hover display
- Error handling
"""

import logging
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from typing import Any, Dict, List, Optional, Tuple

from dash import callback, Output, Input, State, no_update, html, ctx, ALL
from dash.exceptions import PreventUpdate

from src.models import KlinePeriod, PriceDirection, IntradayTick, RealtimeQuote
from src.exceptions import (
    ConnectionTimeoutError,
    InvalidDataError,
    StockNotFoundError,
    ServiceUnavailableError,
)

logger = logging.getLogger("autofetchstock.app")


class CallbackManager:
    """
    Manages Dash callbacks and their dependencies.

    This class holds references to the application components
    (fetcher, storage, processor, renderer, scheduler) and
    registers all callbacks with the Dash app.
    """

    def __init__(self, app, fetcher, storage, processor, renderer, scheduler,
                 shioaji_fetcher=None, news_processor=None):
        """
        Initialize callback manager.

        Args:
            app: Dash application instance
            fetcher: DataFetcher instance
            storage: DataStorage instance
            processor: DataProcessor instance
            renderer: ChartRenderer instance
            scheduler: Scheduler instance
            shioaji_fetcher: ShioajiFetcher instance (optional)
            news_processor: NewsProcessor instance (optional)
        """
        self.app = app
        self.fetcher = fetcher
        self.shioaji_fetcher = shioaji_fetcher
        self.storage = storage
        self.processor = processor
        self.renderer = renderer
        self.scheduler = scheduler
        self.news_processor = news_processor
        self._current_stock_id: Optional[str] = None
        self._current_stock_name: Optional[str] = None

    def register_callbacks(self) -> None:
        """Register all Dash callbacks."""
        self._register_search_callbacks()
        self._register_tab_callbacks()
        self._register_period_callbacks()
        self._register_update_callbacks()
        self._register_hover_callbacks()
        self._register_error_callbacks()
        self._register_favorites_callbacks()
        self._register_news_callbacks()
        logger.info("All callbacks registered")

    def _build_favorite_kbar(self, quote: Optional[RealtimeQuote]) -> html.Div:
        """Build a compact day-candle marker for the favorites list."""
        bar_height = 28
        body_class = "price-flat"
        wick_top = 2
        wick_height = bar_height - 4
        body_top = (bar_height // 2) - 2
        body_height = 4

        if quote:
            current_price = quote.current_price
            open_price = (
                quote.open_price
                if quote.open_price is not None and quote.open_price > 0
                else (quote.previous_close or current_price)
            )
            high_candidates = [p for p in (quote.high_price, open_price, current_price) if p and p > 0]
            low_candidates = [p for p in (quote.low_price, open_price, current_price) if p and p > 0]
            high_price = max(high_candidates) if high_candidates else current_price
            low_price = min(low_candidates) if low_candidates else current_price

            if current_price > open_price:
                body_class = "price-up"
            elif current_price < open_price:
                body_class = "price-down"

            if high_price > low_price:
                usable_height = bar_height - 4
                price_range = high_price - low_price
                body_high = max(open_price, current_price)
                body_low = min(open_price, current_price)
                body_top = round(((high_price - body_high) / price_range) * usable_height) + 2
                body_height = max(4, round(((body_high - body_low) / price_range) * usable_height))
                max_top = max(2, bar_height - 2 - body_height)
                body_top = min(max(body_top, 2), max_top)

        return html.Div(
            className="favorite-item-kbar",
            children=[
                html.Span(
                    className=f"favorite-kbar-wick {body_class}",
                    style={"top": f"{wick_top}px", "height": f"{wick_height}px"},
                ),
                html.Span(
                    className=f"favorite-kbar-body {body_class}",
                    style={"top": f"{body_top}px", "height": f"{body_height}px"},
                ),
            ],
        )

    def _render_favorite_item(self, favorite: dict, current_stock: Optional[str]) -> html.Div:
        """Render a single item in the favorites list."""
        stock_id = favorite["id"]
        is_active = stock_id == current_stock

        quote = None
        price_text = "--"
        price_class = "favorite-item-price"
        item_class = f"favorite-item{' active' if is_active else ''}"

        try:
            if self.fetcher:
                get_cached_quote = getattr(self.fetcher, "get_cached_quote", None)
                if callable(get_cached_quote):
                    quote = get_cached_quote(stock_id)

                # Using blocking=False to avoid UI freeze if many favorites use TWSE.
                # The fetcher now falls back to its last cached quote instead of
                # wiping the UI back to "--" when rate-limited.
                if quote is None:
                    quote = self.fetcher.fetch_realtime_quote(stock_id, blocking=False)
            if quote:
                price_text = f"{quote.current_price:.2f}"
                if quote.change_amount > 0:
                    price_class += " price-up"
                elif quote.change_amount < 0:
                    price_class += " price-down"
                else:
                    price_class += " price-flat"

                if quote.limit_up_price > 0 and quote.current_price >= quote.limit_up_price:
                    item_class += " limit-up-bg"
                elif quote.limit_down_price > 0 and quote.current_price <= quote.limit_down_price:
                    item_class += " limit-down-bg"
        except Exception:
            quote = None

        return html.Div(
            id={"type": "favorite-item", "index": stock_id},
            className=item_class,
            children=[
                html.Div(
                    className="favorite-item-main",
                    children=[
                        self._build_favorite_kbar(quote),
                        html.Span(favorite["name"], className="favorite-item-text"),
                    ],
                ),
                html.Span(price_text, className=price_class),
            ],
            n_clicks=0,
            draggable="true",
            **{"data-stock-id": stock_id},
        )

    def _register_favorites_callbacks(self) -> None:
        """Register favorites related callbacks."""

        @self.app.callback(
            Output("app-state-store", "data", allow_duplicate=True),
            Input("main-container", "id"),
            State("app-state-store", "data"),
            prevent_initial_call='initial_duplicate'
        )
        def load_initial_favorites(_, current_state: dict):
            """Load favorites from storage on initial load."""
            favorites = self.storage.load_favorites()
            if not favorites:
                return no_update
            
            new_state = current_state.copy()
            new_state["favorites"] = favorites
            
            # Subscribe to Shioaji for all favorites
            if self.shioaji_fetcher and self.shioaji_fetcher.is_connected:
                for fav in favorites:
                    self.shioaji_fetcher.subscribe(fav["id"])
            
            # Also add all favorites to scheduler for background fetching (fallback)
            for fav in favorites:
                self.scheduler.add_stock_job(fav["id"])
                
            return new_state

        @self.app.callback(
            Output("app-state-store", "data", allow_duplicate=True),
            Output("stock-star-toggle", "className"),
            Input("stock-star-toggle", "n_clicks"),
            State("app-state-store", "data"),
            prevent_initial_call=True
        )
        def on_star_click(n_clicks: int, current_state: dict):
            """Handle clicking the favorite star button."""
            if n_clicks is None:
                raise PreventUpdate

            stock_id = current_state.get("current_stock")
            if not stock_id:
                raise PreventUpdate

            favorites = current_state.get("favorites", [])
            
            # Check if already in favorites
            fav_ids = [f["id"] for f in favorites]
            is_favorite = stock_id in fav_ids

            if is_favorite:
                # Remove from favorites
                favorites = [f for f in favorites if f["id"] != stock_id]
                star_class = "star-button"
                # Unsubscribe from Shioaji if not current stock
                # (But current_stock IS stock_id here, so we might want to keep subscription for main view)
                # Ideally, main view manages its own subscription.
                # If we remove from favorites, we just let it be. 
                # If user navigates away, main view subscription logic handles it.
                logger.info(f"Removed {stock_id} from favorites")
            else:
                # Add to favorites
                favorites.append({
                    "id": stock_id,
                    "name": self._current_stock_name or stock_id
                })
                star_class = "star-button active"
                # Subscribe to Shioaji
                if self.shioaji_fetcher and self.shioaji_fetcher.is_connected:
                    self.shioaji_fetcher.subscribe(stock_id)
                logger.info(f"Added {stock_id} to favorites")

            # Update state and save to storage
            new_state = current_state.copy()
            new_state["favorites"] = favorites
            self.storage.save_favorites(favorites)

            return new_state, star_class

        @self.app.callback(
            Output("favorites-list", "children"),
            Input("app-state-store", "data"),
            Input("favorites-update-interval", "n_intervals")
        )
        def render_favorites_list(app_state: dict, n_intervals: int):
            """Render the favorites list sidebar."""
            favorites = app_state.get("favorites", [])
            current_stock = app_state.get("current_stock")

            if not favorites:
                return html.Div("尚未加入最愛", className="no-favorites")

            return [self._render_favorite_item(fav, current_stock) for fav in favorites]

        @self.app.callback(
            Output("stock-search-input", "value", allow_duplicate=True),
            Output("stock-search-button", "n_clicks"),
            Input({"type": "favorite-item", "index": ALL}, "n_clicks"),
            State("stock-search-button", "n_clicks"),
            prevent_initial_call=True
        )
        def on_favorite_click(n_clicks_list, current_search_clicks):
            """Handle clicking an item in the favorites list."""
            if not any(n_clicks_list):
                raise PreventUpdate

            # Find which item was clicked
            triggered = ctx.triggered_id
            if not triggered or not isinstance(triggered, dict):
                raise PreventUpdate
            
            stock_id = triggered.get("index")
            if not stock_id:
                raise PreventUpdate

            # Set search input and trigger search button
            return stock_id, (current_search_clicks or 0) + 1

        # ── Drag-and-drop reorder ────────────────────────────────────────────

        # Clientside: on hidden button click, read window._favoritesOrder and
        # push it into the store so the Python callback can persist it.
        self.app.clientside_callback(
            """
            function(n) {
                if (!window._favoritesOrder) {
                    return window.dash_clientside.no_update;
                }
                var order = window._favoritesOrder;
                window._favoritesOrder = null;
                return order;
            }
            """,
            Output("favorites-order-store", "data"),
            Input("favorites-reorder-btn", "n_clicks"),
            prevent_initial_call=True,
        )

        @self.app.callback(
            Output("app-state-store", "data", allow_duplicate=True),
            Input("favorites-order-store", "data"),
            State("app-state-store", "data"),
            prevent_initial_call=True,
        )
        def on_favorites_reorder(new_order, app_state):
            """Persist drag-and-drop reordered favorites list."""
            if not new_order or not app_state:
                raise PreventUpdate

            current_favorites = app_state.get("favorites", [])
            fav_map = {f["id"]: f for f in current_favorites}

            # Rebuild list in dropped order; keep any IDs not in new_order at end
            reordered = [fav_map[sid] for sid in new_order if sid in fav_map]
            seen = set(new_order)
            for fav in current_favorites:
                if fav["id"] not in seen:
                    reordered.append(fav)

            self.storage.save_favorites(reordered)
            logger.info(f"Favorites reordered: {[f['id'] for f in reordered]}")

            new_state = dict(app_state)
            new_state["favorites"] = reordered
            return new_state

        @self.app.callback(
            Output("stock-search-input", "value", allow_duplicate=True),
            Output("stock-search-button", "n_clicks", allow_duplicate=True),
            Input({"type": "match-item", "index": ALL}, "n_clicks"),
            State("stock-search-button", "n_clicks"),
            prevent_initial_call=True
        )
        def on_match_item_click(n_clicks_list, current_search_clicks):
            """Handle clicking an item in the search match list."""
            if not any(n_clicks_list):
                raise PreventUpdate

            # Find which item was clicked
            triggered = ctx.triggered_id
            if not triggered or not isinstance(triggered, dict):
                raise PreventUpdate
            
            stock_id = triggered.get("index")
            if not stock_id:
                raise PreventUpdate

            # Set search input and trigger search button
            return stock_id, (current_search_clicks or 0) + 1

    def _register_search_callbacks(self) -> None:
        """Register stock search related callbacks."""

        @self.app.callback(
            Output("stock-match-list", "children"),
            Output("stock-match-list", "style"),
            Input("stock-search-input", "value"),
            prevent_initial_call=True
        )
        def on_search_input(search_value: str):
            """Handle search input changes (REQ-012)."""
            logger.debug(f"Search input: '{search_value}'")
            if not search_value or len(search_value.strip()) < 1:
                return [], {"display": "none"}

            try:
                results = self.fetcher.search_stock(search_value)
                logger.debug(f"Search returned {len(results)} results")

                if not results:
                    return [
                        html.Div("查無符合的股票", className="match-item")
                    ], {"display": "block"}

                items = [
                    html.Div(
                        id={"type": "match-item", "index": stock.stock_id},
                        className="match-item",
                        children=[
                            html.Span(stock.stock_id, className="match-item-id"),
                            html.Span(stock.stock_name, className="match-item-name"),
                        ],
                        n_clicks=0,
                    )
                    for stock in results[:10]
                ]

                return items, {"display": "block"}

            except Exception as e:
                logger.error(f"Search error: {e}")
                return [
                    html.Div(f"搜尋發生錯誤", className="match-item")
                ], {"display": "block"}

        @self.app.callback(
            Output("stock-name-display", "children"),
            Output("stock-id-display", "children"),
            Output("stock-price-display", "children"),
            Output("stock-price-display", "className"),
            Output("stock-change-display", "children"),
            Output("stock-change-display", "className"),
            Output("stock-volume-display", "children"),
            Output("last-update-display", "children"),
            Output("app-state-store", "data"),
            Output("auto-update-interval", "disabled"),
            Output("stock-match-list", "style", allow_duplicate=True),
            Output("intraday-chart", "figure", allow_duplicate=True),
            Output("kline-chart", "figure", allow_duplicate=True),
            Output("stock-star-toggle", "className", allow_duplicate=True),
            Input("stock-search-button", "n_clicks"),
            State("stock-search-input", "value"),
            State("app-state-store", "data"),
            State("period-selector", "value"),
            prevent_initial_call=True
        )
        def on_search_submit(n_clicks: int, search_value: str, current_state: dict, period_value: str):
            """Handle search button click - select a stock."""
            if not n_clicks or not search_value:
                raise PreventUpdate

            try:
                # Resolve submit text into a concrete stock first. Exact names
                # such as "國巨" should map to the underlying stock code.
                stock = self.fetcher.resolve_stock(search_value)
                stock_id = stock.stock_id

                # Fetch realtime quote (blocking is fine for search submit)
                quote = self.fetcher.fetch_realtime_quote(stock_id)

                # Check if in favorites (Needed for unsubscription logic)
                favorites = current_state.get("favorites", [])
                fav_ids = [f["id"] for f in favorites]

                # Subscribe to Shioaji streaming if available
                is_using_shioaji = False
                if self.shioaji_fetcher and self.shioaji_fetcher.is_connected:
                    # Unsubscribe previous if changed AND not in favorites
                    if self._current_stock_id and self._current_stock_id != stock_id:
                        # If previous stock is a favorite, keep subscription!
                        if self._current_stock_id not in fav_ids:
                            self.shioaji_fetcher.unsubscribe(self._current_stock_id)
                    
                    self.shioaji_fetcher.subscribe(stock_id)
                    is_using_shioaji = True

                # Update internal state
                self._current_stock_id = stock_id
                self._current_stock_name = quote.stock_name

                # Check if in favorites (for star button)
                is_favorite = any(f["id"] == stock_id for f in favorites)
                star_class = "star-button active" if is_favorite else "star-button"

                # Save as intraday tick for chart (Immediate update)
                # Skip if using Shioaji (AppController handles streaming ticks)
                if not is_using_shioaji:
                    self._save_quote_as_tick(quote)

                # Add to scheduler for background updates
                self.scheduler.add_stock_job(stock_id)

                # Update app state - Trigger background sync via 'needs_history_sync'
                new_state = current_state.copy() if current_state else {}
                new_state["current_stock"] = stock_id
                new_state["needs_history_sync"] = stock_id  # Flag to trigger sync callback

                # Determine price direction class
                direction_class = self._get_direction_class(quote.direction)
                change_text = f"{'+' if quote.change_amount >= 0 else ''}{quote.change_amount:.2f} ({'+' if quote.change_percent >= 0 else ''}{quote.change_percent:.2f}%)"

                # Render intraday chart with CURRENT local data (Fast)
                intraday_data = self.storage.load_intraday_data(stock_id, date.today())
                big_orders_items = []
                
                if intraday_data and intraday_data.ticks:
                    df = self.processor.prepare_intraday_data(intraday_data.ticks)
                    intraday_figure = self.renderer.render_intraday_chart(
                        df,
                        f"{quote.stock_name} ({stock_id})",
                        quote.previous_close
                    )
                    
                    # Generate Big Orders List (Newest at Top)
                    if "is_big_buy" in df.columns:
                        big_orders = df[df["is_big_buy"] | df["is_big_sell"]]
                        # Reverse iteration to show newest first
                        for _, row in big_orders.iloc[::-1].iterrows():
                            is_buy = row["is_big_buy"]
                            vol_class = "big-order-volume big-buy" if is_buy else "big-order-volume big-sell"
                            time_str = row["time"].strftime("%H:%M:%S") if isinstance(row["time"], datetime) else str(row["time"])
                            
                            big_orders_items.append(
                                html.Div(
                                    className="big-order-item",
                                    children=[
                                        html.Span(time_str, className="big-order-time"),
                                        html.Span(f"{row['tick_vol_calc']:.0f}", className=vol_class),
                                    ]
                                )
                            )
                        if not big_orders_items:
                            big_orders_items = [html.Div("尚無大戶資料", className="no-data")]
                else:
                    intraday_figure = self.renderer.render_empty_chart("載入中...")
                    big_orders_items = [html.Div("尚無大戶資料", className="no-data")]

                # Render K-line chart with EXISTING local data (Fast)
                daily_file = self.storage.load_daily_data(stock_id)
                if daily_file and daily_file.daily_data:
                    period_map = {
                        "daily": KlinePeriod.DAILY,
                        "weekly": KlinePeriod.WEEKLY,
                        "monthly": KlinePeriod.MONTHLY,
                        "min_1": KlinePeriod.MIN_1,
                        "min_5": KlinePeriod.MIN_5,
                        "min_15": KlinePeriod.MIN_15,
                        "min_30": KlinePeriod.MIN_30,
                        "min_60": KlinePeriod.MIN_60,
                    }
                    period = period_map.get(period_value, KlinePeriod.DAILY)
                    kline_df = self.processor.prepare_kline_data(
                        daily_file.daily_data, 
                        period,
                        realtime_quote=quote
                    )
                    kline_figure = self.renderer.render_kline_chart(
                        kline_df,
                        f"{quote.stock_name} ({stock_id})",
                        period.display_name
                    )
                else:
                    # If no daily data yet, still try to render a 1-day chart with just the quote
                    kline_df = self.processor.prepare_kline_data(
                        [], 
                        KlinePeriod.DAILY,
                        realtime_quote=quote
                    )
                    if not kline_df.empty:
                        kline_figure = self.renderer.render_kline_chart(
                            kline_df,
                            f"{quote.stock_name} ({stock_id})",
                            "日K"
                        )
                    else:
                        kline_figure = self.renderer.render_empty_chart("同步資料中...")

                return (
                    quote.stock_name,  # stock name
                    f"({stock_id})",  # stock id
                    f"{quote.current_price:.2f}",  # price
                    f"stock-price {direction_class}",  # price class
                    change_text,  # change
                    f"stock-change {direction_class}",  # change class
                    f"{quote.total_volume:,} 張",  # volume
                    quote.timestamp.strftime("%H:%M:%S") if quote.timestamp else "--",  # update time
                    new_state,  # app state
                    False,  # enable auto-update
                    {"display": "none"},  # hide match list
                    intraday_figure,  # intraday chart
                    kline_figure,  # kline chart
                    star_class,  # star toggle class
                )

            except StockNotFoundError:
                logger.warning(f"Stock not found: {search_value}")
                empty_fig = self.renderer.render_empty_chart("查無此股票")
                return (
                    "--", "", "--", "stock-price", "", "stock-change",
                    "--", "--", no_update, True, {"display": "none"}, 
                    empty_fig, empty_fig, "star-button"
                )

            except Exception as e:
                logger.error(f"Error fetching stock: {e}")
                error_fig = self.renderer.render_empty_chart("搜尋發生錯誤")
                return (
                    "--", "", "--", "stock-price", "", "stock-change",
                    "--", "--", no_update, True, {"display": "none"}, 
                    error_fig, error_fig, "star-button"
                )

        @self.app.callback(
            Output("kline-chart", "figure", allow_duplicate=True),
            Output("app-state-store", "data", allow_duplicate=True),
            Input("app-state-store", "data"),
            State("period-selector", "value"),
            prevent_initial_call=True
        )
        def sync_history_data(app_state: dict, period_value: str):
            """Background sync of historical data (Incremental update)."""
            stock_id = app_state.get("needs_history_sync")
            if not stock_id:
                raise PreventUpdate

            logger.info(f"Starting background history sync for {stock_id}")
            
            # Fetch and save missing history (Smart Cache)
            # This is the heavy operation
            self._fetch_and_save_daily_history(stock_id, self._current_stock_name or stock_id)
            
            # After sync, clear the flag to prevent re-triggering
            new_state = app_state.copy()
            new_state.pop("needs_history_sync", None)
            
            # Load the updated data and render
            daily_file = self.storage.load_daily_data(stock_id)
            if daily_file:
                # Fetch latest quote to merge
                try:
                    quote = self.fetcher.fetch_realtime_quote(stock_id)
                except:
                    quote = None

                period_map = {
                    "daily": KlinePeriod.DAILY,
                    "weekly": KlinePeriod.WEEKLY,
                    "monthly": KlinePeriod.MONTHLY,
                    "min_1": KlinePeriod.MIN_1,
                    "min_5": KlinePeriod.MIN_5,
                    "min_15": KlinePeriod.MIN_15,
                    "min_30": KlinePeriod.MIN_30,
                    "min_60": KlinePeriod.MIN_60,
                }
                period = period_map.get(period_value, KlinePeriod.DAILY)
                df = self.processor.prepare_kline_data(
                    daily_file.daily_data, 
                    period,
                    realtime_quote=quote
                )
                figure = self.renderer.render_kline_chart(
                    df,
                    f"{daily_file.stock_name} ({stock_id})",
                    period.display_name
                )
                logger.info(f"Background sync complete for {stock_id}")
                return figure, new_state
            
            return no_update, new_state

    def _register_tab_callbacks(self) -> None:
        """Register tab switching callbacks."""

        @self.app.callback(
            Output("intraday-chart", "figure"),
            Input("main-tabs", "value"),
            State("app-state-store", "data"),
            prevent_initial_call=True
        )
        def on_tab_switch_intraday(active_tab: str, app_state: dict):
            """Handle switch to intraday tab (REQ-031)."""
            if active_tab != "intraday":
                raise PreventUpdate

            stock_id = app_state.get("current_stock") if app_state else None
            if not stock_id:
                return self.renderer.render_empty_chart("請選擇股票")

            try:
                # Get intraday data
                from datetime import date
                intraday_data = self.storage.load_intraday_data(stock_id, date.today())

                if intraday_data and intraday_data.ticks:
                    df = self.processor.prepare_intraday_data(intraday_data.ticks)
                    return self.renderer.render_intraday_chart(
                        df,
                        f"{intraday_data.stock_name} ({stock_id})",
                        intraday_data.previous_close
                    )
                else:
                    return self.renderer.render_empty_chart("暫無分時資料")

            except Exception as e:
                logger.error(f"Error rendering intraday chart: {e}")
                return self.renderer.render_empty_chart(f"載入失敗: {str(e)}")

    def _register_period_callbacks(self) -> None:
        """Register K-line period change callbacks."""

        @self.app.callback(
            Output("kline-chart", "figure"),
            Input("period-selector", "value"),
            Input("main-tabs", "value"),
            State("app-state-store", "data"),
            prevent_initial_call=True
        )
        def on_period_change(period_value: str, active_tab: str, app_state: dict):
            """Handle K-line period change (REQ-055, REQ-056)."""
            if active_tab != "kline":
                raise PreventUpdate

            stock_id = app_state.get("current_stock") if app_state else None
            if not stock_id:
                return self.renderer.render_empty_chart("請選擇股票")

            try:
                # Map period value to KlinePeriod
                period_map = {
                    "daily": KlinePeriod.DAILY,
                    "weekly": KlinePeriod.WEEKLY,
                    "monthly": KlinePeriod.MONTHLY,
                    "min_1": KlinePeriod.MIN_1,
                    "min_5": KlinePeriod.MIN_5,
                    "min_15": KlinePeriod.MIN_15,
                    "min_30": KlinePeriod.MIN_30,
                    "min_60": KlinePeriod.MIN_60,
                }
                period = period_map.get(period_value, KlinePeriod.DAILY)
                period_label = period.display_name

                # Load daily data
                daily_file = self.storage.load_daily_data(stock_id)

                if daily_file:
                    # Fetch latest quote for the current day
                    try:
                        quote = self.fetcher.fetch_realtime_quote(stock_id)
                    except:
                        quote = None

                    df = self.processor.prepare_kline_data(
                        daily_file.daily_data, 
                        period,
                        realtime_quote=quote
                    )
                    return self.renderer.render_kline_chart(
                        df,
                        f"{daily_file.stock_name} ({stock_id})",
                        period_label
                    )
                else:
                    return self.renderer.render_empty_chart("暫無K線資料")

            except Exception as e:
                logger.error(f"Error rendering K-line chart: {e}")
                return self.renderer.render_empty_chart(f"載入失敗: {str(e)}")

        @self.app.callback(
            Output("kline-chart", "figure", allow_duplicate=True),
            Input("kline-chart", "relayoutData"),
            State("app-state-store", "data"),
            State("period-selector", "value"),
            prevent_initial_call=True
        )
        def on_kline_zoom(relayout_data: dict, app_state: dict, period_value: str):
            """Handle K-line chart zoom/pan to load more historical data."""
            if not relayout_data:
                raise PreventUpdate

            stock_id = app_state.get("current_stock") if app_state else None
            if not stock_id:
                raise PreventUpdate

            # Check if this is a zoom/pan event with x-axis range
            x_range_start = None
            if "xaxis.range[0]" in relayout_data:
                x_range_start = relayout_data["xaxis.range[0]"]
            elif "xaxis.range" in relayout_data:
                x_range_start = relayout_data["xaxis.range"][0]

            if not x_range_start:
                raise PreventUpdate

            try:
                # Parse the start date from the range
                if isinstance(x_range_start, str):
                    # Handle various datetime string formats from Plotly
                    try:
                        # Try standard ISO format first
                        requested_start = datetime.fromisoformat(x_range_start.replace("Z", "+00:00")).date()
                    except ValueError:
                        # Handle format like '2025-06-28 13:29:01.7266'
                        # Extract just the date part
                        date_part = x_range_start.split(" ")[0].split("T")[0]
                        requested_start = datetime.strptime(date_part, "%Y-%m-%d").date()
                else:
                    raise PreventUpdate

                # Load current data to check earliest date
                daily_file = self.storage.load_daily_data(stock_id)
                if not daily_file or not daily_file.daily_data:
                    raise PreventUpdate

                # Find earliest date in current data
                earliest_date = min(record.date for record in daily_file.daily_data)

                # If requested start is before our earliest data, fetch more
                if requested_start >= earliest_date:
                    # We already have data for this range
                    raise PreventUpdate

                logger.info(f"Fetching more history: requested {requested_start}, have {earliest_date}")

                # Calculate months to fetch (from requested start to our earliest)
                months_to_fetch = []
                current = requested_start
                while current < earliest_date:
                    months_to_fetch.append((current.year, current.month))
                    # Move to next month
                    if current.month == 12:
                        current = date(current.year + 1, 1, 1)
                    else:
                        current = date(current.year, current.month + 1, 1)

                # Fetch missing months (limit to 12 months at a time)
                all_records = []
                for year, month in months_to_fetch[:12]:
                    try:
                        logger.info(f"Fetching {stock_id} for {year}/{month}...")
                        records = self.fetcher.fetch_daily_history(stock_id, year, month)
                        if records:
                            all_records.extend(records)
                            logger.info(f"Got {len(records)} records for {year}/{month}")
                    except Exception as e:
                        logger.warning(f"Failed to fetch {year}/{month}: {e}")
                        continue

                # Save new records
                if all_records:
                    self.storage.save_daily_data(
                        stock_id,
                        daily_file.stock_name,
                        all_records
                    )
                    logger.info(f"Saved {len(all_records)} new historical records for {stock_id}")
                else:
                    logger.warning(f"No new records fetched for {stock_id}")

                # Re-render chart with all data (including newly fetched)
                period_map = {
                    "daily": KlinePeriod.DAILY,
                    "weekly": KlinePeriod.WEEKLY,
                    "monthly": KlinePeriod.MONTHLY,
                    "min_1": KlinePeriod.MIN_1,
                    "min_5": KlinePeriod.MIN_5,
                    "min_15": KlinePeriod.MIN_15,
                    "min_30": KlinePeriod.MIN_30,
                    "min_60": KlinePeriod.MIN_60,
                }
                period = period_map.get(period_value, KlinePeriod.DAILY)

                # Reload data with new records
                daily_file = self.storage.load_daily_data(stock_id)
                if daily_file and daily_file.daily_data:
                    df = self.processor.prepare_kline_data(daily_file.daily_data, period)
                    logger.info(f"Re-rendering chart with {len(df)} data points")
                    return self.renderer.render_kline_chart(
                        df,
                        f"{daily_file.stock_name} ({stock_id})",
                        period.display_name
                    )

                raise PreventUpdate

            except PreventUpdate:
                raise
            except Exception as e:
                logger.warning(f"Zoom handler error: {e}")
                raise PreventUpdate

    def _register_update_callbacks(self) -> None:
        """Register auto-update callbacks."""

        @self.app.callback(
            Output("stock-price-display", "children", allow_duplicate=True),
            Output("stock-price-display", "className", allow_duplicate=True),
            Output("stock-change-display", "children", allow_duplicate=True),
            Output("stock-change-display", "className", allow_duplicate=True),
            Output("stock-volume-display", "children", allow_duplicate=True),
            Output("last-update-display", "children", allow_duplicate=True),
            Output("market-status", "children"),
            Output("scheduler-status", "children"),
            Output("intraday-chart", "figure", allow_duplicate=True),
            Output("kline-chart", "figure", allow_duplicate=True),
            Output("big-orders-list", "children", allow_duplicate=True),
            Output("best-five-prices-body", "children", allow_duplicate=True),
            Output("bidask-ratio-inner", "style", allow_duplicate=True),
            Output("ask-total-vol", "children", allow_duplicate=True),
            Output("bid-total-vol", "children", allow_duplicate=True),
            Input("auto-update-interval", "n_intervals"),
            State("app-state-store", "data"),
            State("main-tabs", "value"),
            State("period-selector", "value"),
            prevent_initial_call=True
        )
        def on_auto_update(n_intervals: int, app_state: dict, active_tab: str, period_value: str):
            """Handle automatic updates (REQ-044)."""
            stock_id = app_state.get("current_stock") if app_state else None

            # Update market and scheduler status
            is_market_open = self.scheduler.is_market_open()
            market_text = f"● 市場狀態：{'開盤中' if is_market_open else '休市'}"

            scheduler_status = self.scheduler.get_status()
            scheduler_text = f"● 排程狀態：{'運作中' if scheduler_status.is_running and not scheduler_status.is_paused else '暫停'}"

            if not stock_id:
                return (
                    no_update, no_update, no_update, no_update,
                    no_update, no_update, market_text, scheduler_text, no_update, no_update, no_update,
                    no_update, no_update, no_update, no_update,
                )

            try:
                # Fetch realtime quote (non-blocking)
                # If Shioaji has data, it returns immediately.
                # If falling back to TWSE, it returns None if rate limit hit.
                quote = self.fetcher.fetch_realtime_quote(stock_id, blocking=False)
                
                if quote is None:
                    # Rate limit hit (TWSE) or no data available yet
                    return (
                        no_update, no_update, no_update, no_update,
                        no_update, no_update, market_text, scheduler_text, no_update, no_update, no_update,
                        no_update, no_update, no_update, no_update,
                    )

                direction_class = self._get_direction_class(quote.direction)
                change_text = f"{'+' if quote.change_amount >= 0 else ''}{quote.change_amount:.2f} ({'+' if quote.change_percent >= 0 else ''}{quote.change_percent:.2f}%)"

                # Shioaji tick callback stores real transaction times. Do not
                # turn Shioaji quote snapshots into fake ticks at poll time.
                if not (self.shioaji_fetcher and self.shioaji_fetcher.is_subscribed(stock_id)):
                    self._save_quote_as_tick(quote)

                # OPTIMIZATION: Update charts every 2 seconds (n_intervals % 2 == 0)
                # Text updates (price, time) happen every second.
                intraday_figure = no_update
                big_orders_items = no_update
                kline_figure = no_update
                five_prices_body = no_update
                bidask_ratio_style = no_update
                ask_total_text = no_update
                bid_total_text = no_update

                if n_intervals % 2 == 0:
                    # Update intraday chart if on intraday tab OR if we need Big Orders (which needs intraday data)
                    # Note: Big Orders list is always visible, so we usually need to load this.
                    # Optimization: Only load if we are on intraday tab OR (it's time to update big orders and we want them)
                    # Let's keep loading it every 2s for Big Orders.
                    
                    intraday_data = self.storage.load_intraday_data(stock_id, date.today())
                    
                    if intraday_data and intraday_data.ticks:
                        df = self.processor.prepare_intraday_data(intraday_data.ticks)
                        
                        # Only render intraday chart if tab is active
                        if active_tab == "intraday":
                            intraday_figure = self.renderer.render_intraday_chart(
                                df,
                                f"{quote.stock_name} ({stock_id})",
                                quote.previous_close
                            )
                        
                        # Generate Big Orders List (Newest at Top)
                        big_orders_items = []
                        
                        if "is_big_buy" in df.columns:
                            big_orders = df[df["is_big_buy"] | df["is_big_sell"]]
                            # Reverse iteration to show newest first
                            for _, row in big_orders.iloc[::-1].iterrows():
                                is_buy = row["is_big_buy"]
                                vol_class = "big-order-volume big-buy" if is_buy else "big-order-volume big-sell"
                                time_str = row["time"].strftime("%H:%M:%S") if isinstance(row["time"], datetime) else str(row["time"])
                                
                                big_orders_items.append(
                                    html.Div(
                                        className="big-order-item",
                                        children=[
                                            html.Span(time_str, className="big-order-time"),
                                            html.Span(f"{row['tick_vol_calc']:.0f}", className=vol_class),
                                        ]
                                    )
                                )
                            if not big_orders_items:
                                big_orders_items = [html.Div("尚無大戶資料", className="no-data")]
                    else:
                        if active_tab == "intraday":
                            intraday_figure = self.renderer.render_empty_chart("載入中...")
                        big_orders_items = [html.Div("尚無大戶資料", className="no-data")]

                    # Update K-line chart if on K-line tab
                    if active_tab == "kline":
                        daily_file = self.storage.load_daily_data(stock_id)
                        if daily_file:
                            period_map = {
                                "daily": KlinePeriod.DAILY,
                                "weekly": KlinePeriod.WEEKLY,
                                "monthly": KlinePeriod.MONTHLY,
                                "min_1": KlinePeriod.MIN_1,
                                "min_5": KlinePeriod.MIN_5,
                                "min_15": KlinePeriod.MIN_15,
                                "min_30": KlinePeriod.MIN_30,
                                "min_60": KlinePeriod.MIN_60,
                            }
                            period = period_map.get(period_value, KlinePeriod.DAILY)
                            
                            # Merge live quote into K-line
                            kline_df = self.processor.prepare_kline_data(
                                daily_file.daily_data, 
                                period,
                                realtime_quote=quote
                            )
                            kline_figure = self.renderer.render_kline_chart(
                                kline_df,
                                f"{quote.stock_name} ({stock_id})",
                                period.display_name
                            )

                    # Update Best Five Prices
                    bidask = self.shioaji_fetcher.get_last_bidask(stock_id) if self.shioaji_fetcher else None
                    if bidask and bidask.get("bid_price") and bidask.get("ask_price"):
                        bid_prices = bidask["bid_price"]
                        bid_volumes = bidask["bid_volume"]
                        ask_prices = bidask["ask_price"]
                        ask_volumes = bidask["ask_volume"]
                        ask_side_total = bidask.get("ask_side_total_vol", 0)
                        bid_side_total = bidask.get("bid_side_total_vol", 0)

                        # Build five-level rows + subtotal
                        rows = []
                        bid_vol_sum = 0
                        ask_vol_sum = 0
                        levels = min(5, len(bid_prices), len(ask_prices))
                        for i in range(levels):
                            bv = bid_volumes[i] if i < len(bid_volumes) else 0
                            av = ask_volumes[i] if i < len(ask_volumes) else 0
                            bid_vol_sum += bv
                            ask_vol_sum += av
                            rows.append(
                                html.Div(
                                    className="five-price-row",
                                    children=[
                                        html.Span(f"{bv:,}", className="five-bid-vol"),
                                        html.Span(f"{bid_prices[i]:.2f}", className="five-bid-price"),
                                        html.Span(f"{ask_prices[i]:.2f}", className="five-ask-price"),
                                        html.Span(f"{av:,}", className="five-ask-vol"),
                                    ]
                                )
                            )
                        # Subtotal row
                        rows.append(
                            html.Div(
                                className="five-subtotal-row",
                                children=[
                                    html.Span(f"{bid_vol_sum:,}", className="five-subtotal-vol"),
                                    html.Span("小計", className="five-subtotal-label"),
                                    html.Span(f"{ask_vol_sum:,}", className="five-subtotal-vol"),
                                ]
                            )
                        )
                        five_prices_body = rows

                        # Bid/Ask ratio bar
                        total = ask_side_total + bid_side_total
                        ratio_pct = (ask_side_total / total * 100) if total > 0 else 50
                        bidask_ratio_style = {"width": f"{ratio_pct:.1f}%"}
                        ask_total_text = f"{ask_side_total:,}"
                        bid_total_text = f"{bid_side_total:,}"

                return (
                    f"{quote.current_price:.2f}",
                    f"stock-price {direction_class}",
                    change_text,
                    f"stock-change {direction_class}",
                    f"{quote.total_volume:,} 張",
                    quote.timestamp.strftime("%H:%M:%S") if quote.timestamp else "--",
                    market_text,
                    scheduler_text,
                    intraday_figure,
                    kline_figure,
                    big_orders_items,
                    five_prices_body,
                    bidask_ratio_style,
                    ask_total_text,
                    bid_total_text,
                )

            except Exception as e:
                logger.warning(f"Auto-update failed: {e}")
                return (
                    no_update, no_update, no_update, no_update,
                    no_update, no_update, market_text, scheduler_text, no_update, no_update, no_update,
                    no_update, no_update, no_update, no_update,
                )

    def _register_hover_callbacks(self) -> None:
        """Register chart hover callbacks."""

        @self.app.callback(
            Output("ohlc-open", "children"),
            Output("ohlc-high", "children"),
            Output("ohlc-low", "children"),
            Output("ohlc-close", "children"),
            Output("ohlc-volume", "children"),
            Input("kline-chart", "hoverData"),
            prevent_initial_call=True
        )
        def on_kline_hover(hover_data: dict):
            """Handle K-line chart hover (REQ-058)."""
            if not hover_data or "points" not in hover_data:
                return "--", "--", "--", "--", "--"

            try:
                point = hover_data["points"][0]
                customdata = point.get("customdata", {})

                if isinstance(customdata, dict):
                    return (
                        f"{customdata.get('open', '--'):.2f}" if customdata.get('open') else "--",
                        f"{customdata.get('high', '--'):.2f}" if customdata.get('high') else "--",
                        f"{customdata.get('low', '--'):.2f}" if customdata.get('low') else "--",
                        f"{customdata.get('close', '--'):.2f}" if customdata.get('close') else "--",
                        f"{customdata.get('volume', '--'):,}" if customdata.get('volume') else "--",
                    )
            except Exception as e:
                logger.debug(f"Hover data parse error: {e}")

            return "--", "--", "--", "--", "--"

    def _register_error_callbacks(self) -> None:
        """Register error handling callbacks."""

        @self.app.callback(
            Output("error-message-display", "style"),
            Input("error-close-button", "n_clicks"),
            prevent_initial_call=True
        )
        def on_error_close(n_clicks: int):
            """Handle error message close button."""
            return {"display": "none"}

    def _get_direction_class(self, direction: PriceDirection) -> str:
        """Get CSS class for price direction."""
        if direction == PriceDirection.UP:
            return "price-up"
        elif direction == PriceDirection.DOWN:
            return "price-down"
        return "price-flat"

    def show_error(self, message: str, error_type: str = "error") -> None:
        """
        Show error message in the UI.

        Args:
            message: Error message to display
            error_type: "error", "warning", or "info"
        """
        # This would be called programmatically
        # In Dash, we'd need to use a Store + callback pattern
        logger.error(f"UI Error ({error_type}): {message}")

    def _save_quote_as_tick(self, quote: RealtimeQuote) -> None:
        """
        Save a realtime quote as an intraday tick.

        This accumulates price data for the intraday chart.

        Args:
            quote: RealtimeQuote to convert and save
        """
        try:
            if getattr(quote, "is_simtrade", False):
                logger.debug(f"Skip saving simtrade quote for {quote.stock_id}")
                return

            # Load previous ticks to calculate volume delta and price trend (REQ-FixVolume0)
            last_accumulated_volume = 0
            last_price = quote.previous_close # Default to prev close if no ticks
            
            existing_data = self.storage.load_intraday_data(quote.stock_id, date.today())
            stream_sum = 0
            has_accumulated_anchor = False
            
            if existing_data and existing_data.ticks:
                last_tick = existing_data.ticks[-1]
                last_price = last_tick.price
                
                # Search backwards for last non-zero accumulated volume
                # And sum up the volume of Shioaji ticks (acc=0) in between
                for t in reversed(existing_data.ticks):
                    if t.accumulated_volume > 0:
                        last_accumulated_volume = t.accumulated_volume
                        has_accumulated_anchor = True
                        break
                    
                    # Skip odd lots for stream sum (they are shares, but quote.total_volume is lots)
                    if getattr(t, 'is_odd', False):
                        continue
                        
                    stream_sum += t.volume

            # Calculate actual volume since last poll
            latest_tick_volume = max(0, int(getattr(quote, "tick_volume", 0) or 0))
            if quote.total_volume >= last_accumulated_volume:
                if has_accumulated_anchor:
                    delta = quote.total_volume - last_accumulated_volume
                    # Deduplicate: Subtract volume already captured by stream ticks
                    tick_volume = max(0, delta - stream_sum)
                else:
                    # A first snapshot's cumulative volume is not one trade.
                    # Keep the total as accumulated_volume, but only use the
                    # source's latest single-trade volume for per-tick volume.
                    tick_volume = latest_tick_volume
            else:
                tick_volume = latest_tick_volume

            # Determine buy/sell volume based on Price Trend (Primary) -> Bid/Ask (Secondary)
            buy_volume = 0.0
            sell_volume = 0.0
            
            if quote.current_price > last_price:
                # Price Up -> Dominant Buy
                buy_volume = float(tick_volume)
            elif quote.current_price < last_price:
                # Price Down -> Dominant Sell
                sell_volume = float(tick_volume)
            else:
                # Price Unchanged -> Check Bid/Ask
                if quote.best_ask and quote.current_price >= quote.best_ask:
                    buy_volume = float(tick_volume)
                elif quote.best_bid and quote.current_price <= quote.best_bid:
                    sell_volume = float(tick_volume)
                else:
                    # Indeterminate -> Split
                    buy_volume = tick_volume / 2.0
                    sell_volume = tick_volume / 2.0

            # If this is the first data point (gap fill from 0 to Current Total), do not bias Buy/Sell power
            # We preserve tick_volume for the Total Volume chart, but neutralize Buy/Sell Power
            if last_accumulated_volume == 0:
                buy_volume = 0.0
                sell_volume = 0.0

            tick = IntradayTick(
                time=quote.timestamp.time() if quote.timestamp else datetime.now().time(),
                price=quote.current_price,
                volume=tick_volume,
                buy_volume=buy_volume,
                sell_volume=sell_volume,
                accumulated_volume=quote.total_volume,
                timestamp=quote.timestamp or datetime.now(),
            )

            self.storage.save_intraday_data(
                stock_id=quote.stock_id,
                stock_name=quote.stock_name,
                trade_date=date.today(),
                previous_close=quote.previous_close,
                ticks=[tick],
            )
            logger.debug(f"Saved intraday tick for {quote.stock_id}: {quote.current_price} (V:{tick_volume}, B:{buy_volume}, S:{sell_volume})")
        except Exception as e:
            logger.warning(f"Failed to save intraday tick: {e}")

    def _fetch_and_save_daily_history(self, stock_id: str, stock_name: str) -> None:
        """
        Fetch and save historical daily OHLC data for K-line chart.

        Fetches the last 3 months of data to populate the K-line chart.

        Args:
            stock_id: Stock ID
            stock_name: Stock name
        """
        try:
            today = date.today()
            all_records = []

            # Fetch last 6 months of data for initial load
            for months_ago in range(6):
                year = today.year
                month = today.month - months_ago
                if month <= 0:
                    month += 12
                    year -= 1

                try:
                    records = self.fetcher.fetch_daily_history(stock_id, year, month)
                    if records:
                        all_records.extend(records)
                        logger.debug(f"Fetched {len(records)} records for {stock_id} ({year}/{month})")
                except Exception as e:
                    logger.warning(f"Failed to fetch history for {year}/{month}: {e}")
                    continue

            # Save all records
            if all_records:
                self.storage.save_daily_data(stock_id, stock_name, all_records)
                logger.info(f"Saved {len(all_records)} daily records for {stock_id}")

        except Exception as e:
            logger.warning(f"Failed to fetch daily history for {stock_id}: {e}")

    # ── News callbacks ───────────────────────────────────────────────────────

    def _register_news_callbacks(self) -> None:
        """
        Register all news-related callbacks.

        TASK-153: URL routing → page-content
        TASK-154: Main page stock-filtered news tab
        TASK-155: /news page category view + manual refresh
        TASK-156: Ticker bar rotation (5 s)
        """
        from src.app.layout import create_main_page_layout, create_news_page_layout

        # ── TASK-153  Routing ────────────────────────────────────────────────
        @self.app.callback(
            Output("page-content", "children"),
            Input("url", "pathname"),
        )
        def route_page(pathname: str):
            """Swap page-content based on URL pathname."""
            if pathname == "/news":
                return create_news_page_layout()
            return create_main_page_layout()

        # ── News data store refresh ──────────────────────────────────────────
        # Loads latest news into the shared store so all news callbacks
        # can read from it without hitting storage independently.
        @self.app.callback(
            Output("news-data-store", "data"),
            Input("news-ticker-interval", "n_intervals"),
            Input("news-refresh-button", "n_clicks", allow_optional=True),
            prevent_initial_call=False,
        )
        def refresh_news_store(n_intervals, n_clicks):
            """Load latest news run result into the shared data store."""
            try:
                run_result = self.storage.load_latest_news()
                if run_result is None:
                    return None
                return run_result.to_dict()
            except Exception as e:
                logger.warning(f"Failed to load latest news: {e}")
                return no_update

        # ── TASK-154  Stock news tab (main page) ─────────────────────────────
        @self.app.callback(
            Output("stock-news-articles", "children"),
            Input("stock-news-category-tabs", "value", allow_optional=True),
            Input("news-data-store", "data"),
            Input("app-state-store", "data"),
            prevent_initial_call=False,
        )
        def update_stock_news_tab(category: str, news_data: dict, app_state: dict):
            """Filter news by current stock + selected category."""
            category = category or "ALL"
            if not news_data:
                return html.Div("尚無新聞資料", className="no-news")

            current_stock = (app_state or {}).get("current_stock")
            if not current_stock:
                return html.Div("請先選擇股票", className="no-news")

            articles = _extract_articles_from_run(news_data, category, current_stock)
            if not articles:
                return html.Div(f"目前無 {current_stock} 相關新聞", className="no-news")

            return _render_article_list(articles)

        # ── TASK-155  /news page ─────────────────────────────────────────────
        @self.app.callback(
            Output("news-category-content", "children"),
            Output("news-last-updated", "children"),
            Input("news-category-tabs", "value", allow_optional=True),
            Input("news-data-store", "data"),
            prevent_initial_call=False,
        )
        def update_news_page(category: str, news_data: dict):
            """Show all articles in the selected category on the /news page."""
            category = category or "INTERNATIONAL"
            if not news_data:
                return html.Div("尚無新聞資料", className="no-news"), "最後更新：--"

            # Last updated time
            run_at = news_data.get("run_at", "")
            try:
                from datetime import datetime as _dt
                ts = _dt.fromisoformat(run_at)
                updated_str = f"最後更新：{ts.strftime('%Y-%m-%d %H:%M')}"
            except Exception:
                updated_str = "最後更新：--"

            articles = _extract_articles_from_run(news_data, category, stock_filter=None)
            if not articles:
                return html.Div("此分類目前無新聞", className="no-news"), updated_str

            return _render_article_list(articles), updated_str

        # ── TASK-156  News ticker ────────────────────────────────────────────
        @self.app.callback(
            Output("news-ticker-content", "children"),
            Output("news-ticker-bar", "style"),
            Input("news-ticker-interval", "n_intervals"),
            State("news-data-store", "data"),
            State("app-state-store", "data"),
            prevent_initial_call=False,
        )
        def rotate_ticker(n_intervals: int, news_data: dict, app_state: dict):
            """Rotate the ticker headline every 5 seconds."""
            if not news_data:
                return "--", {"display": "none"}

            current_stock = (app_state or {}).get("current_stock")
            # Collect one headline per category (most recent)
            headlines = _collect_ticker_headlines(news_data, current_stock)
            if not headlines:
                return "--", {"display": "none"}

            idx = (n_intervals or 0) % len(headlines)
            item = headlines[idx]
            ticker_text = f"[{item['category']}] {item['title']}"
            return ticker_text, {"display": "flex"}


# ── Module-level news helper functions ──────────────────────────────────────

_CATEGORY_DISPLAY = {
    "INTERNATIONAL": "國際",
    "FINANCIAL": "財經",
    "TECH": "科技",
    "STOCK_TW": "台股",
    "STOCK_US": "美股",
}


def _extract_articles_from_run(
    run_dict: dict,
    category: str,
    stock_filter: Optional[str],
) -> List[dict]:
    """
    Extract article dicts from a serialised NewsRunResult dict.

    Args:
        run_dict: to_dict() output of a NewsRunResult
        category: category value ("ALL", "INTERNATIONAL", …)
        stock_filter: stock_id to filter by (None = no filter)

    Returns:
        List of plain article dicts ordered newest-first.
    """
    categories = run_dict.get("categories", {})
    articles: List[dict] = []

    for cat_key, cat_data in categories.items():
        if category != "ALL" and cat_key != category:
            continue
        for art in cat_data.get("articles", []):
            if stock_filter:
                related = art.get("related_stock_ids", [])
                if stock_filter not in related:
                    continue
            art_copy = dict(art)
            art_copy["_category_key"] = cat_key
            articles.append(art_copy)

    # Sort newest-first
    articles.sort(key=lambda a: a.get("published_at", ""), reverse=True)
    return articles


def _render_article_list(articles: List[dict]) -> html.Div:
    """Render a list of article dicts as Dash html components."""
    items = []
    for art in articles:
        cat_key = art.get("_category_key", "")
        cat_label = _CATEGORY_DISPLAY.get(cat_key, cat_key)
        pub = art.get("published_at", "")
        try:
            from datetime import datetime as _dt
            ts = _dt.fromisoformat(pub)
            pub_str = ts.strftime("%m/%d %H:%M")
        except Exception:
            pub_str = pub[:16] if pub else "--"

        title = art.get("title", "（無標題）")
        summary = art.get("summary") or art.get("excerpt", "")
        url = art.get("url", "#")
        source = art.get("source", "")

        items.append(
            html.Div(
                className="news-article-card",
                children=[
                    html.Div(
                        className="news-article-header",
                        children=[
                            html.Span(cat_label, className="news-cat-badge"),
                            html.Span(source, className="news-source"),
                            html.Span(pub_str, className="news-pub-time"),
                        ],
                    ),
                    html.A(
                        title,
                        href=url,
                        target="_blank",
                        rel="noopener noreferrer",
                        className="news-article-title",
                    ),
                    html.P(summary, className="news-article-summary") if summary else None,
                ],
            )
        )

    return html.Div(items, className="news-articles-list")


def _collect_ticker_headlines(
    run_dict: dict,
    stock_filter: Optional[str],
) -> List[dict]:
    """
    Collect one headline per category for the ticker bar.

    If stock_filter is set, prefer related articles; fall back to
    the most-recent article across all categories if nothing matches.
    """
    categories = run_dict.get("categories", {})
    headlines: List[dict] = []

    for cat_key, cat_data in categories.items():
        cat_articles = cat_data.get("articles", [])
        if not cat_articles:
            continue

        # Prefer articles related to the current stock
        picked = None
        if stock_filter:
            for art in cat_articles:
                if stock_filter in art.get("related_stock_ids", []):
                    picked = art
                    break

        if picked is None:
            picked = cat_articles[0]

        headlines.append({
            "category": _CATEGORY_DISPLAY.get(cat_key, cat_key),
            "title": picked.get("title", ""),
            "url": picked.get("url", "#"),
        })

    return headlines
