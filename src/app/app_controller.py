"""
Application controller for autoFetchStock.

This module is the main orchestrator that initializes all components
and manages the Dash application lifecycle.
"""

import logging
from typing import Optional

from dash import Dash

from src.config import AppConfig, setup_logging
from src.fetcher import DataFetcher
from src.fetcher.shioaji_fetcher import ShioajiFetcher
from src.storage import DataStorage
from src.processor.data_processor import DataProcessor
from src.renderer.chart_renderer import ChartRenderer
from src.scheduler import Scheduler
from src.news.news_processor import NewsProcessor
from src.app.layout import create_layout
from src.app.callbacks import CallbackManager

logger = logging.getLogger("autofetchstock.app")


class AppController:
    """
    Main application controller.

    Initializes and coordinates all application components:
    - DataFetcher: TWSE API data fetching
    - DataStorage: Local JSON file storage
    - DataProcessor: Data transformation and calculations
    - ChartRenderer: Plotly chart generation
    - Scheduler: Automatic data fetching
    - Dash App: Web interface

    Implements REQ-004 (web interface), REQ-011 (query response),
    REQ-073 (history load), REQ-080 (performance).
    """

    def __init__(self, config: AppConfig = None):
        """
        Initialize application controller.

        Args:
            config: Application configuration (uses defaults if None)
        """
        self.config = config or AppConfig()

        # Initialize logging
        setup_logging(self.config)
        logger.info("Initializing AppController...")

        # Initialize components
        self._init_components()

        # Create Dash application
        self._init_dash_app()

        # Load existing data on startup (REQ-073)
        self._load_existing_data()

        logger.info("AppController initialized successfully")

    def _init_components(self) -> None:
        """Initialize all application components."""
        # Data storage
        self.storage = DataStorage(data_dir=self.config.data_dir)
        logger.debug("DataStorage initialized")

        # Shioaji fetcher
        self.shioaji_fetcher = ShioajiFetcher(config=self.config)
        if self.shioaji_fetcher.login():
            logger.info("ShioajiFetcher logged in and ready")
            self.shioaji_fetcher.set_callbacks(
                on_quote=self._handle_shioaji_quote,
                on_tick=self._handle_shioaji_tick  # Re-enable raw ticks for accurate big orders
            )
        else:
            logger.warning("ShioajiFetcher failed to login, fallback to TWSE only")

        # Data fetcher with storage for cache and Shioaji fetcher
        self.fetcher = DataFetcher(
            storage=self.storage,
            shioaji_fetcher=self.shioaji_fetcher
        )
        logger.debug("DataFetcher initialized")
        
        # Pre-load stock list for search (in background ideally)
        try:
            # This will now hit cache first if available
            self.fetcher.preload_stock_list()
        except Exception as e:
            logger.warning(f"Failed to pre-load stock list: {e}")

        # Data processor

        # Data processor
        self.processor = DataProcessor()
        logger.debug("DataProcessor initialized")

        # Chart renderer
        self.renderer = ChartRenderer()
        logger.debug("ChartRenderer initialized")

        # Scheduler with fetch callback
        self.scheduler = Scheduler(
            fetch_callback=self._scheduled_fetch,
            fetch_interval=self.config.fetch_interval
        )
        logger.debug("Scheduler initialized")

        # News processor
        self.news_processor = NewsProcessor(
            config=self.config,
            storage=self.storage,
        )
        # Register hourly news job (08:00-15:00 Mon-Fri)
        self.scheduler.add_news_job(self.news_processor.run)
        self.scheduler.add_news_cleanup_job(
            lambda: self.storage.cleanup_old_news(self.config.news_retention_days)
        )
        self.scheduler.add_news_event_job(
            lambda: self.news_processor.build_event_timeline(
                self.config.news_history_window_days
            )
        )
        if self.config.news_rag_enabled:
            self.scheduler.add_news_rag_index_job(
                lambda: self.news_processor.update_rag_index(
                    self.config.news_rag_window_days
                )
            )
        logger.debug("NewsProcessor initialized and news jobs registered")

    def _init_dash_app(self) -> None:
        """Initialize Dash application with layout and callbacks."""
        # Create Dash app
        self.app = Dash(
            __name__,
            title="台股即時資料系統",
            update_title=None,
            suppress_callback_exceptions=True,
            assets_folder="assets",
        )

        # Set layout
        self.app.layout = create_layout()

        # Initialize callback manager
        self.callback_manager = CallbackManager(
            app=self.app,
            fetcher=self.fetcher,
            shioaji_fetcher=self.shioaji_fetcher,
            storage=self.storage,
            processor=self.processor,
            renderer=self.renderer,
            scheduler=self.scheduler,
            news_processor=self.news_processor,
        )

        # Register all callbacks
        self.callback_manager.register_callbacks()

        logger.debug("Dash app initialized")

    def _load_existing_data(self) -> None:
        """Load existing history data on startup (REQ-073)."""
        try:
            available_stocks = self.storage.get_available_stocks()
            logger.info(f"Found {len(available_stocks)} stocks with existing data")

            for stock_id in available_stocks:
                daily_data = self.storage.load_daily_data(stock_id)
                if daily_data:
                    logger.debug(f"Loaded {len(daily_data.daily_data)} records for {stock_id}")

        except Exception as e:
            logger.warning(f"Error loading existing data: {e}")

    def _scheduled_fetch(self, stock_id: str) -> None:
        """
        Callback for scheduled data fetching.

        Called by the Scheduler at configured intervals.

        Args:
            stock_id: Stock ID to fetch
        """
        # Skip if Shioaji is handling this stock
        if self.shioaji_fetcher and self.shioaji_fetcher.is_subscribed(stock_id):
            logger.debug(f"Skipping scheduled fetch for {stock_id} (Shioaji active)")
            return

        try:
            # Fetch realtime quote
            quote = self.fetcher.fetch_realtime_quote(stock_id)
            logger.debug(f"Scheduled fetch for {stock_id}: {quote.current_price}")

            # Save as intraday tick for background data accumulation
            self._save_quote_as_tick(quote)

        except Exception as e:
            logger.error(f"Scheduled fetch failed for {stock_id}: {e}")
            raise

    def _save_quote_as_tick(self, quote) -> None:
        """
        Save a realtime quote as an intraday tick.
        """
        from datetime import datetime, date
        from src.models import IntradayTick
        try:
            # Load previous ticks to calculate volume delta and price trend (REQ-FixVolume0)
            last_accumulated_volume = 0
            last_price = quote.previous_close # Default
            
            existing_data = self.storage.load_intraday_data(quote.stock_id, date.today())
            stream_sum = 0
            has_accumulated_anchor = False
            
            if existing_data and existing_data.ticks:
                last_tick = existing_data.ticks[-1]
                last_price = last_tick.price
                
                # Search backwards for last non-zero accumulated volume
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

            # Determine buy/sell volume based on Price Trend (Primary)
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
                best_ask = getattr(quote, "best_ask", 0)
                best_bid = getattr(quote, "best_bid", 0)
                
                if best_ask and quote.current_price >= best_ask:
                    buy_volume = float(tick_volume)
                elif best_bid and quote.current_price <= best_bid:
                    sell_volume = float(tick_volume)
                else:
                    # Indeterminate -> Split
                    buy_volume = tick_volume / 2.0
                    sell_volume = tick_volume / 2.0

            # If this is the first data point (gap fill from 0 to Current Total), do not bias Buy/Sell power
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
        except Exception as e:
            logger.warning(f"Failed to save scheduled intraday tick: {e}")

    def run(
        self,
        host: str = None,
        port: int = None,
        debug: bool = None
    ) -> None:
        """
        Run the application server.

        Args:
            host: Server host (default from config)
            port: Server port (default from config)
            debug: Debug mode (default from config)
        """
        host = host or self.config.host
        port = port or self.config.port
        debug = debug if debug is not None else self.config.debug

        logger.info(f"Starting server at http://{host}:{port}")

        # Start scheduler
        self.scheduler.start()

        try:
            # Run Dash server
            self.app.run(
                host=host,
                port=port,
                debug=debug,
            )
        finally:
            # Cleanup on shutdown
            self.shutdown()

    def shutdown(self) -> None:
        """Gracefully shutdown all components."""
        logger.info("Shutting down AppController...")

        # Stop scheduler
        if self.scheduler:
            self.scheduler.stop()

        # Logout shioaji
        if hasattr(self, 'shioaji_fetcher'):
            self.shioaji_fetcher.logout()

        # Close fetcher session
        if self.fetcher:
            self.fetcher.close()

        logger.info("AppController shutdown complete")

    def _handle_shioaji_quote(self, quote) -> None:
        """Handle real-time quote from Shioaji."""
        # Update storage or cache if needed
        # For now, we mainly rely on ticks for chart data
        pass

    def _handle_shioaji_tick(self, tick) -> None:
        """Handle real-time tick from Shioaji and save to storage."""
        from datetime import date
        
        try:
            # tick is already an IntradayTick instance with metadata attached by ShioajiFetcher
            stock_name = getattr(tick, "stock_name", "")
            reference = getattr(tick, "reference", 0)
            stock_id = getattr(tick, "stock_id", "")
            
            if not stock_id:
                logger.warning("Received Shioaji tick without stock_id")
                return

            # Save to storage
            self.storage.save_intraday_data(
                stock_id=stock_id,
                stock_name=stock_name,
                trade_date=date.today(),
                previous_close=reference,
                ticks=[tick]
            )
        except Exception as e:
            logger.error(f"Error saving Shioaji tick: {e}")

    @property
    def server(self):
        """Get the underlying Flask server for WSGI deployment."""
        return self.app.server
