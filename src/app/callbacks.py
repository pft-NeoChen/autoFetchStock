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

    def __init__(self, app, fetcher, storage, processor, renderer, scheduler):
        """
        Initialize callback manager.

        Args:
            app: Dash application instance
            fetcher: DataFetcher instance
            storage: DataStorage instance
            processor: DataProcessor instance
            renderer: ChartRenderer instance
            scheduler: Scheduler instance
        """
        self.app = app
        self.fetcher = fetcher
        self.storage = storage
        self.processor = processor
        self.renderer = renderer
        self.scheduler = scheduler
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
        logger.info("All callbacks registered")

    def _register_favorites_callbacks(self) -> None:
        """Register favorites related callbacks."""

        @self.app.callback(
            Output("app-state-store", "data", allow_duplicate=True),
            Input("main-container", "id"),
            State("app-state-store", "data"),
            prevent_initial_call=True
        )
        def load_initial_favorites(_, current_state: dict):
            """Load favorites from storage on initial load."""
            favorites = self.storage.load_favorites()
            if not favorites:
                return no_update
            
            new_state = current_state.copy()
            new_state["favorites"] = favorites
            
            # Also add all favorites to scheduler for background fetching
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
                logger.info(f"Removed {stock_id} from favorites")
            else:
                # Add to favorites
                favorites.append({
                    "id": stock_id,
                    "name": self._current_stock_name or stock_id
                })
                star_class = "star-button active"
                logger.info(f"Added {stock_id} to favorites")

            # Update state and save to storage
            new_state = current_state.copy()
            new_state["favorites"] = favorites
            self.storage.save_favorites(favorites)

            return new_state, star_class

        @self.app.callback(
            Output("favorites-list", "children"),
            Input("app-state-store", "data"),
        )
        def render_favorites_list(app_state: dict):
            """Render the favorites list sidebar."""
            favorites = app_state.get("favorites", [])
            current_stock = app_state.get("current_stock")

            if not favorites:
                return html.Div("尚未加入最愛", className="no-favorites")

            items = []
            for fav in favorites:
                is_active = fav["id"] == current_stock
                items.append(
                    html.Div(
                        id={"type": "favorite-item", "index": fav["id"]},
                        className=f"favorite-item{' active' if is_active else ''}",
                        children=[
                            html.Span(f"{fav['name']} ({fav['id']})", className="favorite-item-text"),
                        ],
                        n_clicks=0,
                    )
                )
            return items

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
                # Try to fetch by exact ID first, then search
                stock_id = search_value.strip().upper()

                # Try to get realtime quote
                quote = self.fetcher.fetch_realtime_quote(stock_id)

                # Update internal state
                self._current_stock_id = stock_id
                self._current_stock_name = quote.stock_name

                # Check if in favorites
                favorites = current_state.get("favorites", [])
                is_favorite = any(f["id"] == stock_id for f in favorites)
                star_class = "star-button active" if is_favorite else "star-button"

                # Save as intraday tick for chart (Immediate update)
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
                    no_update, no_update, market_text, scheduler_text, no_update, no_update, no_update
                )

            try:
                quote = self.fetcher.fetch_realtime_quote(stock_id)
                direction_class = self._get_direction_class(quote.direction)
                change_text = f"{'+' if quote.change_amount >= 0 else ''}{quote.change_amount:.2f} ({'+' if quote.change_percent >= 0 else ''}{quote.change_percent:.2f}%)"

                # Save as intraday tick
                self._save_quote_as_tick(quote)

                # Update intraday chart if on intraday tab
                intraday_figure = no_update
                big_orders_items = no_update
                
                # Always load intraday data to update Big Orders list, even if tab not active?
                # The user wants "realtime monitoring", usually implies visible.
                # Let's update it if we have data.
                intraday_data = self.storage.load_intraday_data(stock_id, date.today())
                
                if intraday_data and intraday_data.ticks:
                    df = self.processor.prepare_intraday_data(intraday_data.ticks)
                    
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
                kline_figure = no_update
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
                )

            except Exception as e:
                logger.warning(f"Auto-update failed: {e}")
                return (
                    no_update, no_update, no_update, no_update,
                    no_update, no_update, market_text, scheduler_text, no_update, no_update, no_update
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
            # Load previous ticks to calculate volume delta and price trend (REQ-FixVolume0)
            last_accumulated_volume = 0
            last_price = quote.previous_close # Default to prev close if no ticks
            
            existing_data = self.storage.load_intraday_data(quote.stock_id, date.today())
            if existing_data and existing_data.ticks:
                last_tick = existing_data.ticks[-1]
                last_accumulated_volume = last_tick.accumulated_volume
                last_price = last_tick.price

            # Calculate actual volume since last poll
            if quote.total_volume >= last_accumulated_volume:
                tick_volume = quote.total_volume - last_accumulated_volume
            else:
                tick_volume = quote.tick_volume

            # Determine buy/sell volume based on Price Trend (Primary) -> Bid/Ask (Secondary)
            buy_volume = 0
            sell_volume = 0
            
            if quote.current_price > last_price:
                # Price Up -> Dominant Buy
                buy_volume = tick_volume
            elif quote.current_price < last_price:
                # Price Down -> Dominant Sell
                sell_volume = tick_volume
            else:
                # Price Unchanged -> Check Bid/Ask
                if quote.best_ask and quote.current_price >= quote.best_ask:
                    buy_volume = tick_volume
                elif quote.best_bid and quote.current_price <= quote.best_bid:
                    sell_volume = tick_volume
                else:
                    # Indeterminate -> Split
                    buy_volume = tick_volume / 2
                    sell_volume = tick_volume / 2

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
