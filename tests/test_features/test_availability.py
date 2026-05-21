"""TASK-F02 RED tests: feature available_at rules (V2 §0.5)."""

from __future__ import annotations

from datetime import datetime

import pytest

from src.features.availability import (
    AVAILABILITY_RULES,
    UnknownFeatureError,
    availability_of,
)


pytestmark = pytest.mark.unit


def test_daily_ohlc_available_after_market_close() -> None:
    assert availability_of("daily_ohlc", datetime(2026, 5, 21, 0, 0)) == datetime(
        2026, 5, 21, 13, 30
    )


def test_minute_kbar_available_only_after_bar_completes() -> None:
    assert availability_of(
        "minute_kbar",
        datetime(2026, 5, 21, 9, 0),
        bar_minutes=5,
    ) == datetime(2026, 5, 21, 9, 5)


def test_chips_institutional_defaults_to_next_trading_day_pre_open() -> None:
    assert availability_of(
        "chips_institutional", datetime(2026, 5, 21, 14, 0)
    ) == datetime(2026, 5, 22, 8, 30)


def test_margin_defaults_to_next_trading_day_pre_open() -> None:
    assert availability_of("margin", datetime(2026, 5, 21, 14, 0)) == datetime(
        2026, 5, 22, 8, 30
    )


def test_next_trading_day_skips_weekend() -> None:
    assert availability_of("margin", datetime(2026, 5, 22, 14, 0)) == datetime(
        2026, 5, 25, 8, 30
    )


def test_monthly_revenue_uses_official_announcement_timestamp() -> None:
    official = datetime(2026, 5, 10, 17, 45)
    assert availability_of("monthly_revenue", official) == official


def test_news_uses_processed_at_when_system_processing_lags() -> None:
    published_at = datetime(2026, 5, 21, 10, 0)
    processed_at = datetime(2026, 5, 21, 10, 7)

    assert availability_of("news", published_at, processed_at=processed_at) == processed_at


def test_news_without_processing_lag_uses_published_at() -> None:
    published_at = datetime(2026, 5, 21, 10, 0)

    assert availability_of("news", published_at) == published_at


def test_advisor_uses_generated_at_timestamp() -> None:
    generated_at = datetime(2026, 5, 21, 12, 5)
    assert availability_of("advisor", generated_at) == generated_at


def test_unknown_feature_raises() -> None:
    with pytest.raises(UnknownFeatureError, match="unknown_feature"):
        availability_of("unknown_feature", datetime(2026, 5, 21, 10, 0))


def test_rules_registry_covers_required_feature_sources() -> None:
    assert {
        "daily_ohlc",
        "minute_kbar",
        "chips_institutional",
        "margin",
        "monthly_revenue",
        "news",
        "advisor",
    } <= set(AVAILABILITY_RULES)
