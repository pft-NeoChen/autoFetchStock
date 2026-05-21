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
import time
import traceback
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Callable, List, Optional
from zoneinfo import ZoneInfo

from src.fetcher.ticks_budget import TicksFallbackBudget

if TYPE_CHECKING:
    from src.data.spike_store import SpikeDetectionStore
    from src.fetcher.shioaji_fetcher import ShioajiFetcher
    from src.processor.volume_spike_detector import VolumeSpikeDetector
    from src.storage.minute_kbar_storage import MinuteKBarStorage

logger = logging.getLogger("autofetchstock.scheduler.volume_spike")
_TZ_TAIPEI = ZoneInfo("Asia/Taipei")


class VolumeSpikeJob:
    """Glue object handed to Scheduler.add_volume_spike_job."""

    # Suppress alert pushes after a budget-reject burst; one popup per
    # 5-minute window is enough signal without spamming the UI.
    _ALERT_THROTTLE_SECONDS: float = 300.0

    def __init__(
        self,
        fetcher: "ShioajiFetcher",
        storage: "MinuteKBarStorage",
        detector: "VolumeSpikeDetector",
        detection_store: "SpikeDetectionStore",
        tracked_stocks_provider: Callable[[], List[str]],
        ticks_budget: Optional[TicksFallbackBudget] = None,
        limit_alert_pusher: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self.fetcher = fetcher
        self.storage = storage
        self.detector = detector
        self.detection_store = detection_store
        self.tracked_stocks_provider = tracked_stocks_provider
        self._ticks_budget = ticks_budget or TicksFallbackBudget()
        self._limit_alert_pusher = limit_alert_pusher
        # Sweep offset rotates the iteration start across calls so a
        # rate-limited tail of `tracked` doesn't always belong to the same
        # stocks. Wraps around `len(tracked)` inside `run_once`.
        self._sweep_offset = 0
        self._last_budget_alert_ts: float = 0.0

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

        # Rotate iteration order so any rate-limited tail isn't always the
        # same stocks. Q2 concern: pure sequential iteration would let
        # later list entries miss fallback opportunities when budget is
        # tight; rotating distributes that risk evenly across the watchlist.
        self._sweep_offset = (self._sweep_offset + 1) % len(tracked)
        ordered = tracked[self._sweep_offset:] + tracked[: self._sweep_offset]

        now = datetime.now(_TZ_TAIPEI).replace(second=0, microsecond=0)
        target_minute = now - timedelta(minutes=1)
        target_time = target_minute.time()
        target_date = target_minute.date()

        for stock_id in ordered:
            try:
                self._process_stock(stock_id, target_date, target_time)
            except Exception as exc:
                logger.warning(
                    "[spike_job] %s failed at %s: %s\n%s",
                    stock_id, target_minute, exc, traceback.format_exc(),
                )

        # Surface budget-exhaustion to the UI exactly once per throttle
        # window, regardless of how many stocks rejected this sweep.
        rejects = self._ticks_budget.reset_reject_count()
        if rejects > 0:
            self._maybe_push_budget_alert(rejects, len(ordered))

        logger.debug(
            "[spike_job] swept %d stocks for minute %s (offset=%d, rejects=%d)",
            len(ordered), target_minute.strftime("%H:%M"),
            self._sweep_offset, rejects,
        )

    def _maybe_push_budget_alert(self, rejects: int, total: int) -> None:
        """Throttled limit-alert when ticks fallback budget gets exhausted."""
        if not self._limit_alert_pusher:
            return
        now_wall = time.time()
        if now_wall - self._last_budget_alert_ts < self._ALERT_THROTTLE_SECONDS:
            return
        self._last_budget_alert_ts = now_wall
        try:
            self._limit_alert_pusher({
                "level": "warn",
                "title": "成交量偵測：ticks 配額不足",
                "body": (
                    f"本輪掃描 {total} 檔個股時 kbars API 異常，"
                    f"已有 {rejects} 次 ticks fallback 因配額不足被略過。\n"
                    "Shioaji 限制 ticks ≤10 次 / 5 秒，"
                    "略過的個股下一分鐘會自動重試，不影響資料完整性。"
                ),
                "tag": "ticks_budget",
                "ts": now_wall,
            })
        except Exception as exc:
            logger.debug(f"limit-alert pusher failed: {exc}")

    # ── internals ──────────────────────────────────────────────────────────

    def _process_stock(
        self, stock_id: str, target_date: date, target_time
    ) -> None:
        # Gate ticks fallback through the budget so a transient kbars
        # outage can't burst past Shioaji's 10/5s ticks cap. Stocks that
        # lose this race skip the fallback this minute and retry next
        # cycle when kbars usually recovers.
        allow_fallback = self._ticks_budget.try_acquire(stock_id)
        bars = self.fetcher.fetch_minute_kbars(
            stock_id,
            target_date,
            start_time=target_time,
            end_time=target_time,
            allow_ticks_fallback=allow_fallback,
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
