"""
Scheduler for autoFetchStock.

This module handles automatic data fetching scheduling:
- APScheduler integration
- Market hours detection (Taiwan Stock Exchange: 09:00-13:30)
- Dynamic job management per stock
- Error handling and pause/resume mechanisms
"""

import logging
import traceback
from datetime import datetime, time
from typing import Callable, Dict, Optional, Set
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

from src.models import SchedulerStatus
from src.exceptions import ServiceUnavailableError, SchedulerTaskError

logger = logging.getLogger("autofetchstock.scheduler")

# Taiwan timezone
TW_TIMEZONE = ZoneInfo("Asia/Taipei")


class Scheduler:
    """
    Background scheduler for automatic stock data fetching.

    Implements REQ-060 through REQ-064 and error handling
    requirements REQ-104 and REQ-106.
    """

    # Market hours (Taiwan Stock Exchange)
    MARKET_OPEN: time = time(9, 0)
    MARKET_CLOSE: time = time(13, 30)

    # Default fetch interval (seconds)
    DEFAULT_INTERVAL: int = 5  # Will be adjusted based on TWSE limits

    def __init__(
        self,
        fetch_callback: Callable[[str], None] = None,
        fetch_interval: int = None
    ):
        """
        Initialize scheduler.

        Args:
            fetch_callback: Callback function to fetch data for a stock ID
            fetch_interval: Fetch interval in seconds
        """
        self._scheduler = BackgroundScheduler(
            timezone=TW_TIMEZONE,
            job_defaults={
                "coalesce": True,  # Combine missed runs
                "max_instances": 1,  # Only one instance per job
                "misfire_grace_time": 60,  # Allow 60s late execution
            }
        )

        self._fetch_callback = fetch_callback
        self._fetch_interval = fetch_interval or self.DEFAULT_INTERVAL
        self._active_stocks: Set[str] = set()
        self._paused: bool = False
        self._consecutive_errors: Dict[str, int] = {}

        # Register job event listeners
        self._scheduler.add_listener(
            self._on_job_executed,
            EVENT_JOB_EXECUTED
        )
        self._scheduler.add_listener(
            self._on_job_error,
            EVENT_JOB_ERROR
        )

        logger.info(f"Scheduler initialized with {self._fetch_interval}s interval")

    def start(self) -> None:
        """
        Start the scheduler (REQ-061).

        Will only process jobs during market hours.
        """
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("Scheduler started")

    def stop(self) -> None:
        """
        Stop the scheduler (REQ-062).

        Gracefully shuts down all jobs.
        """
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)
            logger.info("Scheduler stopped")

    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._scheduler.running

    def is_market_open(self) -> bool:
        """
        Check if Taiwan stock market is currently open.

        Market hours: 09:00 - 13:30 (Asia/Taipei), Mon-Fri

        Returns:
            True if market is open
        """
        now = datetime.now(TW_TIMEZONE)

        # Check weekday (0=Monday, 6=Sunday)
        if now.weekday() >= 5:  # Saturday or Sunday
            return False

        current_time = now.time()
        return self.MARKET_OPEN <= current_time <= self.MARKET_CLOSE

    def add_stock_job(self, stock_id: str) -> bool:
        """
        Add a stock to the fetch schedule.

        Args:
            stock_id: Stock ID to track

        Returns:
            True if job was added (or already exists)
        """
        if stock_id in self._active_stocks:
            logger.debug(f"Stock {stock_id} already in schedule")
            return True

        job_id = self._get_job_id(stock_id)

        try:
            self._scheduler.add_job(
                self._fetch_job,
                trigger=IntervalTrigger(seconds=self._fetch_interval),
                id=job_id,
                args=[stock_id],
                name=f"Fetch {stock_id}",
                replace_existing=True,
            )
            self._active_stocks.add(stock_id)
            self._consecutive_errors[stock_id] = 0
            logger.info(f"Added fetch job for {stock_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to add job for {stock_id}: {e}")
            return False

    def remove_stock_job(self, stock_id: str) -> bool:
        """
        Remove a stock from the fetch schedule.

        Args:
            stock_id: Stock ID to remove

        Returns:
            True if job was removed (or didn't exist)
        """
        job_id = self._get_job_id(stock_id)

        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass  # Job might not exist

        self._active_stocks.discard(stock_id)
        self._consecutive_errors.pop(stock_id, None)
        logger.info(f"Removed fetch job for {stock_id}")
        return True

    def pause_auto_fetch(self) -> None:
        """
        Pause all automatic fetching.

        Used when ServiceUnavailableError is received (REQ-104).
        """
        self._paused = True
        self._scheduler.pause()
        logger.warning("Auto-fetch paused")

    def resume_auto_fetch(self) -> None:
        """
        Resume automatic fetching after pause.
        """
        self._paused = False
        self._scheduler.resume()
        logger.info("Auto-fetch resumed")

    def is_paused(self) -> bool:
        """Check if auto-fetch is paused."""
        return self._paused

    def get_status(self) -> SchedulerStatus:
        """
        Get current scheduler status.

        Returns:
            SchedulerStatus with current state information
        """
        # Calculate total consecutive failures across all stocks
        total_failures = sum(self._consecutive_errors.values())

        return SchedulerStatus(
            is_running=self._scheduler.running,
            is_market_open=self.is_market_open(),
            is_paused=self._paused,
            active_jobs=list(self._active_stocks),
            last_fetch_time=None,  # Would need to track this separately
            consecutive_failures=total_failures,
        )

    def set_fetch_callback(self, callback: Callable[[str], None]) -> None:
        """
        Set the fetch callback function.

        Args:
            callback: Function that takes stock_id and fetches data
        """
        self._fetch_callback = callback

    def add_news_job(self, news_callback: Callable[[], None]) -> bool:
        """
        Add the hourly news collection job.

        Runs every hour from 08:00 to 15:00 Asia/Taipei, Mon-Fri.
        Uses CronTrigger so it fires at the top of each hour within
        the configured window (hour="8-15").

        Args:
            news_callback: Zero-argument callable that runs the full news
                           collection and summarization pipeline.

        Returns:
            True if the job was registered successfully.
        """
        try:
            self._scheduler.add_job(
                self._news_job,
                trigger=CronTrigger(
                    day_of_week="mon-fri",
                    hour="8-15",
                    minute=0,
                    timezone=TW_TIMEZONE,
                ),
                id="news_collect",
                kwargs={"news_callback": news_callback},
                name="News collection",
                replace_existing=True,
            )
            logger.info("Registered hourly news job (08:00-15:00 Mon-Fri)")
            return True
        except Exception as e:
            logger.error(f"Failed to register news job: {e}")
            return False

    def _news_job(self, news_callback: Callable[[], None]) -> None:
        """
        Execute the news collection job.

        Wraps the callback so exceptions are logged but do not crash
        the scheduler (REQ-106).

        Args:
            news_callback: The NewsProcessor.run() bound method.
        """
        logger.info("Starting scheduled news collection")
        try:
            news_callback()
            logger.info("Scheduled news collection completed")
        except Exception as e:
            logger.error(
                f"News collection job failed: {e}\n{traceback.format_exc()}"
            )

    def add_news_cleanup_job(self, cleanup_callback: Callable[[], int]) -> bool:
        """
        Add the daily news history cleanup job.

        Runs at 23:55 Asia/Taipei every day. The callback should return the
        number of deleted daily news files.
        """
        try:
            self._scheduler.add_job(
                self._news_cleanup_job,
                trigger=CronTrigger(
                    hour=23,
                    minute=55,
                    timezone=TW_TIMEZONE,
                ),
                id="news_cleanup",
                kwargs={"cleanup_callback": cleanup_callback},
                name="News history cleanup",
                replace_existing=True,
            )
            logger.info("Registered daily news cleanup job (23:55)")
            return True
        except Exception as e:
            logger.error(f"Failed to register news cleanup job: {e}")
            return False

    def _news_cleanup_job(self, cleanup_callback: Callable[[], int]) -> None:
        """Execute the news cleanup job without crashing the scheduler."""
        logger.info("Starting scheduled news cleanup")
        try:
            deleted_count = cleanup_callback()
            logger.info("Scheduled news cleanup completed: %d files deleted", deleted_count)
        except Exception as e:
            logger.error(
                f"News cleanup job failed: {e}\n{traceback.format_exc()}"
            )

    def add_news_event_job(self, event_callback: Callable[[], object]) -> bool:
        """
        Add the daily news event timeline build job.

        Runs at 16:05 Asia/Taipei, after the regular 08:00-15:00 hourly news
        collection window.
        """
        try:
            self._scheduler.add_job(
                self._news_event_job,
                trigger=CronTrigger(
                    hour=16,
                    minute=5,
                    timezone=TW_TIMEZONE,
                ),
                id="news_events",
                kwargs={"event_callback": event_callback},
                name="News event timeline",
                replace_existing=True,
            )
            logger.info("Registered daily news event job (16:05)")
            return True
        except Exception as e:
            logger.error(f"Failed to register news event job: {e}")
            return False

    def _news_event_job(self, event_callback: Callable[[], object]) -> None:
        """Execute the news event job without crashing the scheduler."""
        logger.info("Starting scheduled news event timeline build")
        try:
            event_callback()
            logger.info("Scheduled news event timeline build completed")
        except Exception as e:
            logger.error(
                f"News event timeline job failed: {e}\n{traceback.format_exc()}"
            )

    def add_news_rag_index_job(self, index_callback: Callable[[], object]) -> bool:
        """
        Add the daily news RAG index update jobs.

        Runs twice per day (16:20 and 16:21 Asia/Taipei) to fit the
        Gemini free-tier 100 contents/min embedding quota: each pass
        embeds up to 100 new articles, separated by a one-minute gap so
        the second pass starts in a fresh quota window.
        """
        success = True
        for slot, minute in enumerate((20, 21), start=1):
            try:
                self._scheduler.add_job(
                    self._news_rag_index_job,
                    trigger=CronTrigger(
                        hour=16,
                        minute=minute,
                        timezone=TW_TIMEZONE,
                    ),
                    id=f"news_rag_index_{slot}",
                    kwargs={"index_callback": index_callback},
                    name=f"News RAG index update #{slot}",
                    replace_existing=True,
                )
                logger.info("Registered daily news RAG index job #%d (16:%02d)", slot, minute)
            except Exception as e:
                logger.error(f"Failed to register news RAG index job #{slot}: {e}")
                success = False
        return success

    def _news_rag_index_job(self, index_callback: Callable[[], object]) -> None:
        """Execute the news RAG index job without crashing the scheduler."""
        logger.info("Starting scheduled news RAG index update")
        try:
            added_count = index_callback()
            logger.info("Scheduled news RAG index update completed: %s new rows", added_count)
        except Exception as e:
            logger.error(
                f"News RAG index job failed: {e}\n{traceback.format_exc()}"
            )

    def _fetch_job(self, stock_id: str) -> None:
        """
        Execute fetch job for a stock (REQ-063).

        This is called by APScheduler at scheduled intervals.

        Args:
            stock_id: Stock ID to fetch

        Raises:
            SchedulerTaskError: If fetch fails (REQ-106)
        """
        # Debug trace
        # logger.debug(f"APScheduler triggering job for {stock_id}")

        # Skip if paused or outside market hours
        if self._paused:
            logger.debug(f"Skipping fetch for {stock_id} - scheduler paused")
            return

        # Bypass market hours check for development/testing
        # if not self.is_market_open():
        #     # Log this only once per minute to avoid spamming if interval is short
        #     # logger.debug(f"Skipping fetch for {stock_id} - market closed")
        #     return
        if not self.is_market_open():
             logger.debug(f"Market closed, but forcing fetch for {stock_id} (DEV MODE)")

        if not self._fetch_callback:
            logger.warning(f"No fetch callback set, skipping {stock_id}")
            return

        try:
            # Execute fetch callback
            self._fetch_callback(stock_id)

            # Reset error counter on success
            self._consecutive_errors[stock_id] = 0
            logger.debug(f"Fetch completed for {stock_id}")

        except ServiceUnavailableError as e:
            # Service is unavailable, pause all fetching (REQ-104)
            logger.error(f"Service unavailable: {e}")
            self.pause_auto_fetch()
            raise SchedulerTaskError(
                task_name=f"fetch_{stock_id}",
                reason=str(e)
            )

        except Exception as e:
            # Increment error counter
            self._consecutive_errors[stock_id] = self._consecutive_errors.get(stock_id, 0) + 1
            error_count = self._consecutive_errors[stock_id]

            # Log the error with full traceback (REQ-106)
            logger.error(
                f"Fetch failed for {stock_id} ({error_count} consecutive errors):\n"
                f"{traceback.format_exc()}"
            )

            # Don't raise - let scheduler continue (REQ-106)
            # The job will retry at next interval

    def _get_job_id(self, stock_id: str) -> str:
        """Generate job ID for a stock."""
        return f"fetch_{stock_id}"

    def _get_next_run_time(self) -> Optional[datetime]:
        """Get the next scheduled run time."""
        jobs = self._scheduler.get_jobs()
        if not jobs:
            return None

        next_times = [
            job.next_run_time for job in jobs
            if job.next_run_time is not None
        ]

        return min(next_times) if next_times else None

    def _on_job_executed(self, event) -> None:
        """Callback when a job completes successfully."""
        logger.debug(f"Job {event.job_id} executed successfully")

    def _on_job_error(self, event) -> None:
        """
        Callback when a job raises an exception.

        Note: This is called in addition to the exception handling
        in _fetch_job. The exception doesn't propagate to crash
        the scheduler (REQ-106).
        """
        logger.error(
            f"Job {event.job_id} raised an exception: {event.exception}"
        )

    def __enter__(self):
        """Context manager entry - start scheduler."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - stop scheduler."""
        self.stop()
        return False
