"""
Per-minute volume spike detection job.

Runs once per minute (cron: second=5, slightly after the bar closes
so the broker has a chance to publish the most recent K bar). For
each tracked stock:

    fetch the previous-minute K bar  →  persist  →  detect  →
    if is_volume_spike: push to SpikeDetectionStore.

Job is scoped to trading hours (Scheduler.is_market_open). Failures
on individual stocks are logged but never raised so the APScheduler
worker keeps running for the next minute.
"""

from __future__ import annotations

import logging
import traceback
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Callable, List
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from src.data.spike_store import SpikeDetectionStore
    from src.fetcher.shioaji_fetcher import ShioajiFetcher
    from src.processor.volume_spike_detector import VolumeSpikeDetector
    from src.storage.minute_kbar_storage import MinuteKBarStorage

logger = logging.getLogger("autofetchstock.scheduler.volume_spike")
_TZ_TAIPEI = ZoneInfo("Asia/Taipei")


class VolumeSpikeJob:
    """Glue object handed to Scheduler.add_volume_spike_job."""

    def __init__(
        self,
        fetcher: "ShioajiFetcher",
        storage: "MinuteKBarStorage",
        detector: "VolumeSpikeDetector",
        detection_store: "SpikeDetectionStore",
        tracked_stocks_provider: Callable[[], List[str]],
    ) -> None:
        self.fetcher = fetcher
        self.storage = storage
        self.detector = detector
        self.detection_store = detection_store
        self.tracked_stocks_provider = tracked_stocks_provider

    def run_once(self) -> None:
        """Execute one detection sweep across all tracked stocks."""
        try:
            tracked = list(self.tracked_stocks_provider() or [])
        except Exception as exc:
            logger.error("[spike_job] tracked_stocks_provider failed: %s", exc)
            return

        if not tracked:
            logger.debug("[spike_job] no tracked stocks")
            return

        now = datetime.now(_TZ_TAIPEI).replace(second=0, microsecond=0)
        target_minute = now - timedelta(minutes=1)
        target_time = target_minute.time()
        target_date = target_minute.date()

        for stock_id in tracked:
            try:
                self._process_stock(stock_id, target_date, target_time)
            except Exception as exc:
                logger.warning(
                    "[spike_job] %s failed at %s: %s\n%s",
                    stock_id, target_minute, exc, traceback.format_exc(),
                )

        logger.debug(
            "[spike_job] swept %d stocks for minute %s",
            len(tracked), target_minute.strftime("%H:%M"),
        )

    # ── internals ──────────────────────────────────────────────────────────

    def _process_stock(
        self, stock_id: str, target_date: date, target_time
    ) -> None:
        bars = self.fetcher.fetch_minute_kbars(
            stock_id,
            target_date,
            start_time=target_time,
            end_time=target_time,
        )
        if not bars:
            logger.debug(
                "[spike_job] %s: no bar yet for %s", stock_id, target_time
            )
            return

        bar = bars[0]
        # Detector uses storage for baseline lookup — historical days only,
        # so it's safe to detect BEFORE persisting today's just-closed bar.
        detected = self.detector.detect(bar)
        self.storage.append_bar(stock_id, "", detected)

        if detected.is_volume_spike:
            self.detection_store.add_spike(stock_id, detected)
            logger.info(
                "[spike_job] SPIKE %s @ %s vol=%d ratio=%.2f severity=%s",
                stock_id,
                detected.timestamp.strftime("%H:%M"),
                detected.volume,
                detected.volume_ratio or 0.0,
                detected.spike_severity.value,
            )
