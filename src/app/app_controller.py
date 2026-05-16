"""
Application controller for autoFetchStock.

This module is the main orchestrator that initializes all components
and manages the Dash application lifecycle.
"""

import logging
from typing import Optional

from dash import Dash

from src.config import AppConfig, setup_logging
from src.data import advisor as advisor_module
from src.data import fundamentals as fundamentals_module
from src.fetcher import DataFetcher
from src.fetcher.shioaji_fetcher import ShioajiFetcher
from src.fetcher.minute_kbar_warmup import MinuteKBarWarmup
from src.storage import DataStorage
from src.storage.minute_kbar_storage import MinuteKBarStorage
from src.processor.volume_spike_detector import VolumeSpikeDetector
from src.data.spike_store import SpikeDetectionStore
from src.scheduler.volume_spike_job import VolumeSpikeJob
from src.processor.data_processor import DataProcessor
from src.renderer.chart_renderer import ChartRenderer
from src.scheduler import Scheduler
from src.news.news_processor import NewsProcessor
from src.app.layout import create_layout
from src.app.callbacks import CallbackManager
from src.app.intraday_guard import (
    quote_timestamp_matches_trade_date,
    timestamp_matches_trade_date,
)

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

    _TPEX_T86_SENTINEL_IDS = ("3081", "3363", "3163", "6187")
    _TPEX_MARGIN_SENTINEL_IDS = ("3081", "3363", "3163", "6187")

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

        # Volume Spike Detection: minute-kbar storage + warmup backfiller
        self.minute_kbar_storage = MinuteKBarStorage()
        self.minute_kbar_warmup = MinuteKBarWarmup(
            fetcher=self.shioaji_fetcher,
            storage=self.minute_kbar_storage,
        )
        self.volume_spike_detector = VolumeSpikeDetector(
            storage=self.minute_kbar_storage,
        )
        self.spike_detection_store = SpikeDetectionStore()
        logger.debug(
            "MinuteKBarStorage + MinuteKBarWarmup + VolumeSpikeDetector + "
            "SpikeDetectionStore initialized"
        )

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

        # Volume Spike Detection: per-minute job over favorite stocks.
        # tracked_stocks_provider must be a fresh-on-each-call lambda so
        # newly added favorites get detected without restart.
        self.volume_spike_job = VolumeSpikeJob(
            fetcher=self.shioaji_fetcher,
            storage=self.minute_kbar_storage,
            detector=self.volume_spike_detector,
            detection_store=self.spike_detection_store,
            tracked_stocks_provider=lambda: [
                fav.get("id") for fav in (self.storage.load_favorites() or [])
                if fav.get("id")
            ],
        )
        self.scheduler.add_volume_spike_job(self.volume_spike_job)
        logger.debug("VolumeSpikeJob registered with Scheduler")

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

        # Phase 3.5 #4 — MarketStrip indices (Shioaji local + yfinance foreign).
        from src.fetcher.index_fetcher import IndexFetcher
        self.index_fetcher = IndexFetcher()

        # Phase 7.4 — fundamentals disk cache + daily 16:35 warmup + boot catchup.
        # Typical usage: app closes after market, opens before market open next
        # day. So at every boot, check disk cache freshness for favorites and
        # refetch any missing/stale entries in a background thread.
        fundamentals_module.configure_disk_cache(self.config.data_dir)
        self.scheduler.add_fundamentals_warmup_job(self._run_fundamentals_warmup)
        self._catchup_fundamentals()

        # Phase 7.4 — AI advisor LLM scorer + watchlist warmup.
        advisor_module.configure(self.config)
        runtime = advisor_module.get_runtime()
        if runtime and runtime.enabled:
            self.scheduler.add_advisor_warmup_job(
                self._run_advisor_warmup,
                interval_minutes=self.config.advisor_warmup_interval_min,
            )

    def _run_fundamentals_warmup(self, *, force: bool = True) -> None:
        """Refresh fundamentals for every favorite. Called by 16:35 cron + boot catchup."""
        try:
            favorites = self.storage.load_favorites() or []
        except Exception as exc:
            logger.warning("fundamentals warmup: load favorites failed: %s", exc)
            return
        if not favorites:
            return
        success = 0
        for fav in favorites:
            stock_id = fav.get("id")
            if not stock_id:
                continue
            try:
                if fundamentals_module.warmup(stock_id, force=force):
                    success += 1
            except Exception as exc:
                logger.debug("fundamentals warmup [%s] failed: %s", stock_id, exc)
        logger.info("fundamentals warmup done: %d/%d refreshed", success, len(favorites))

    def _catchup_fundamentals(self) -> None:
        """Boot-time catchup: refetch favorites whose disk cache is stale/missing.

        Runs in a background thread so the Dash dev server boots immediately.
        Skips already-fresh entries so a quick app restart doesn't re-burn
        endpoints. ``force=False`` honors fresh disk cache.
        """
        import threading

        try:
            favorites = self.storage.load_favorites() or []
        except Exception as exc:
            logger.warning("fundamentals catchup: load favorites failed: %s", exc)
            return
        stale = [
            f for f in favorites
            if f.get("id") and not fundamentals_module.is_disk_cache_fresh(f["id"])
        ]
        if not stale:
            logger.info("fundamentals catchup: all %d favorites have fresh cache", len(favorites))
            return
        logger.info(
            "fundamentals catchup: %d/%d favorites need refresh",
            len(stale), len(favorites),
        )

        def _run() -> None:
            for fav in stale:
                stock_id = fav.get("id")
                if not stock_id:
                    continue
                try:
                    fundamentals_module.warmup(stock_id, force=False)
                except Exception as exc:
                    logger.debug("fundamentals catchup [%s] failed: %s", stock_id, exc)
            logger.info("fundamentals catchup done")

        threading.Thread(target=_run, daemon=True, name="fund-catchup").start()

    def _run_advisor_warmup(self) -> None:
        """Iterate watchlist and refresh advisor cache via LLM."""
        from datetime import datetime, timezone, timedelta
        from src.app.callbacks import _extract_articles_from_run
        from src.data.chips_kpi import build_chips_kpi
        from src.data.fundamentals import get_fundamentals

        runtime = advisor_module.get_runtime()
        if not (runtime and runtime.enabled):
            return
        try:
            favorites = self.storage.load_favorites() or []
        except Exception as exc:
            logger.warning("advisor warmup: load favorites failed: %s", exc)
            return
        if not favorites:
            return

        today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        try:
            news_file = self.storage.load_news(today)
        except Exception as exc:
            logger.debug("advisor warmup: news load failed: %s", exc)
            news_file = None
        run_dict = news_file.to_dict() if news_file else {}

        success = 0
        for fav in favorites:
            if not runtime.quota.can_call():
                logger.info("advisor warmup stopped: daily quota exhausted")
                break
            stock_id = fav.get("id")
            stock_name = fav.get("name") or stock_id
            if not stock_id:
                continue
            articles = _extract_articles_from_run(
                run_dict, "ALL", stock_id, stock_name,
            ) if run_dict else []
            try:
                cards = build_chips_kpi(stock_id, self.chips_storage)
            except Exception:
                cards = []
            try:
                fundamentals = get_fundamentals(stock_id)
            except Exception:
                fundamentals = None
            quote = None
            try:
                if self.fetcher:
                    get_cached_quote = getattr(self.fetcher, "get_cached_quote", None)
                    if callable(get_cached_quote):
                        quote = get_cached_quote(stock_id)
            except Exception:
                quote = None
            closes = self._load_daily_closes_for_advisor(stock_id)
            if advisor_module.warmup(
                stock_id,
                stock_name=stock_name,
                articles=articles,
                chip_cards=cards,
                fundamentals=fundamentals,
                quote=quote,
                daily_closes=closes,
            ):
                success += 1
        logger.info(
            "advisor warmup done: %d/%d refreshed (remaining quota %d)",
            success, len(favorites), runtime.quota.remaining(),
        )

    def _load_daily_closes_for_advisor(self, stock_id: str, limit: int = 80) -> list:
        if not self.storage or not stock_id:
            return []
        try:
            daily = self.storage.load_daily_data(stock_id)
        except Exception:
            return []
        closes = []
        for row in (getattr(daily, "daily_data", None) or [])[-limit:]:
            close = getattr(row, "close", None)
            if isinstance(close, (int, float)):
                closes.append(float(close))
        return closes

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

                    # Volume Spike Detection: backfill 5 trading days of 1-min K
                    # bars in the background so 法 B baselines are available
                    # immediately. No-op if disk already has enough days.
                    try:
                        self.minute_kbar_warmup.warmup_async(
                            stock_id, stock_name=fav.get("name", "")
                        )
                    except Exception as exc:
                        logger.debug("warmup_async(%s) failed: %s", stock_id, exc)
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
            index_fetcher=self.index_fetcher,
            spike_detection_store=self.spike_detection_store,
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
        """Scheduled-job body: fetch today's T86 + MI_MARGN from both
        TWSE (上市) and TPEX (上櫃) and persist as a single merged daily
        snapshot. Stock IDs do not collide across markets so a flat dict
        union is safe. Phase 7.2: TPEX coverage so small-cap OTC names
        (e.g. 聯亞 3081) surface real chip data.
        """
        from datetime import date as _date
        today = _date.today()

        # ── T86 (三大法人買賣超) ────────────────────────────────────
        merged_t86: dict = {}
        try:
            twse = self.chips_fetcher.fetch_t86(today)
            if twse:
                merged_t86.update(twse)
        except Exception as exc:
            logger.warning("Scheduled chips TWSE T86 fetch failed: %s", exc)
        try:
            tpex = self.chips_fetcher.fetch_tpex_t86(today)
            if tpex:
                merged_t86.update(tpex)
        except Exception as exc:
            logger.warning("Scheduled chips TPEX T86 fetch failed: %s", exc)
        if merged_t86:
            self.chips_storage.save_t86_snapshot(today, merged_t86)
            logger.info(
                "Scheduled chips T86: saved %s (%d stocks across TWSE+TPEX)",
                today, len(merged_t86),
            )
        else:
            logger.info("Scheduled chips T86: no data for %s yet", today)

        # ── MI_MARGN (融資融券餘額) ─────────────────────────────────
        merged_margin: dict = {}
        try:
            twse_m = self.chips_fetcher.fetch_margin(today)
            if twse_m:
                merged_margin.update(twse_m)
        except Exception as exc:
            logger.warning("Scheduled MI_MARGN TWSE fetch failed: %s", exc)
        try:
            tpex_m = self.chips_fetcher.fetch_tpex_margin(today)
            if tpex_m:
                merged_margin.update(tpex_m)
        except Exception as exc:
            logger.warning("Scheduled MI_MARGN TPEX fetch failed: %s", exc)
        if merged_margin:
            self.chips_storage.save_margin_snapshot(today, merged_margin)
            logger.info(
                "Scheduled MI_MARGN: saved %s (%d stocks across TWSE+TPEX)",
                today, len(merged_margin),
            )
        else:
            logger.info("Scheduled MI_MARGN: no data for %s yet", today)

    def _catchup_chips_t86(self) -> None:
        """Backfill or repair the most recent T86 snapshot on startup.

        Runs in a background thread so the app can boot immediately;
        TWSE responses can take a few seconds and we don't want to
        block the Dash dev server. Walks back up to 7 calendar days
        to land on the last actual trading day. Existing snapshots from
        before TPEX support are repaired by merging in TPEX rows.
        """
        import threading

        latest_t86_date = self.chips_storage.latest_snapshot_date()
        latest_margin_date = self.chips_storage.latest_margin_date()
        need_t86 = latest_t86_date is None
        repair_tpex_t86 = (
            latest_t86_date is not None
            and self._t86_snapshot_needs_tpex_repair(latest_t86_date)
        )
        need_margin = latest_margin_date is None
        repair_tpex_margin = (
            latest_margin_date is not None
            and self._margin_snapshot_needs_tpex_repair(latest_margin_date)
        )
        if not need_t86 and not repair_tpex_t86 and not need_margin and not repair_tpex_margin:
            return

        def _run() -> None:
            if need_t86:
                try:
                    self._catchup_t86_merged()
                except Exception as exc:
                    logger.warning("Chips T86 catch-up failed: %s", exc)
            elif repair_tpex_t86:
                try:
                    self._repair_t86_tpex_snapshot(latest_t86_date)
                except Exception as exc:
                    logger.warning("Chips T86 TPEX repair failed: %s", exc)
            if need_margin:
                try:
                    self._catchup_margin_window()
                except Exception as exc:
                    logger.warning("MI_MARGN catch-up failed: %s", exc)
            elif repair_tpex_margin:
                try:
                    self._repair_margin_tpex_snapshot(latest_margin_date)
                except Exception as exc:
                    logger.warning("MI_MARGN TPEX repair failed: %s", exc)

        threading.Thread(
            target=_run,
            name="chips-t86-catchup",
            daemon=True,
        ).start()

    def _t86_snapshot_needs_tpex_repair(self, snapshot_date) -> bool:
        """Return True when the latest T86 cache appears to miss TPEX rows."""
        snapshot = self.chips_storage.load_t86_day(snapshot_date)
        if not snapshot:
            return True
        return not any(sid in snapshot for sid in self._TPEX_T86_SENTINEL_IDS)

    def _repair_t86_tpex_snapshot(self, snapshot_date) -> None:
        """Merge TPEX T86 rows into an existing daily cache file."""
        existing = self.chips_storage.load_t86_day(snapshot_date) or {}
        tpex = self.chips_fetcher.fetch_tpex_t86(snapshot_date)
        if tpex is None:
            logger.info("Chips T86 TPEX repair: fetch failed for %s", snapshot_date)
            return
        if not tpex:
            logger.info("Chips T86 TPEX repair: no TPEX rows for %s", snapshot_date)
            return

        merged = dict(existing)
        changed = False
        new_rows = 0
        for stock_id, row in tpex.items():
            if stock_id not in merged:
                new_rows += 1
            if merged.get(stock_id) != row:
                merged[stock_id] = row
                changed = True

        if not changed:
            logger.info("Chips T86 TPEX repair: snapshot already complete for %s", snapshot_date)
            return

        self.chips_storage.save_t86_snapshot(snapshot_date, merged)
        logger.info(
            "Chips T86 TPEX repair saved snapshot for %s (%d TPEX rows, %d new, %d total)",
            snapshot_date, len(tpex), new_rows, len(merged),
        )

    def _margin_snapshot_needs_tpex_repair(self, snapshot_date) -> bool:
        """Return True when the latest MI_MARGN cache appears to miss TPEX rows."""
        snapshot = self.chips_storage.load_margin_day(snapshot_date)
        if not snapshot:
            return True
        return not any(sid in snapshot for sid in self._TPEX_MARGIN_SENTINEL_IDS)

    def _repair_margin_tpex_snapshot(self, snapshot_date) -> None:
        """Merge TPEX MI_MARGN rows into an existing daily cache file."""
        existing = self.chips_storage.load_margin_day(snapshot_date) or {}
        tpex = self.chips_fetcher.fetch_tpex_margin(snapshot_date)
        if tpex is None:
            logger.info("MI_MARGN TPEX repair: fetch failed for %s", snapshot_date)
            return
        if not tpex:
            logger.info("MI_MARGN TPEX repair: no TPEX rows for %s", snapshot_date)
            return

        merged = dict(existing)
        changed = False
        new_rows = 0
        for stock_id, row in tpex.items():
            if stock_id not in merged:
                new_rows += 1
            if merged.get(stock_id) != row:
                merged[stock_id] = row
                changed = True

        if not changed:
            logger.info("MI_MARGN TPEX repair: snapshot already complete for %s", snapshot_date)
            return

        self.chips_storage.save_margin_snapshot(snapshot_date, merged)
        logger.info(
            "MI_MARGN TPEX repair saved snapshot for %s (%d TPEX rows, %d new, %d total)",
            snapshot_date, len(tpex), new_rows, len(merged),
        )

    def _catchup_t86_merged(self, max_lookback_days: int = 7) -> None:
        """Walk back day-by-day to find the most recent T86 snapshot,
        fetching TWSE + TPEX in parallel and merging both before save.
        Runs only when storage holds nothing.
        """
        from datetime import date as _date, timedelta as _td

        cur = _date.today()
        for _ in range(max_lookback_days + 1):
            merged: dict = {}
            try:
                twse = self.chips_fetcher.fetch_t86(cur)
                if twse:
                    merged.update(twse)
            except Exception as exc:
                logger.debug("T86 catch-up TWSE %s failed: %s", cur, exc)
            try:
                tpex = self.chips_fetcher.fetch_tpex_t86(cur)
                if tpex:
                    merged.update(tpex)
            except Exception as exc:
                logger.debug("T86 catch-up TPEX %s failed: %s", cur, exc)

            if merged:
                self.chips_storage.save_t86_snapshot(cur, merged)
                logger.info(
                    "Chips T86 catch-up saved snapshot for %s (%d stocks across TWSE+TPEX)",
                    cur, len(merged),
                )
                return
            cur -= _td(days=1)
        logger.info("Chips T86 catch-up: no snapshot in last %d days", max_lookback_days)

    def _catchup_margin_window(self, max_days: int = 25) -> None:
        """Walk back day-by-day collecting MI_MARGN snapshots (TWSE +
        TPEX merged) until the storage holds ~20 trading days. Runs only
        when storage is empty.
        """
        from datetime import date as _date, timedelta as _td

        cur = _date.today()
        saved = 0
        for _ in range(max_days):
            if saved >= 20:
                break
            merged: dict = {}
            try:
                twse_m = self.chips_fetcher.fetch_margin(cur)
                if twse_m:
                    merged.update(twse_m)
            except Exception as exc:
                logger.debug("MI_MARGN catch-up TWSE %s failed: %s", cur, exc)
            try:
                tpex_m = self.chips_fetcher.fetch_tpex_margin(cur)
                if tpex_m:
                    merged.update(tpex_m)
            except Exception as exc:
                logger.debug("MI_MARGN catch-up TPEX %s failed: %s", cur, exc)
            if merged:
                self.chips_storage.save_margin_snapshot(cur, merged)
                saved += 1
            cur -= _td(days=1)
        logger.info("MI_MARGN catch-up saved %d days (TWSE+TPEX merged)", saved)

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
        trade_date = date.today()
        if not quote_timestamp_matches_trade_date(quote, trade_date):
            logger.debug(
                "Skip saving stale quote for %s: timestamp=%s trade_date=%s",
                quote.stock_id,
                quote.timestamp,
                trade_date,
            )
            return

        try:
            # Load previous ticks to calculate volume delta and price trend (REQ-FixVolume0)
            last_accumulated_volume = 0
            last_price = quote.previous_close # Default
            last_tick_time = None
            
            existing_data = self.storage.load_intraday_data(quote.stock_id, trade_date)
            stream_sum = 0
            has_accumulated_anchor = False
            
            if existing_data and existing_data.ticks:
                last_tick = existing_data.ticks[-1]
                last_price = last_tick.price
                last_tick_time = last_tick.timestamp
                if not last_tick_time and hasattr(last_tick, 'time'):
                     last_tick_time = datetime.combine(trade_date, last_tick.time)
                
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
                trade_date=trade_date,
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
            trade_date = date.today()
            if not timestamp_matches_trade_date(getattr(tick, "timestamp", None), trade_date):
                logger.debug(
                    "Skip saving stale Shioaji tick for %s: timestamp=%s trade_date=%s",
                    stock_id,
                    getattr(tick, "timestamp", None),
                    trade_date,
                )
                return

            # --- Fix: Maintain accumulated volume ---
            # Shioaji tick comes with accumulated_volume=0. We must calculate it.
            
            # Initialize cache if needed
            if stock_id not in self._volume_cache:
                try:
                    existing_data = self.storage.load_intraday_data(stock_id, trade_date)
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
