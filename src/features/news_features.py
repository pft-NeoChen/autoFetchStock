"""TASK-F07 — News features (V2 §0.3, §0.5).

Aggregates raw news records into day-level (stock_id × date) features.

Look-ahead rule (V2 §0.5): a news item is assigned to its *effective trading
day* — same day if ``published_at`` ≤ 13:30, otherwise the next weekday. The
provider therefore exposes a value at row T whose ``available_at`` is no
later than T's signal timestamp (13:30).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from src.features.store import FeatureProvider, FeatureValue

__all__ = [
    "NewsRecord",
    "aggregate_news_by_day",
    "assign_effective_date",
    "news_feature_providers",
]


MARKET_CLOSE = time(13, 30)


@dataclass(frozen=True)
class NewsRecord:
    stock_id: str
    published_at: datetime
    impact_score: float = 0.0
    impact_direction: str = "neutral"  # "up" | "down" | "neutral"


def assign_effective_date(published_at: datetime) -> date:
    """Map a publication timestamp to the trading day it affects."""
    ref = published_at.date()
    if published_at.weekday() < 5 and published_at.time() <= MARKET_CLOSE:
        return ref
    nxt = ref + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def aggregate_news_by_day(
    records: Iterable[NewsRecord],
) -> dict[str, pd.DataFrame]:
    """Group records into per-stock DataFrames indexed by effective trading day."""
    buckets: dict[str, dict[date, dict[str, float]]] = defaultdict(lambda: defaultdict(
        lambda: {"news_count": 0.0, "news_severity": 0.0, "news_direction_score": 0.0}
    ))
    for rec in records:
        eff = assign_effective_date(rec.published_at)
        bucket = buckets[rec.stock_id][eff]
        bucket["news_count"] += 1
        if rec.impact_score > bucket["news_severity"]:
            bucket["news_severity"] = float(rec.impact_score)
        if rec.impact_direction == "up":
            bucket["news_direction_score"] += float(rec.impact_score)
        elif rec.impact_direction == "down":
            bucket["news_direction_score"] -= float(rec.impact_score)

    by_stock: dict[str, pd.DataFrame] = {}
    for sid, day_map in buckets.items():
        idx = pd.DatetimeIndex(sorted(pd.Timestamp(d) for d in day_map))
        df = pd.DataFrame(
            [day_map[ts.date()] for ts in idx],
            index=idx,
            columns=["news_count", "news_severity", "news_direction_score"],
        )
        by_stock[sid] = df
    return by_stock


def _attach_anomaly_flag(
    df: pd.DataFrame,
    *,
    window: int,
    multiplier: float,
) -> pd.DataFrame:
    if df.empty:
        df["news_anomaly"] = pd.Series(dtype=bool)
        return df
    baseline = df["news_count"].shift(1).rolling(window=window, min_periods=1).mean()
    df["news_anomaly"] = (df["news_count"] > baseline.fillna(0) * multiplier) & (
        df["news_count"] > 0
    )
    return df


def news_feature_providers(
    *,
    news_records: Iterable[NewsRecord],
    anomaly_window: int = 20,
    anomaly_multiplier: float = 3.0,
) -> list[FeatureProvider]:
    by_stock = aggregate_news_by_day(news_records)
    for sid, df in by_stock.items():
        by_stock[sid] = _attach_anomaly_flag(
            df, window=anomaly_window, multiplier=anomaly_multiplier
        )

    columns = ("news_count", "news_severity", "news_direction_score", "news_anomaly")

    def _make_provider(name: str) -> FeatureProvider:
        def compute(stock_id: str, ref_date: date, ohlc: pd.DataFrame) -> FeatureValue | None:
            available_at = datetime.combine(ref_date, MARKET_CLOSE)
            df = by_stock.get(stock_id)
            if df is None or df.empty:
                default = False if name == "news_anomaly" else 0.0
                return FeatureValue(value=default, available_at=available_at)
            ts = pd.Timestamp(ref_date)
            if ts not in df.index:
                default = False if name == "news_anomaly" else 0.0
                return FeatureValue(value=default, available_at=available_at)
            return FeatureValue(value=df.at[ts, name], available_at=available_at)

        return FeatureProvider(name=name, schema_version="v1", compute=compute)

    return [_make_provider(c) for c in columns]
