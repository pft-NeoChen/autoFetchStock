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
        
        # Volume cache for real-time accumulation {stock_id: total_volume}
        self._volume_cache = {}

        # Initialize components
        self._init_components()

        # Create Dash application
        self._init_dash_app()

        # Load existing data on startup (REQ-073)
        self._load_existing_data()

        logger.info("AppController initialized successfully")

    def init_volume_cache(self, stock_id: str, initial_volume: int) -> None:
        """Initialize or reset volume cache for a stock."""
        self._volume_cache[stock_id] = initial_volume
        logger.info(f"Initialized volume cache for {stock_id} to {initial_volume}")

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
            # Auto-subscribe to saved favorites on startup
            self._subscribe_saved_favorites()
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

    def _subscribe_saved_favorites(self) -> None:
        """Subscribe to all saved favorites in Shioaji."""
        try:
            favorites = self.storage.load_favorites()
            if not favorites:
                return

            logger.info(f"Auto-subscribing to {len(favorites)} saved favorites...")
            for fav in favorites:
                stock_id = fav.get("id")
                if stock_id:
                    self.shioaji_fetcher.subscribe(stock_id)
                    # Warm up cache with snapshot to ensure immediate UI display
                    try:
                        quote = self.shioaji_fetcher.fetch_quote(stock_id)
                        if quote and hasattr(self.fetcher, '_quote_cache'):
                            # Also update DataFetcher cache
                            import threading
                            with self.fetcher._cache_lock:
                                self.fetcher._quote_cache[stock_id] = quote
                    except Exception:
                        pass # Ignore snapshot errors during startup
        except Exception as e:
            logger.error(f"Failed to auto-subscribe favorites: {e}")

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
        # Check Shioaji cache freshness
        if self.shioaji_fetcher and self.shioaji_fetcher.is_subscribed(stock_id):
            cached_quote = self.shioaji_fetcher.get_last_quote(stock_id)
            
            if cached_quote:
                # Check data staleness
                from datetime import datetime
                now = datetime.now()
                # Ensure quote.timestamp is timezone-naive or converted properly if needed.
                # Assuming both are local time for now.
                ts = cached_quote.timestamp
                if ts:
                    age = (now - ts).total_seconds()
                    if age < 20: # Consider data fresh if < 20 seconds old
                        logger.debug(f"Skipping scheduled fetch for {stock_id} (Shioaji active & fresh {age:.1f}s)")
                        return
                    else:
                        logger.info(f"Shioaji data for {stock_id} is stale ({age:.1f}s old). forcing update...")
                else:
                    # No timestamp? Treat as stale/no-data
                    pass
            else:
                logger.info(f"Shioaji subscribed to {stock_id} but no data yet. Attempting Shioaji snapshot...")

            # If we reach here, it means either no cache or stale cache.
            # Try to fetch snapshot from Shioaji first
            try:
                quote = self.shioaji_fetcher.fetch_quote(stock_id)
                if quote:
                    logger.info(f"Fetched Shioaji snapshot for {stock_id}: {quote.current_price}")
                    # Update DataFetcher's cache too so UI can see it immediately
                    if hasattr(self.fetcher, '_quote_cache'):
                        import threading
                        with self.fetcher._cache_lock:
                            self.fetcher._quote_cache[stock_id] = quote
                            
                    # Save as intraday tick
                    self._save_quote_as_tick(quote)
                    return # Success, no need for TWSE
            except Exception as e:
                logger.warning(f"Shioaji snapshot failed for {stock_id}: {e}")
            
            logger.info(f"Shioaji snapshot failed/empty. Scheduler will fetch fallback from TWSE.")

        try:
            # Fetch realtime quote
            quote = self.fetcher.fetch_realtime_quote(stock_id)
            logger.debug(f"Scheduled fetch for {stock_id}: {quote.current_price}")

            # Save as intraday tick for background data accumulation
            self._save_quote_as_tick(quote)

        except Exception as e:
            logger.error(f"Scheduled fetch failed for {stock_id}: {e}")
            raise

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
        from datetime import datetime, date, time
        from src.models import IntradayTick
        
        # Ignore pre-market trial matching data (before 09:00:00)
        current_time = quote.timestamp.time() if quote.timestamp else datetime.now().time()
        if current_time < time(9, 0):
            return

        try:
            # Load previous ticks to calculate volume delta and price trend (REQ-FixVolume0)
            last_accumulated_volume = 0
            last_price = quote.previous_close # Default
            last_tick_time = None
            
            existing_data = self.storage.load_intraday_data(quote.stock_id, date.today())
            stream_sum = 0
            
            if existing_data and existing_data.ticks:
                last_tick = existing_data.ticks[-1]
                last_price = last_tick.price
                last_tick_time = last_tick.timestamp
                if not last_tick_time and hasattr(last_tick, 'time'):
                     last_tick_time = datetime.combine(date.today(), last_tick.time)
                
                # Search backwards for last non-zero accumulated volume
                for t in reversed(existing_data.ticks):
                    if t.accumulated_volume > 0:
                        last_accumulated_volume = t.accumulated_volume
                        break
                    
                    # Skip odd lots for stream sum (they are shares, but quote.total_volume is lots)
                    if getattr(t, 'is_odd', False):
                        continue
                        
                    stream_sum += t.volume

            # Calculate actual volume since last poll
            if quote.total_volume >= last_accumulated_volume:
                delta = quote.total_volume - last_accumulated_volume
                # Deduplicate: Subtract volume already captured by stream ticks
                tick_volume = max(0, delta - stream_sum)
                if tick_volume > 0:
                    logger.info(f"SaveTick {quote.stock_id}: LastAcc={last_accumulated_volume}, CurrTotal={quote.total_volume}, Delta={delta}, StreamSum={stream_sum} -> TickVol={tick_volume}")
            else:
                tick_volume = getattr(quote, "tick_volume", 0)

            # Determine buy/sell volume based on Price Trend (Primary)
            buy_volume = 0.0
            sell_volume = 0.0
            
            # Smart Spike Detection:
            # Only treat as "Gap Fill" if time difference is large (> 5 minutes) AND volume is large (> 500).
            # This allows real big orders (which happen instantly) to pass, but filters out long disconnection gaps.
            is_large_gap = False
            current_time = quote.timestamp or datetime.now()
            
            if tick_volume > 500:
                if last_tick_time:
                    # Ensure timezone awareness compatibility
                    if last_tick_time.tzinfo is None and current_time.tzinfo is not None:
                        last_tick_time = last_tick_time.replace(tzinfo=current_time.tzinfo)
                    elif last_tick_time.tzinfo is not None and current_time.tzinfo is None:
                        current_time = current_time.replace(tzinfo=last_tick_time.tzinfo)
                        
                    time_gap = (current_time - last_tick_time).total_seconds()
                    if time_gap > 300: # 5 minutes gap
                        is_large_gap = True
                        logger.info(f"Detected large gap fill for {quote.stock_id}: Vol={tick_volume}, Gap={time_gap:.1f}s. Skipping buy/sell power.")
                else:
                    is_large_gap = True

            if not is_large_gap and last_accumulated_volume > 0:
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
        logger.debug(f"AppController received quote for {quote.stock_id}")
        
        # Use Quote's total volume to calibrate our cache
        try:
            current_vol = int(quote.total_volume)
            old_vol = self._volume_cache.get(quote.stock_id, 0)
            
            if quote.stock_id in self._volume_cache:
                # Only update if new total is greater (prevent out-of-order jitter)
                if current_vol > self._volume_cache[quote.stock_id]:
                    self._volume_cache[quote.stock_id] = current_vol
                    logger.debug(f"[Quote] {quote.stock_id} cache update: {old_vol} -> {current_vol}")
            else:
                self._volume_cache[quote.stock_id] = current_vol
                logger.debug(f"[Quote] {quote.stock_id} cache init: {current_vol}")
        except Exception as e:
            logger.error(f"Error processing quote volume: {e}")

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

            # --- Fix: Maintain accumulated volume ---
            # Shioaji tick comes with accumulated_volume=0. We must calculate it.
            
            # Initialize cache if needed
            if stock_id not in self._volume_cache:
                try:
                    existing_data = self.storage.load_intraday_data(stock_id, date.today())
                    if existing_data and existing_data.ticks:
                        self._volume_cache[stock_id] = existing_data.ticks[-1].accumulated_volume
                    else:
                        self._volume_cache[stock_id] = 0
                except Exception:
                    self._volume_cache[stock_id] = 0
            
            # Update volume
            tick_vol = int(tick.volume)
            old_cache = self._volume_cache[stock_id]
            
            self._volume_cache[stock_id] += tick_vol
            tick.accumulated_volume = self._volume_cache[stock_id]
            
            logger.debug(f"[Tick] {stock_id} vol:{tick_vol} cache:{old_cache}->{self._volume_cache[stock_id]}")
            # ----------------------------------------

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
