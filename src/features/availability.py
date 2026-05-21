"""TASK-F02 — Feature available_at rules (V2 §0.5).

The rules are intentionally conservative. When a source is normally published
after the close but exact publication time is not stored, the value becomes
available before the next weekday's open.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time, timedelta
from typing import Any

MARKET_CLOSE = time(13, 30)
PRE_OPEN_AVAILABLE = time(8, 30)
DEFAULT_MINUTE_BAR_MINUTES = 1

AvailabilityRule = Callable[..., datetime]


class UnknownFeatureError(ValueError):
    """Raised when no availability rule exists for a feature source."""


def _at_time(ref_timestamp: datetime, wall_time: time) -> datetime:
    return datetime.combine(ref_timestamp.date(), wall_time).replace(
        tzinfo=ref_timestamp.tzinfo
    )


def _next_weekday_pre_open(ref_timestamp: datetime) -> datetime:
    next_day = ref_timestamp.date() + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    return datetime.combine(next_day, PRE_OPEN_AVAILABLE).replace(
        tzinfo=ref_timestamp.tzinfo
    )


def _daily_ohlc_available(ref_timestamp: datetime, **_: Any) -> datetime:
    return _at_time(ref_timestamp, MARKET_CLOSE)


def _minute_kbar_available(
    ref_timestamp: datetime,
    *,
    bar_minutes: int = DEFAULT_MINUTE_BAR_MINUTES,
    **_: Any,
) -> datetime:
    if bar_minutes <= 0:
        raise ValueError("bar_minutes must be positive")
    return ref_timestamp + timedelta(minutes=bar_minutes)


def _next_day_pre_open_available(ref_timestamp: datetime, **_: Any) -> datetime:
    return _next_weekday_pre_open(ref_timestamp)


def _published_timestamp_available(ref_timestamp: datetime, **_: Any) -> datetime:
    return ref_timestamp


def _news_available(
    ref_timestamp: datetime,
    *,
    processed_at: datetime | None = None,
    **_: Any,
) -> datetime:
    if processed_at is None:
        return ref_timestamp
    return max(ref_timestamp, processed_at)


AVAILABILITY_RULES: dict[str, AvailabilityRule] = {
    "daily_ohlc": _daily_ohlc_available,
    "minute_kbar": _minute_kbar_available,
    "chips": _next_day_pre_open_available,
    "chips_institutional": _next_day_pre_open_available,
    "margin": _next_day_pre_open_available,
    "monthly_revenue": _published_timestamp_available,
    "news": _news_available,
    "advisor": _published_timestamp_available,
}


def availability_of(
    feature_name: str,
    ref_timestamp: datetime,
    **kwargs: Any,
) -> datetime:
    """Return the earliest timestamp when a feature value may be used."""
    rule = AVAILABILITY_RULES.get(feature_name)
    if rule is None:
        raise UnknownFeatureError(f"Unknown feature availability rule: {feature_name}")
    return rule(ref_timestamp, **kwargs)
