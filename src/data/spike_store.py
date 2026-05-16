"""
In-memory store of recently detected volume spikes per stock.

Bounded ring buffer (deque maxlen=20) so the right-rail panel can
render the latest spike events without re-querying disk on every
Dash callback. Thread-safe (write-from-scheduler, read-from-Dash).
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Dict, List

from src.models import MinuteKBar


class SpikeDetectionStore:
    """Per-stock bounded ring buffer of detected spike bars."""

    DEFAULT_MAX_SPIKES: int = 20

    def __init__(self, max_spikes: int = DEFAULT_MAX_SPIKES) -> None:
        self._max = max_spikes
        self._buffers: Dict[str, deque[MinuteKBar]] = {}
        self._lock = threading.Lock()

    def add_spike(self, stock_id: str, bar: MinuteKBar) -> None:
        """Append a spike bar; replaces an earlier bar with the same timestamp."""
        with self._lock:
            buf = self._buffers.get(stock_id)
            if buf is None:
                buf = deque(maxlen=self._max)
                self._buffers[stock_id] = buf
            else:
                # Drop any prior entry with the same minute so re-runs of the
                # detection job don't create duplicate ring slots.
                existing = [b for b in buf if b.timestamp != bar.timestamp]
                buf.clear()
                buf.extend(existing)
            buf.append(bar)

    def get_recent(self, stock_id: str, n: int = DEFAULT_MAX_SPIKES) -> List[MinuteKBar]:
        """Return the latest spike bars for `stock_id`, newest first."""
        with self._lock:
            buf = self._buffers.get(stock_id)
            if not buf:
                return []
            ordered = sorted(buf, key=lambda b: b.timestamp, reverse=True)
            return ordered[:n]

    def clear(self, stock_id: str) -> None:
        with self._lock:
            self._buffers.pop(stock_id, None)
