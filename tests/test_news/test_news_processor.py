"""
Unit tests for src/news/news_processor.py  (TASK-164)

Coverage targets:
- _load_favorites: returns [] on storage failure (REQ-295)
- _load_favorites: converts dict items to StockInfo
- _build_stats: counts correctly
- run: calls storage.save_news with a NewsRunResult
- run: result contains all 5 NewsCategory keys
- run: save_news called even if one category raises
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.models import StockInfo
from src.news.news_fetcher import RawArticle
from src.news.news_models import NewsCategory, NewsCategoryResult, NewsRunResult
from src.news.news_processor import NewsProcessor
from tests.test_news.conftest import make_article, make_category_result, make_run_result


def _make_processor(mock_config, mock_storage):
    """Create a NewsProcessor with mocked sub-components."""
    with patch("src.news.news_processor.NewsFetcher"), \
         patch("src.news.news_processor.NewsSummarizer"):
        processor = NewsProcessor(config=mock_config, storage=mock_storage)
    # Replace with explicit mocks so tests can control their behaviour
    processor._fetcher = MagicMock()
    processor._summarizer = MagicMock()
    processor._summarizer.set_favorites.return_value = None
    processor._summarizer.summarize_category.return_value = ("分類摘要", True)
    processor._summarizer.summarize_article.return_value = ("文章摘要", [], True)
    return processor


# ── _load_favorites ──────────────────────────────────────────────────────────

class TestLoadFavorites:
    def test_returns_empty_on_storage_error(self, mock_config, mock_storage):
        mock_storage.load_favorites.side_effect = Exception("disk error")
        processor = _make_processor(mock_config, mock_storage)
        result = processor._load_favorites()
        assert result == []

    def test_converts_dict_to_stock_info(self, mock_config, mock_storage):
        mock_storage.load_favorites.return_value = [
            {"id": "2330", "name": "台積電"},
        ]
        processor = _make_processor(mock_config, mock_storage)
        result = processor._load_favorites()
        assert len(result) == 1
        assert result[0].stock_id == "2330"
        assert result[0].stock_name == "台積電"

    def test_digit_id_maps_to_twse(self, mock_config, mock_storage):
        mock_storage.load_favorites.return_value = [{"id": "2330", "name": "台積電"}]
        processor = _make_processor(mock_config, mock_storage)
        result = processor._load_favorites()
        assert result[0].market == "TWSE"

    def test_alpha_id_maps_to_us(self, mock_config, mock_storage):
        mock_storage.load_favorites.return_value = [{"id": "AAPL", "name": "Apple"}]
        processor = _make_processor(mock_config, mock_storage)
        result = processor._load_favorites()
        assert result[0].market == "US"


# ── _build_stats ──────────────────────────────────────────────────────────────

class TestBuildStats:
    def test_counts_articles_and_failures(self, mock_config, mock_storage):
        processor = _make_processor(mock_config, mock_storage)

        art_ok = make_article(summary="ok")
        from dataclasses import replace
        art_failed = replace(art_ok, summary_failed=True, summary="")

        from tests.test_news.conftest import make_category_result
        cat = make_category_result(
            NewsCategory.FINANCIAL,
            articles=[art_ok, art_failed],
        )
        # Override counts
        from dataclasses import replace as dc_replace
        cat = dc_replace(cat, article_count=1, failed_count=1, articles=[art_ok, art_failed])

        stats = processor._build_stats([cat], duration=5.0)
        assert stats.total_articles == 2
        assert stats.failed_summaries >= 1
        assert stats.duration_seconds == pytest.approx(5.0)


class TestFetchStockCategory:
    """Phase 1：_fetch_stock_category 不再做 LLM per-article 摘要，
    summary 欄位 fallback 為 RSS excerpt，related_stock_ids 來自 favorites 比對。"""

    def test_stock_news_keeps_stock_id_from_favorite(self, mock_config, mock_storage):
        processor = _make_processor(mock_config, mock_storage)
        raw = RawArticle(
            title="台積電新聞",
            url="https://example.com/2330",
            source="TestSource",
            published_at=make_article().published_at,
            excerpt="short",
        )
        processor._fetcher.fetch_stock_news.return_value = ([raw], NewsCategory.STOCK_TW)

        result, raws = processor._fetch_stock_category(
            NewsCategory.STOCK_TW,
            [StockInfo(stock_id="2330", stock_name="台積電")],
        )

        assert result.articles[0].related_stock_ids == ["2330"]
        assert result.articles[0].summary_failed is False
        assert result.articles[0].summary == "short"  # RSS excerpt fallback
        assert raws == [raw]

    def test_stock_news_merges_stock_ids_for_duplicate_url(self, mock_config, mock_storage):
        processor = _make_processor(mock_config, mock_storage)
        raw = RawArticle(
            title="供應鏈新聞",
            url="https://example.com/supply-chain",
            source="TestSource",
            published_at=make_article().published_at,
            excerpt="short",
        )
        processor._fetcher.fetch_stock_news.side_effect = [
            ([raw], NewsCategory.STOCK_TW),
            ([raw], NewsCategory.STOCK_TW),
        ]

        result, _ = processor._fetch_stock_category(
            NewsCategory.STOCK_TW,
            [
                StockInfo(stock_id="2330", stock_name="台積電"),
                StockInfo(stock_id="2317", stock_name="鴻海"),
            ],
        )

        assert len(result.articles) == 1
        assert result.articles[0].related_stock_ids == ["2330", "2317"]


# ── run() integration ─────────────────────────────────────────────────────────

class TestRun:
    @pytest.fixture(autouse=True)
    def _setup(self, mock_config, mock_storage):
        self.processor = _make_processor(mock_config, mock_storage)
        self.mock_storage = mock_storage

    def test_run_calls_save_news(self):
        """run() must call storage.save_news with a valid NewsRunResult."""
        self.processor._fetcher.fetch_category.return_value = []
        self.processor._fetcher.fetch_stock_news.return_value = ([], NewsCategory.STOCK_TW)
        self.mock_storage.load_favorites.return_value = [{"id": "2330", "name": "台積電"}]

        result = self.processor.run()

        self.mock_storage.save_news.assert_called_once()
        saved_arg = self.mock_storage.save_news.call_args[0][0]
        assert isinstance(saved_arg, NewsRunResult)

    def test_run_returns_all_5_categories(self):
        """run() result must have entries for all 5 NewsCategory members."""
        self.processor._fetcher.fetch_category.return_value = []
        self.processor._fetcher.fetch_stock_news.return_value = ([], NewsCategory.STOCK_TW)
        self.mock_storage.load_favorites.return_value = [{"id": "2330", "name": "台積電"}]

        result = self.processor.run()

        assert isinstance(result, NewsRunResult)
        assert set(result.categories.keys()) == set(NewsCategory)

    def test_run_saves_even_if_one_category_fails(self):
        """run() should not raise even when a category fetch raises."""
        call_count = 0

        def side_effect(cat):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("network error")
            return make_category_result(cat), []

        self.processor._fetch_category = side_effect
        self.processor._fetcher.fetch_stock_news.return_value = ([], NewsCategory.STOCK_TW)
        self.mock_storage.load_favorites.return_value = []  # skip stock categories

        result = self.processor.run()
        assert isinstance(result, NewsRunResult)
        self.mock_storage.save_news.assert_called_once()

    def test_run_skips_stock_categories_when_no_favorites(self):
        """When favorites list is empty, STOCK_TW and STOCK_US should still appear but be empty."""
        self.processor._fetcher.fetch_category.return_value = []
        self.mock_storage.load_favorites.return_value = []

        result = self.processor.run()

        assert NewsCategory.STOCK_TW in result.categories
        assert NewsCategory.STOCK_US in result.categories
        # Neither should have articles
        assert result.categories[NewsCategory.STOCK_TW].article_count == 0
        assert result.categories[NewsCategory.STOCK_US].article_count == 0
