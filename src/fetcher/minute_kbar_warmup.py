"""
Backfill 5 trading days of 1-minute K bars for newly tracked stocks.

Volume Spike Detection's preferred baseline (法 B) needs same-time-of-day
samples across past trading days. Without this warmup, every new stock
falls back to 法 A (recent-N intraday bars) and ships with the
`baseline_low_confidence` flag for the first ~1 hour of trading.

Usage:
    warmup = MinuteKBarWarmup(shioaji_fetcher, minute_kbar_storage)
    warmup.warmup_async("2330")   # fire-and-forget, runs in daemon thread
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, timedelta
from typing import TYPE_CHECKING, Optional

from src.config import SPIKE_BASELINE_DAYS, SPIKE_BASELINE_MIN_DAYS
from src.models import StockMinuteKFile
from src.storage.minute_kbar_storage import MinuteKBarStorage

if TYPE_CHECKING:
    from src.fetcher.shioaji_fetcher import ShioajiFetcher

logger = logging.getLogger("autofetchstock.fetcher.warmup")


class MinuteKBarWarmup:
    """Background backfill of 1-min K bars (Shioaji-only)."""

    # Shioaji quota: keep <= 2 API calls/sec across all warmup threads.
    _RATE_LIMIT_SECONDS: float = 0.5
    _RETRY_PER_DAY: int = 1

    def __init__(
        self,
        fetcher: "ShioajiFetcher",
        storage: MinuteKBarStorage,
    ) -> None:
        self.fetcher = fetcher
        self.storage = storage
        self._rate_lock = threading.Lock()
        self._inflight: set[str] = set()
        self._inflight_lock = threading.Lock()

    # ── public API ─────────────────────────────────────────────────────────

    def needs_warmup(self, stock_id: str, today: Optional[date] = None) -> bool:
        """
        True when fewer than SPIKE_BASELINE_MIN_DAYS prior trading days
        already have minute-kbar files on disk.
        """
        days_with_data = 0
        for d in self._iter_recent_trading_days(SPIKE_BASELINE_DAYS, today):
            if self.storage.load(stock_id, d) is not None:
                days_with_data += 1
        return days_with_data < SPIKE_BASELINE_MIN_DAYS

    def warmup_async(
        self,
        stock_id: str,
        stock_name: str = "",
        today: Optional[date] = None,
    ) -> Optional[threading.Thread]:
        """
        Spawn a daemon thread to backfill if needed. Returns the Thread
        (or None if a warmup is already in flight for this stock).
        Caller does not need to join — thread will not block shutdown.
        """
        with self._inflight_lock:
            if stock_id in self._inflight:
                logger.debug("[warmup] %s already in progress, skipping", stock_id)
                return None
            self._inflight.add(stock_id)

        thread = threading.Thread(
            target=self._warmup_sync,
            args=(stock_id, stock_name, today),
            name=f"warmup-{stock_id}",
            daemon=True,
        )
        thread.start()
        return thread

    # ── internals ──────────────────────────────────────────────────────────

    def _warmup_sync(
        self, stock_id: str, stock_name: str, today: Optional[date]
    ) -> None:
        try:
            if not self.needs_warmup(stock_id, today):
                logger.debug("[warmup] %s already covered, skipping", stock_id)
                return

            total = 0
            for d in self._iter_recent_trading_days(SPIKE_BASELINE_DAYS, today):
                if self.storage.load(stock_id, d) is not None:
                    continue
                saved = self._backfill_day_with_retry(stock_id, stock_name, d)
                total += saved
            logger.info("[warmup] %s done: %d bars backfilled", stock_id, total)
        finally:
            with self._inflight_lock:
                self._inflight.discard(stock_id)

    def _backfill_day_with_retry(
        self, stock_id: str, stock_name: str, target_date: date
    ) -> int:
        for attempt in range(self._RETRY_PER_DAY + 1):
            try:
                return self._backfill_day(stock_id, stock_name, target_date)
            except Exception as exc:
                if attempt >= self._RETRY_PER_DAY:
                    logger.warning(
                        "[warmup] %s %s failed after %d attempts: %s",
                        stock_id, target_date, attempt + 1, exc,
                    )
                    return 0
                logger.debug(
                    "[warmup] %s %s attempt %d failed: %s — retry",
                    stock_id, target_date, attempt + 1, exc,
                )
        return 0

    def _backfill_day(
        self, stock_id: str, stock_name: str, target_date: date
    ) -> int:
        with self._rate_lock:
            bars = self.fetcher.fetch_minute_kbars(stock_id, target_date)
            time.sleep(self._RATE_LIMIT_SECONDS)

        if not bars:
            logger.debug("[warmup] %s %s: no bars returned", stock_id, target_date)
            return 0

        file = StockMinuteKFile(
            stock_id=stock_id,
            stock_name=stock_name,
            date=target_date,
            bars=bars,
        )
        self.storage.save(file)
        logger.debug(
            "[warmup] %s %s: %d bars saved", stock_id, target_date, len(bars)
        )
        return len(bars)

    @staticmethod
    def _iter_recent_trading_days(n: int, today: Optional[date] = None):
        """Yield the most recent n trading days STRICTLY BEFORE today."""
        cursor = (today or date.today()) - timedelta(days=1)
        yielded = 0
        scanned = 0
        while yielded < n and scanned < n * 3 + 7:
            if cursor.weekday() < 5:
                yield cursor
                yielded += 1
            cursor -= timedelta(days=1)
            scanned += 1
