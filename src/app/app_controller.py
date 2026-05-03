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
        
        # Volume cache for real-time accumulation {stock_id: total_volume}
        self._volume_cache = {}
        
        # Buffer for batching tick writes to reduce I/O
        import threading
        self._tick_buffer = {}
        self._buffer_lock = threading.Lock()
        self._stop_event = threading.Event()

        # Initialize components
        self._init_components()

        # Create Dash application
        self._init_dash_app()

        # Load existing data on startup (REQ-073)
        self._load_existing_data()
        
        # Start background flush thread
        self._flush_thread = threading.Thread(target=self._flush_ticks_loop, daemon=True)
        self._flush_thread.start()

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
        else:
            logger.warning("ShioajiFetcher failed to login, fallback to TWSE only")

        # Data fetcher with storage for cache and Shioaji fetcher
        self.fetcher = DataFetcher(
            storage=self.storage,
            shioaji_fetcher=self.shioaji_fetcher
        )
        logger.debug("DataFetcher initialized")

        # Auto-subscribe to saved favorites after DataFetcher exists so cache warm-up works.
        if self.shioaji_fetcher and self.shioaji_fetcher.is_connected:
            self._subscribe_saved_favorites()
        
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

        self._catchup_news_event_timeline()
        if self.config.news_rag_enabled:
            self._catchup_news_rag_index()

        # Phase 3.5 #3 — TWSE chip-flow (T86) fetcher + per-day storage.
        # On startup we backfill the most recent snapshot so ChipsKpi
        # cards show real data on first paint instead of the STUB.
        from src.fetcher.chips_fetcher import ChipsFetcher
        from src.storage.chips_storage import ChipsStorage
        self.chips_storage = ChipsStorage(data_dir=self.config.data_dir)
        self.chips_fetcher = ChipsFetcher()
        self.scheduler.add_chips_t86_job(self._run_chips_t86_fetch)
        self._catchup_chips_t86()

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
            on_init_volume=self.init_volume_cache,
            get_buffered_ticks=self._get_buffered_ticks,
            news_processor=self.news_processor,
            chips_storage=self.chips_storage,
        )

        # Register all callbacks
        self.callback_manager.register_callbacks()

        logger.debug("Dash app initialized")

    def _get_buffered_ticks(self, stock_id: str):
        """Retrieve ticks currently in the memory buffer for a stock (thread-safe)."""
        with self._buffer_lock:
            if stock_id in self._tick_buffer:
                # Return a copy to avoid mutation during iteration
                return list(self._tick_buffer[stock_id]["ticks"])
            return []

    def _run_chips_t86_fetch(self) -> None:
        """Scheduled-job body: fetch today's T86 and persist."""
        from datetime import date as _date
        try:
            today = _date.today()
            snap = self.chips_fetcher.fetch_t86(today)
            if not snap:
                logger.info("Scheduled chips T86: no data for %s yet", today)
                return
            self.chips_storage.save_t86_snapshot(today, snap)
            logger.info("Scheduled chips T86: saved %s (%d stocks)", today, len(snap))
        except Exception as exc:
            logger.warning("Scheduled chips T86 fetch failed: %s", exc)

    def _catchup_chips_t86(self) -> None:
        """Backfill the most recent T86 snapshot if storage is empty.

        Runs in a background thread so the app can boot immediately;
        TWSE responses can take a few seconds and we don't want to
        block the Dash dev server. Walks back up to 7 calendar days
        to land on the last actual trading day.
        """
        import threading
        from datetime import date as _date

        if self.chips_storage.latest_snapshot_date() is not None:
            return

        def _run() -> None:
            try:
                result = self.chips_fetcher.latest_available()
                if not result:
                    logger.info("Chips T86 catch-up: no snapshot available in last 7 days")
                    return
                snap_date, by_stock = result
                self.chips_storage.save_t86_snapshot(snap_date, by_stock)
                logger.info(
                    "Chips T86 catch-up saved snapshot for %s (%d stocks)",
                    snap_date,
                    len(by_stock),
                )
            except Exception as exc:
                logger.warning("Chips T86 catch-up failed: %s", exc)

        threading.Thread(
            target=_run,
            name="chips-t86-catchup",
            daemon=True,
        ).start()

    def _catchup_news_event_timeline(self) -> None:
        """Run the daily event timeline build if it was missed today.

        APScheduler skips fired-while-offline jobs once `misfire_grace_time`
        elapses, so a server downtime spanning 16:05 Asia/Taipei would defer
        the timeline by a full day. Detect that gap on startup and rebuild
        in the background.
        """
        import threading
        from datetime import datetime, time
        from zoneinfo import ZoneInfo

        tw_tz = ZoneInfo("Asia/Taipei")
        now_tw = datetime.now(tw_tz)
        schedule_cutoff = time(16, 5)

        if now_tw.time() < schedule_cutoff:
            return

        try:
            events = self.storage.load_news_events()
        except Exception as e:
            logger.warning(f"Event timeline catch-up check failed: {e}")
            return

        if events is not None:
            gen_dt = events.generated_at
            if gen_dt.tzinfo is None:
                gen_date = gen_dt.date()
            else:
                gen_date = gen_dt.astimezone(tw_tz).date()
            if gen_date >= now_tw.date():
                return

        logger.info(
            "Event timeline missing for today (last=%s), starting catch-up build",
            events.generated_at.isoformat() if events else "none",
        )

        def _run() -> None:
            try:
                self.news_processor.build_event_timeline(
                    self.config.news_history_window_days
                )
                logger.info("Event timeline catch-up build completed")
            except Exception as exc:
                logger.error(f"Event timeline catch-up build failed: {exc}")

        threading.Thread(
            target=_run,
            name="event-timeline-catchup",
            daemon=True,
        ).start()

    def _catchup_news_rag_index(self) -> None:
        """Run the daily RAG index update if it was missed today.

        Mirrors `_catchup_news_event_timeline`. The RAG job runs at 16:20
        Asia/Taipei; freshness is detected via `updated_at` in
        `data/news/rag_metadata.json`.
        """
        import json
        import threading
        from datetime import datetime, time
        from zoneinfo import ZoneInfo

        tw_tz = ZoneInfo("Asia/Taipei")
        now_tw = datetime.now(tw_tz)
        schedule_cutoff = time(16, 20)

        if now_tw.time() < schedule_cutoff:
            return

        metadata_path = self.storage.news_dir / "rag_metadata.json"
        last_updated: Optional[datetime] = None
        if metadata_path.exists():
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                ts = raw.get("updated_at")
                if ts:
                    last_updated = datetime.fromisoformat(ts)
            except Exception as e:
                logger.warning(f"RAG index catch-up check failed to read metadata: {e}")
                return

        if last_updated is not None:
            if last_updated.tzinfo is None:
                last_date = last_updated.date()
            else:
                last_date = last_updated.astimezone(tw_tz).date()
            if last_date >= now_tw.date():
                return

        logger.info(
            "RAG index missing for today (last=%s), starting catch-up build",
            last_updated.isoformat() if last_updated else "none",
        )

        def _run() -> None:
            import time as _time
            passes = 2  # mirror the two daily scheduled jobs (16:20, 16:21)
            for slot in range(1, passes + 1):
                try:
                    added = self.news_processor.update_rag_index(
                        self.config.news_rag_window_days
                    )
                    logger.info(
                        "RAG index catch-up pass %d/%d completed: %d new embeddings",
                        slot,
                        passes,
                        added,
                    )
                except Exception as exc:
                    logger.error(f"RAG index catch-up pass {slot} failed: {exc}")
                if slot < passes:
                    _time.sleep(65)  # let the per-minute embedding quota reset

        threading.Thread(
            target=_run,
            name="rag-index-catchup",
            daemon=True,
        ).start()

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
            has_accumulated_anchor = False
            
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
                    if tick_volume > 0:
                        logger.info(f"SaveTick {quote.stock_id}: LastAcc={last_accumulated_volume}, CurrTotal={quote.total_volume}, Delta={delta}, StreamSum={stream_sum} -> TickVol={tick_volume}")
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

    def _flush_ticks_loop(self):
        """Background loop to periodically flush buffered ticks to disk."""
        import time
        from datetime import date
        while not self._stop_event.is_set():
            time.sleep(5) # Flush every 5 seconds
            try:
                ticks_to_save = {}
                with self._buffer_lock:
                    if not self._tick_buffer:
                        continue
                    # Swap buffers
                    ticks_to_save = self._tick_buffer
                    self._tick_buffer = {}
                
                # Write to disk outside the lock
                for stock_id, data in ticks_to_save.items():
                    if data["ticks"]:
                        self.storage.save_intraday_data(
                            stock_id=stock_id,
                            stock_name=data["stock_name"],
                            trade_date=date.today(),
                            previous_close=data["reference"],
                            ticks=data["ticks"]
                        )
                        logger.debug(f"Flushed {len(data['ticks'])} ticks for {stock_id}")
            except Exception as e:
                logger.error(f"Error in tick flush loop: {e}")

    def shutdown(self) -> None:
        """Gracefully shutdown all components."""
        logger.info("Shutting down AppController...")

        self._stop_event.set()
        if hasattr(self, '_flush_thread'):
            self._flush_thread.join(timeout=2)

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

            # Buffer tick for batch saving
            with self._buffer_lock:
                if stock_id not in self._tick_buffer:
                    self._tick_buffer[stock_id] = {
                        "stock_name": stock_name,
                        "reference": reference,
                        "ticks": []
                    }
                self._tick_buffer[stock_id]["ticks"].append(tick)
                
        except Exception as e:
            logger.error(f"Error buffering Shioaji tick: {e}")

    @property
    def server(self):
        """Get the underlying Flask server for WSGI deployment."""
        return self.app.server
