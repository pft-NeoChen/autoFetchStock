"""
Unit tests for src/news/news_models.py  (TASK-161)

Coverage targets:
- NewsCategory enum values and display_name
- NewsArticle to_dict / from_dict round-trip
- NewsCategoryResult to_dict / from_dict round-trip
- NewsRunResult to_dict / from_dict round-trip
- NewsDailyFile to_dict / from_dict round-trip
"""
import pytest
from datetime import datetime, timezone

from src.news.news_models import (
    NewsArticle,
    NewsCategory,
    NewsCategoryResult,
    NewsDailyFile,
    NewsRunResult,
    NewsRunStats,
)
from tests.test_news.conftest import make_article, make_category_result, make_run_result


# ── NewsCategory ─────────────────────────────────────────────────────────────

class TestNewsCategory:
    def test_all_members_exist(self):
        names = {c.name for c in NewsCategory}
        assert names == {"INTERNATIONAL", "FINANCIAL", "TECH", "STOCK_TW", "STOCK_US"}

    def test_display_name_not_empty(self):
        for cat in NewsCategory:
            assert cat.display_name, f"{cat} has empty display_name"

    def test_display_name_chinese(self):
        # All display names should contain at least one Chinese character
        import unicodedata
        for cat in NewsCategory:
            has_chinese = any(
                unicodedata.category(ch).startswith("Lo")
                for ch in cat.display_name
            )
            assert has_chinese, f"{cat}.display_name has no Chinese chars: {cat.display_name}"


# ── NewsArticle ──────────────────────────────────────────────────────────────

class TestNewsArticle:
    def test_to_dict_has_required_keys(self, sample_article: NewsArticle):
        d = sample_article.to_dict()
        for key in ("title", "source", "url", "published_at", "category",
                    "summary", "related_stock_ids", "full_text_fetched", "summary_failed"):
            assert key in d, f"missing key: {key}"

    def test_to_dict_category_is_string(self, sample_article: NewsArticle):
        d = sample_article.to_dict()
        assert isinstance(d["category"], str)

    def test_round_trip(self, sample_article: NewsArticle):
        restored = NewsArticle.from_dict(sample_article.to_dict())
        assert restored.title == sample_article.title
        assert restored.category == sample_article.category
        assert restored.related_stock_ids == sample_article.related_stock_ids
        assert restored.summary_failed == sample_article.summary_failed

    def test_from_dict_missing_optional_fields(self):
        """from_dict must tolerate missing optional fields."""
        minimal = {
            "title": "Minimal",
            "source": "S",
            "url": "https://example.com",
            "published_at": "2026-04-10T09:00:00+00:00",
            "category": NewsCategory.FINANCIAL.value,  # use actual enum value
        }
        art = NewsArticle.from_dict(minimal)
        assert art.title == "Minimal"
        assert art.summary == "" or art.summary is None
        assert art.related_stock_ids == []


# ── NewsCategoryResult ───────────────────────────────────────────────────────

class TestNewsCategoryResult:
    def test_to_dict_articles_serialised(self, sample_category_result: NewsCategoryResult):
        d = sample_category_result.to_dict()
        assert isinstance(d["articles"], list)
        assert len(d["articles"]) == sample_category_result.article_count

    def test_round_trip(self, sample_category_result: NewsCategoryResult):
        restored = NewsCategoryResult.from_dict(sample_category_result.to_dict())
        assert restored.category == sample_category_result.category
        assert len(restored.articles) == len(sample_category_result.articles)
        assert restored.category_summary == sample_category_result.category_summary


# ── NewsRunResult ────────────────────────────────────────────────────────────

class TestNewsRunResult:
    def test_to_dict_categories_keyed_by_string(self, sample_run_result: NewsRunResult):
        d = sample_run_result.to_dict()
        assert isinstance(d["categories"], dict)
        for key in d["categories"]:
            assert isinstance(key, str), f"category key should be str, got {type(key)}"

    def test_round_trip(self, sample_run_result: NewsRunResult):
        restored = NewsRunResult.from_dict(sample_run_result.to_dict())
        assert restored.run_at == sample_run_result.run_at
        # categories is Dict[NewsCategory, ...] so keys should match
        assert set(restored.categories.keys()) == set(sample_run_result.categories.keys())

    def test_run_stats_preserved(self, sample_run_result: NewsRunResult):
        restored = NewsRunResult.from_dict(sample_run_result.to_dict())
        assert restored.run_stats.total_articles == sample_run_result.run_stats.total_articles
        assert restored.run_stats.duration_seconds == pytest.approx(
            sample_run_result.run_stats.duration_seconds
        )


# ── NewsDailyFile ────────────────────────────────────────────────────────────

class TestNewsDailyFile:
    def test_to_dict_has_date_and_runs(self, sample_run_result: NewsRunResult):
        daily = NewsDailyFile(date="20260410", runs=[sample_run_result])
        d = daily.to_dict()
        assert d["date"] == "20260410"
        assert len(d["runs"]) == 1

    def test_round_trip(self, sample_run_result: NewsRunResult):
        daily = NewsDailyFile(date="20260410", runs=[sample_run_result])
        restored = NewsDailyFile.from_dict(daily.to_dict())
        assert restored.date == "20260410"
        assert len(restored.runs) == 1
        assert restored.runs[0].run_at == sample_run_result.run_at
