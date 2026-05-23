"""TASK-M01 — Data Freshness Guard (V2 §9.1).

Monitors per-source tick freshness for upstream data feeds (TWSE, Shioaji).
Detects three failure modes that should halt live signal generation:

* **STALE** — latest tick older than ``max_staleness_sec``.
* **STREAM_STOP** — latest tick older than ``stream_timeout_sec``
  (a stricter superset of STALE, meaning the stream is presumed dead).
* **GAP** — two consecutive ticks in recent history spaced wider than
  ``max_gap_sec`` (the feed is up but skipped).

Plus the trivial **NO_DATA** state for sources that never produced a tick.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Deque, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "DataFreshnessGuard",
    "DataSource",
    "FreshnessConfig",
    "FreshnessStatus",
    "HaltReason",
    "check_staleness",
    "detect_gaps",
]


class DataSource(str, Enum):
    TWSE = "twse"
    SHIOAJI = "shioaji"


class HaltReason(str, Enum):
    NO_DATA = "no_data"
    STALE = "stale"
    GAP = "gap"
    STREAM_STOP = "stream_stop"


@dataclass(frozen=True)
class FreshnessConfig:
    max_staleness_sec: float = 30.0
    max_gap_sec: float = 15.0
    stream_timeout_sec: float = 60.0
    gap_history_window: int = 50


@dataclass(frozen=True)
class FreshnessStatus:
    source: DataSource
    is_fresh: bool
    age_sec: Optional[float]
    last_ts: Optional[datetime]
    reasons: Tuple[str, ...] = field(default_factory=tuple)


def check_staleness(
    last_ts: Optional[datetime], now: datetime, max_sec: float
) -> Tuple[bool, Optional[float]]:
    """Return ``(is_fresh, age_sec)``.

    ``last_ts=None`` → ``(False, None)``. Negative ages (clock skew /
    out-of-order ``now``) clamp to 0.0 so they still count as fresh.
    """
    if last_ts is None:
        return False, None
    age = (now - last_ts).total_seconds()
    if age < 0:
        age = 0.0
    return age <= max_sec, age


def detect_gaps(
    ts_series: Sequence[datetime], max_gap_sec: float
) -> List[Tuple[datetime, datetime, float]]:
    """Return ``(before, after, gap_sec)`` triples where consecutive ticks
    exceed ``max_gap_sec``. Series with < 2 entries → ``[]``."""
    if len(ts_series) < 2:
        return []
    gaps: List[Tuple[datetime, datetime, float]] = []
    for prev, curr in zip(ts_series, ts_series[1:]):
        span = (curr - prev).total_seconds()
        if span > max_gap_sec:
            gaps.append((prev, curr, span))
    return gaps


class DataFreshnessGuard:
    def __init__(self, config: Optional[FreshnessConfig] = None) -> None:
        self.config = config or FreshnessConfig()
        self._history: Dict[DataSource, Deque[datetime]] = {}
        self._latest: Dict[DataSource, datetime] = {}

    def record_tick(self, source: DataSource, ts: datetime) -> None:
        hist = self._history.setdefault(
            source, deque(maxlen=max(2, self.config.gap_history_window))
        )
        hist.append(ts)
        prev = self._latest.get(source)
        if prev is None or ts > prev:
            self._latest[source] = ts

    def check(self, source: DataSource, now: datetime) -> FreshnessStatus:
        last = self._latest.get(source)
        if last is None:
            return FreshnessStatus(
                source=source,
                is_fresh=False,
                age_sec=None,
                last_ts=None,
                reasons=(HaltReason.NO_DATA.value,),
            )

        cfg = self.config
        reasons: List[str] = []
        fresh, age = check_staleness(last, now, cfg.max_staleness_sec)
        if not fresh:
            reasons.append(HaltReason.STALE.value)

        assert age is not None  # last is set, so age is defined.
        if age > cfg.stream_timeout_sec:
            reasons.append(HaltReason.STREAM_STOP.value)

        history = list(self._history.get(source, ()))
        if detect_gaps(history, cfg.max_gap_sec):
            reasons.append(HaltReason.GAP.value)

        return FreshnessStatus(
            source=source,
            is_fresh=not reasons,
            age_sec=age,
            last_ts=last,
            reasons=tuple(reasons),
        )

    def should_halt(
        self, now: datetime
    ) -> Tuple[bool, Dict[DataSource, FreshnessStatus]]:
        statuses: Dict[DataSource, FreshnessStatus] = {
            source: self.check(source, now) for source in self._latest
        }
        halt = any(not s.is_fresh for s in statuses.values()) or not statuses
        return halt, statuses
