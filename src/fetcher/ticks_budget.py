"""
Non-blocking token bucket for Shioaji `api.ticks()` fallback calls.

Shioaji caps intraday `ticks` queries at ≤10 per 5-second window
(https://sinotrade.github.io/zh/tutor/limit/). The volume-spike sweep
walks every favorite once a minute and falls back to ticks if `kbars`
fails — without rate limiting, a transient kbars outage with >10
favorites would burst past the cap and trigger 1-minute service
suspension.

This module enforces both a global 5s budget and a per-stock cooldown
so the budget is shared fairly across favorites. Callers that fail to
acquire a token MUST skip the fallback (not sleep) — the spike-job
sweep is sequential and blocking would starve stocks later in the list.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional


class TicksFallbackBudget:
    """Non-blocking token bucket. ``try_acquire`` never sleeps."""

    # Leave 2 calls of headroom under Shioaji's 10/5s ceiling.
    MAX_PER_5S: int = 8
    WINDOW_SECONDS: float = 5.0
    DEFAULT_PER_STOCK_GAP_S: float = 30.0

    def __init__(self) -> None:
        self._window: deque = deque()  # monotonic timestamps of recent acquires
        self._last_acquire_ts: dict = {}  # stock_id → monotonic ts
        self._lock = threading.Lock()
        self._reject_count = 0

    def try_acquire(
        self,
        stock_id: str,
        min_gap_s: Optional[float] = None,
    ) -> bool:
        """Acquire a token if available. Returns False without blocking."""
        gap = self.DEFAULT_PER_STOCK_GAP_S if min_gap_s is None else min_gap_s
        now = time.monotonic()
        with self._lock:
            # Drop window entries older than the limit window.
            cutoff = now - self.WINDOW_SECONDS
            while self._window and self._window[0] < cutoff:
                self._window.popleft()
            if len(self._window) >= self.MAX_PER_5S:
                self._reject_count += 1
                return False
            # Per-stock cooldown only applies once the stock has been
            # acquired at least once. `time.monotonic()` starts at 0 per
            # process on some platforms (macOS), so a default of 0.0 would
            # wrongly trip the cooldown for first-time callers.
            last = self._last_acquire_ts.get(stock_id)
            if last is not None and now - last < gap:
                self._reject_count += 1
                return False
            self._window.append(now)
            self._last_acquire_ts[stock_id] = now
            return True

    def reject_count(self) -> int:
        """Total rejects since process start (read-only)."""
        with self._lock:
            return self._reject_count

    def reset_reject_count(self) -> int:
        """Read-and-clear; used by callers that throttle alert pushes."""
        with self._lock:
            n = self._reject_count
            self._reject_count = 0
            return n
