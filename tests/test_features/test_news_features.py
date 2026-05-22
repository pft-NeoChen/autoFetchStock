"""TASK-F07 — News features (V2 §0.3, §0.5)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.features.news_features import (
    NewsRecord,
    aggregate_news_by_day,
    assign_effective_date,
    news_feature_providers,
)
from src.features.store import FeatureStore


def _news(
    stock_id: str,
    published_at: datetime,
    impact: float = 5.0,
    direction: str = "up",
) -> NewsRecord:
    return NewsRecord(
        stock_id=stock_id,
        published_at=published_at,
        impact_score=impact,
        impact_direction=direction,
    )


def _daily_ohlc(n: int = 30) -> pd.DataFrame:
    idx = pd.date_range("2025-01-02", periods=n, freq="B")
    return pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1_000_000] * n,
        },
        index=idx,
    )


# ---- effective date ----

@pytest.mark.unit
def test_effective_date_before_close_is_same_day() -> None:
    published = datetime(2025, 1, 6, 11, 0)  # Monday morning
    assert assign_effective_date(published) == date(2025, 1, 6)


@pytest.mark.unit
def test_effective_date_after_close_rolls_to_next_weekday() -> None:
    published = datetime(2025, 1, 6, 15, 0)  # Monday afternoon
    assert assign_effective_date(published) == date(2025, 1, 7)


@pytest.mark.unit
def test_effective_date_friday_after_close_rolls_to_monday() -> None:
    published = datetime(2025, 1, 10, 15, 0)  # Friday afternoon
    assert assign_effective_date(published) == date(2025, 1, 13)


@pytest.mark.unit
def test_effective_date_weekend_rolls_to_monday() -> None:
    published = datetime(2025, 1, 11, 10, 0)  # Saturday
    assert assign_effective_date(published) == date(2025, 1, 13)


# ---- aggregate ----

@pytest.mark.unit
def test_aggregate_news_counts_and_severity() -> None:
    records = [
        _news("2330", datetime(2025, 1, 6, 10, 0), impact=3.0, direction="up"),
        _news("2330", datetime(2025, 1, 6, 11, 0), impact=8.0, direction="up"),
        _news("2330", datetime(2025, 1, 7, 9, 0), impact=4.0, direction="down"),
    ]
    by_stock = aggregate_news_by_day(records)

    df = by_stock["2330"]
    row = df.loc[pd.Timestamp("2025-01-06")]
    assert row["news_count"] == 2
    assert row["news_severity"] == pytest.approx(8.0)
    assert row["news_direction_score"] == pytest.approx(11.0)  # both up = +3+8


@pytest.mark.unit
def test_aggregate_direction_score_distinguishes_up_down() -> None:
    records = [
        _news("2330", datetime(2025, 1, 6, 10, 0), impact=4.0, direction="up"),
        _news("2330", datetime(2025, 1, 6, 11, 0), impact=2.0, direction="down"),
        _news("2330", datetime(2025, 1, 6, 12, 0), impact=10.0, direction="neutral"),
    ]
    by_stock = aggregate_news_by_day(records)
    row = by_stock["2330"].loc[pd.Timestamp("2025-01-06")]
    assert row["news_direction_score"] == pytest.approx(4.0 - 2.0)


# ---- provider integration ----

@pytest.mark.unit
def test_provider_returns_zero_when_no_news(tmp_path: Path) -> None:
    providers = news_feature_providers(news_records=[])
    store = FeatureStore(
        providers=providers,
        raw_daily={"2330": _daily_ohlc(5)},
        universe_version="u",
        corp_action_version="c",
        git_commit="g",
        cache_dir=tmp_path,
    )

    df = store.build(["2330"], date(2025, 1, 2), date(2025, 1, 10))
    series = df.xs("2330", level="stock_id")
    assert (series["news_count"].fillna(0) == 0).all()
    assert (series["news_severity"].fillna(0) == 0).all()


@pytest.mark.unit
def test_provider_rolls_after_close_news_to_next_day(tmp_path: Path) -> None:
    records = [
        _news("2330", datetime(2025, 1, 6, 15, 0), impact=9.0, direction="up"),
    ]
    providers = news_feature_providers(news_records=records)
    store = FeatureStore(
        providers=providers,
        raw_daily={"2330": _daily_ohlc(10)},
        universe_version="u",
        corp_action_version="c",
        git_commit="g",
        cache_dir=tmp_path,
    )

    df = store.build(["2330"], date(2025, 1, 2), date(2025, 1, 10))
    series = df.xs("2330", level="stock_id")
    # 1/6 15:00 published → effective 1/7
    assert series["news_severity"].loc[pd.Timestamp("2025-01-07")] == pytest.approx(9.0)
    assert series["news_severity"].loc[pd.Timestamp("2025-01-06")] in (0.0,) or pd.isna(
        series["news_severity"].loc[pd.Timestamp("2025-01-06")]
    )


@pytest.mark.unit
def test_news_anomaly_flag_when_above_baseline(tmp_path: Path) -> None:
    base_records = [
        _news("2330", datetime(2025, 1, d, 10, 0), impact=1.0, direction="up")
        for d in (6, 7, 8, 9, 10)
    ]
    # Then a spike day with many news
    spike_day = datetime(2025, 1, 13, 10, 0)
    spike_records = [
        _news("2330", spike_day + timedelta(minutes=i), impact=1.0, direction="up")
        for i in range(10)
    ]
    providers = news_feature_providers(
        news_records=base_records + spike_records,
        anomaly_window=5,
        anomaly_multiplier=2.0,
    )
    store = FeatureStore(
        providers=providers,
        raw_daily={"2330": _daily_ohlc(15)},
        universe_version="u",
        corp_action_version="c",
        git_commit="g",
        cache_dir=tmp_path,
    )

    df = store.build(["2330"], date(2025, 1, 2), date(2025, 1, 17))
    series = df.xs("2330", level="stock_id")
    assert bool(series["news_anomaly"].loc[pd.Timestamp("2025-01-13")]) is True


@pytest.mark.unit
def test_aggregate_handles_multiple_stocks() -> None:
    records = [
        _news("2330", datetime(2025, 1, 6, 10, 0)),
        _news("2317", datetime(2025, 1, 6, 10, 0)),
    ]
    by_stock = aggregate_news_by_day(records)
    assert set(by_stock.keys()) == {"2330", "2317"}
