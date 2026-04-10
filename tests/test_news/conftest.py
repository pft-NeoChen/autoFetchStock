"""
Shared fixtures for the news submodule tests.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.news.news_models import (
    NewsArticle,
    NewsCategory,
    NewsCategoryResult,
    NewsDailyFile,
    NewsRunResult,
    NewsRunStats,
)


# ── Article factory ──────────────────────────────────────────────────────────

def make_article(
    title: str = "Test article",
    category: NewsCategory = NewsCategory.FINANCIAL,
    summary: str = "要聞摘要",
    related: list[str] | None = None,
    url: str = "https://example.com/news/1",
    published_at: datetime | None = None,
) -> NewsArticle:
    """Return a minimal NewsArticle suitable for testing."""
    return NewsArticle(
        title=title,
        source="TestSource",
        url=url,
        published_at=published_at or datetime(2026, 4, 10, 9, 0, tzinfo=timezone.utc),
        category=category,
        excerpt="short excerpt",
        full_text="full article text" * 10,
        summary=summary,
        related_stock_ids=related or [],
        full_text_fetched=True,
        summary_failed=False,
    )


# ── CategoryResult factory ───────────────────────────────────────────────────

def make_category_result(
    category: NewsCategory = NewsCategory.FINANCIAL,
    articles: list[NewsArticle] | None = None,
) -> NewsCategoryResult:
    arts = articles or [make_article(category=category)]
    return NewsCategoryResult(
        category=category,
        articles=arts,
        category_summary="本分類摘要",
        fetched_at=datetime(2026, 4, 10, 9, 0, tzinfo=timezone.utc),
        article_count=len(arts),
        failed_count=0,
        summary_failed=False,
    )


# ── RunResult factory ────────────────────────────────────────────────────────

def make_run_result(categories: dict | None = None) -> NewsRunResult:
    cats: dict = categories or {
        NewsCategory.FINANCIAL: make_category_result(NewsCategory.FINANCIAL),
        NewsCategory.INTERNATIONAL: make_category_result(NewsCategory.INTERNATIONAL),
    }
    total = sum(c.article_count for c in cats.values())
    stats = NewsRunStats(
        total_articles=total,
        successful_articles=total,
        failed_articles=0,
        total_summaries=total,
        failed_summaries=0,
        duration_seconds=12.3,
    )
    run_at = datetime(2026, 4, 10, 9, 0, tzinfo=timezone.utc)
    return NewsRunResult(
        run_at=run_at,
        finished_at=datetime(2026, 4, 10, 9, 0, 12, tzinfo=timezone.utc),
        categories=cats,
        run_stats=stats,
    )


# ── pytest fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def sample_article():
    return make_article()


@pytest.fixture
def sample_category_result():
    return make_category_result()


@pytest.fixture
def sample_run_result():
    return make_run_result()


@pytest.fixture
def mock_config():
    cfg = MagicMock()
    cfg.gemini_api_key = "FAKE_KEY"
    cfg.news_summarizer_backend = "gemini"
    cfg.news_max_articles_per_category = 20
    cfg.news_request_timeout = 15
    cfg.news_request_interval = 0.0   # no delay in tests
    cfg.news_summarizer_timeout = 10
    cfg.news_max_run_minutes = 5
    return cfg


@pytest.fixture
def mock_storage(tmp_path):
    storage = MagicMock()
    storage.load_favorites.return_value = [
        {"id": "2330", "name": "台積電"},
        {"id": "AAPL", "name": "Apple"},
    ]
    storage.save_news.return_value = None
    storage.load_latest_news.return_value = None
    return storage
