"""Guards for converting realtime quotes into intraday ticks."""

from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

_TW_TIMEZONE = ZoneInfo("Asia/Taipei")


def timestamp_matches_trade_date(
    timestamp: Optional[datetime],
    trade_date: date,
) -> bool:
    """Return whether a timestamp belongs to the target trading date."""
    if timestamp is None:
        return True

    if timestamp.tzinfo is not None:
        return timestamp.astimezone(_TW_TIMEZONE).date() == trade_date

    return timestamp.date() == trade_date


def quote_timestamp_matches_trade_date(
    quote,
    trade_date: date,
) -> bool:
    """Return whether a quote timestamp belongs to the target trading date."""
    return timestamp_matches_trade_date(getattr(quote, "timestamp", None), trade_date)
