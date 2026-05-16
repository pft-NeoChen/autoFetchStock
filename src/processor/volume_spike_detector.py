"""
Volume spike detector for 1-minute K bars.

Hybrid baseline:
  法 B (preferred): same minute-of-day across past N trading days,
                    trimmed mean (drop highest+lowest if >=5 samples).
  法 A (fallback) : recent N bars on the same day, skipping the first
                    SPIKE_FALLBACK_SKIP_OPENING bars (opening volume
                    is naturally large), marked low_confidence.

Detector is a pure function over a single MinuteKBar — it never writes
to disk. Caller is responsible for persisting the returned bar.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Callable, List, Optional, Tuple

from src.config import (
    SPIKE_BASELINE_DAYS,
    SPIKE_BASELINE_MIN_DAYS,
    SPIKE_FALLBACK_SKIP_OPENING,
    SPIKE_FALLBACK_WINDOW,
    SPIKE_MIN_ABS_VOLUME,
    SPIKE_THRESHOLD_EXTREME,
    SPIKE_THRESHOLD_HIGH,
    SPIKE_THRESHOLD_LOW,
    SPIKE_THRESHOLD_MID,
)
from src.models import MinuteKBar, PriceDirection, SpikeSeverity
from src.storage.minute_kbar_storage import MinuteKBarStorage

logger = logging.getLogger("autofetchstock.processor.volume_spike")


class VolumeSpikeDetector:
    """Compute baseline + severity for a freshly observed 1-min K bar."""

    def __init__(
        self,
        storage: MinuteKBarStorage,
        events_provider: Optional[Callable[[str, "date"], bool]] = None,
    ) -> None:
        """
        Args:
            storage: source of historical 1-min bars for baseline lookup.
            events_provider: optional callback `(stock_id, date) -> is_ex_div_day`.
                When True, the detector skips spike judgement (corporate
                actions distort volume baselines). Pass None to disable.
        """
        self.storage = storage
        self.events_provider = events_provider

    # ── public ─────────────────────────────────────────────────────────────

    def detect(self, bar: MinuteKBar) -> MinuteKBar:
        """
        Return a copy of `bar` with detection fields populated.

        Skip rules (return NORMAL with no baseline):
        - bar.volume == 0
        - ex-dividend day per events_provider
        - baseline cannot be computed (no history at all)
        """
        result = replace(
            bar,
            baseline_volume=None,
            volume_ratio=None,
            is_volume_spike=False,
            spike_severity=SpikeSeverity.NORMAL,
            baseline_low_confidence=False,
            price_direction=self._compute_price_direction(bar),
        )

        if bar.volume <= 0:
            return result

        if self.events_provider is not None:
            try:
                if self.events_provider(bar.stock_id, bar.timestamp.date()):
                    logger.debug(
                        "Skip spike detection on ex-div day: %s %s",
                        bar.stock_id, bar.timestamp.date(),
                    )
                    return result
            except Exception as exc:
                logger.warning("events_provider raised, ignoring: %s", exc)

        baseline, low_conf = self._compute_baseline(bar)
        result.baseline_low_confidence = low_conf

        if baseline is None or baseline <= 0:
            return result

        ratio = bar.volume / baseline
        severity = self._classify_severity(ratio, bar.volume)

        result.baseline_volume = baseline
        result.volume_ratio = ratio
        result.spike_severity = severity
        result.is_volume_spike = severity != SpikeSeverity.NORMAL
        return result

    # ── baseline ───────────────────────────────────────────────────────────

    def _compute_baseline(self, bar: MinuteKBar) -> Tuple[Optional[float], bool]:
        """法 B 優先 → 法 A 退回 → (None, True) 全失敗。"""
        # 法 B: same time-of-day, past N trading days
        historical = self.storage.load_same_time_bars(
            stock_id=bar.stock_id,
            target_time=bar.timestamp.time(),
            days=SPIKE_BASELINE_DAYS,
            end_date=bar.timestamp.date(),
        )
        positive = [b.volume for b in historical if b.volume > 0]
        if len(positive) >= SPIKE_BASELINE_MIN_DAYS:
            return self._trimmed_mean(positive), False

        # 法 A: recent bars same day, skip opening
        recent = self.storage.load_recent_bars(
            stock_id=bar.stock_id,
            target_date=bar.timestamp.date(),
            before_timestamp=bar.timestamp,
            n=SPIKE_FALLBACK_WINDOW + SPIKE_FALLBACK_SKIP_OPENING,
        )
        # `recent` is sorted oldest → newest. Drop the first
        # SPIKE_FALLBACK_SKIP_OPENING entries (those are the day's
        # opening bars that always have abnormally large volume).
        trimmed = recent[SPIKE_FALLBACK_SKIP_OPENING:]
        positive = [b.volume for b in trimmed if b.volume > 0]
        if positive:
            return sum(positive) / len(positive), True

        return None, True

    @staticmethod
    def _trimmed_mean(values: List[int]) -> float:
        if len(values) >= 5:
            ordered = sorted(values)[1:-1]
        else:
            ordered = values
        return sum(ordered) / len(ordered)

    # ── severity ───────────────────────────────────────────────────────────

    @staticmethod
    def _classify_severity(ratio: float, volume: int) -> SpikeSeverity:
        if volume < SPIKE_MIN_ABS_VOLUME:
            return SpikeSeverity.NORMAL
        if ratio >= SPIKE_THRESHOLD_EXTREME:
            return SpikeSeverity.EXTREME
        if ratio >= SPIKE_THRESHOLD_HIGH:
            return SpikeSeverity.HIGH
        if ratio >= SPIKE_THRESHOLD_MID:
            return SpikeSeverity.MID
        if ratio >= SPIKE_THRESHOLD_LOW:
            return SpikeSeverity.LOW
        return SpikeSeverity.NORMAL

    @staticmethod
    def _compute_price_direction(bar: MinuteKBar) -> PriceDirection:
        if bar.close > bar.open:
            return PriceDirection.UP
        if bar.close < bar.open:
            return PriceDirection.DOWN
        return PriceDirection.FLAT
