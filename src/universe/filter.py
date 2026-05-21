"""TASK-U01 — Daily Universe Filter (V2 §0.2).

Pure function: given a target date, candidate stock ids, point-in-time daily
data, and per-stock metadata, returns the tradeable universe for that date.

Rules:
- 20-day mean turnover ≥ 50,000,000
- listing bars at or before target ≥ 60
- latest close at or before target ≥ 5
- exclude F-shares (name contains "F-" or ends with "-KY"), ETN, warrant,
  warning, disposition, full-delivery stocks
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

LIQUIDITY_WINDOW = 20
LIQUIDITY_MIN_TURNOVER = 50_000_000
MIN_LISTING_BARS = 60
MIN_PRICE = 5.0


@dataclass(frozen=True)
class StockMeta:
    stock_id: str
    name: str
    listing_date: date
    is_etn: bool = False
    is_warning: bool = False
    is_disposition: bool = False
    is_full_delivery: bool = False
    is_warrant: bool = False


def _is_foreign_listing(name: str) -> bool:
    """F-股 / -KY 外國發行人 (台股慣例)."""
    return "F-" in name or name.upper().endswith("-KY")


def _meta_excludes(meta: StockMeta) -> bool:
    return (
        meta.is_etn
        or meta.is_warning
        or meta.is_disposition
        or meta.is_full_delivery
        or meta.is_warrant
        or _is_foreign_listing(meta.name)
    )


def _bars_at_or_before(df: pd.DataFrame, target_date: date) -> pd.DataFrame:
    # daily_data may be indexed by datetime.date or pd.Timestamp; normalize either way.
    idx = pd.DatetimeIndex(pd.to_datetime(df.index))
    mask = (idx <= pd.Timestamp(target_date))
    return df.iloc[list(mask)]


def filter_universe(
    target_date: date,
    candidates: list[str],
    daily_data: dict[str, pd.DataFrame],
    stock_meta: dict[str, StockMeta],
) -> list[str]:
    selected: list[str] = []
    for stock_id in candidates:
        meta = stock_meta.get(stock_id)
        if meta is None:
            continue
        if _meta_excludes(meta):
            continue

        df = daily_data.get(stock_id)
        if df is None or df.empty:
            continue

        pit = _bars_at_or_before(df, target_date)
        if len(pit) < MIN_LISTING_BARS:
            continue

        latest_close = float(pit["close"].iloc[-1])
        if latest_close < MIN_PRICE:
            continue

        window = pit["turnover"].iloc[-LIQUIDITY_WINDOW:]
        if window.mean() < LIQUIDITY_MIN_TURNOVER:
            continue

        selected.append(stock_id)
    return selected
