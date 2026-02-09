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
from src.storage import DataStorage
from src.processor.data_processor import DataProcessor
from src.renderer.chart_renderer import ChartRenderer
from src.scheduler import Scheduler
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

        # Data fetcher with storage for cache
        self.fetcher = DataFetcher(storage=self.storage)
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
            storage=self.storage,
            processor=self.processor,
            renderer=self.renderer,
            scheduler=self.scheduler,
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
            if existing_data and existing_data.ticks:
                last_tick = existing_data.ticks[-1]
                last_accumulated_volume = last_tick.accumulated_volume
                last_price = last_tick.price

            # Calculate actual volume since last poll
            if quote.total_volume >= last_accumulated_volume:
                tick_volume = quote.total_volume - last_accumulated_volume
            else:
                tick_volume = getattr(quote, "tick_volume", 0)

            # Determine buy/sell volume based on Price Trend (Primary)
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
                best_ask = getattr(quote, "best_ask", 0)
                best_bid = getattr(quote, "best_bid", 0)
                
                if best_ask and quote.current_price >= best_ask:
                    buy_volume = tick_volume
                elif best_bid and quote.current_price <= best_bid:
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

        # Close fetcher session
        if self.fetcher:
            self.fetcher.close()

        logger.info("AppController shutdown complete")

    @property
    def server(self):
        """Get the underlying Flask server for WSGI deployment."""
        return self.app.server
