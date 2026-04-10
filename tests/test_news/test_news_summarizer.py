"""
Unit tests for src/news/news_summarizer.py  (TASK-163)

Coverage targets:
- _parse_article_response: JSON extraction from raw text
- _parse_article_response: markdown fence stripping
- _parse_article_response: plain-text fallback (no JSON)
- summarize_article: success path via mocked _call_backend
- summarize_article: returns ("", [], False) on API failure
- set_favorites: updates internal favorites list
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.news.news_summarizer import NewsSummarizer
from tests.test_news.conftest import make_article


def _make_summarizer(mock_config):
    """
    Create NewsSummarizer with _init_sdk patched out (avoids real API init).
    """
    with patch.object(NewsSummarizer, "_init_sdk", return_value=None):
        summarizer = NewsSummarizer(config=mock_config)
    # Provide a dummy client so _call_sdk has something to call
    summarizer._client = MagicMock()
    summarizer._model_name = "gemini-2.0-flash"
    return summarizer


# ── _parse_article_response ──────────────────────────────────────────────────

class TestParseArticleResponse:
    @pytest.fixture(autouse=True)
    def _setup(self, mock_config):
        self.summarizer = _make_summarizer(mock_config)

    def test_parses_clean_json(self):
        from src.models import StockInfo
        # Set favorites so the filter passes "2330" and "2454"
        self.summarizer.set_favorites([
            StockInfo(stock_id="2330", stock_name="台積電", market="TWSE"),
            StockInfo(stock_id="2454", stock_name="聯發科", market="TWSE"),
        ])
        raw = '{"summary": "市場今日上漲。", "related_stock_ids": ["2330", "2454"]}'
        summary, ids, ok = self.summarizer._parse_article_response(raw)
        assert summary == "市場今日上漲。"
        assert "2330" in ids
        assert ok is True

    def test_strips_markdown_fence(self):
        raw = '```json\n{"summary": "科技股回調。", "related_stock_ids": []}\n```'
        summary, ids, ok = self.summarizer._parse_article_response(raw)
        assert summary == "科技股回調。"
        assert ids == []
        assert ok is True

    def test_plain_text_fallback(self):
        """When response contains no JSON, treat whole text as summary."""
        raw = "這是一段純文字的新聞摘要，沒有 JSON 格式。"
        summary, ids, ok = self.summarizer._parse_article_response(raw)
        assert "純文字" in summary
        assert ids == []
        assert ok is True

    def test_partial_json_fallback(self):
        """Broken JSON falls back to plain-text summary without raising."""
        raw = '{"summary": "incomplete JSON...'
        summary, ids, ok = self.summarizer._parse_article_response(raw)
        assert isinstance(summary, str)
        assert isinstance(ids, list)
        assert ok is True  # fallback still "succeeds"


# ── set_favorites ────────────────────────────────────────────────────────────

class TestSetFavorites:
    @pytest.fixture(autouse=True)
    def _setup(self, mock_config):
        self.summarizer = _make_summarizer(mock_config)

    def test_set_favorites_stores_list(self):
        from src.models import StockInfo
        fav = StockInfo(stock_id="2330", stock_name="台積電", market="TWSE")
        self.summarizer.set_favorites([fav])
        assert any(s.stock_id == "2330" for s in self.summarizer._favorites)

    def test_set_favorites_empty_list(self):
        self.summarizer.set_favorites([])
        assert self.summarizer._favorites == []

    def test_set_favorites_replaces_previous(self):
        from src.models import StockInfo
        fav1 = StockInfo(stock_id="2330", stock_name="台積電", market="TWSE")
        fav2 = StockInfo(stock_id="AAPL", stock_name="Apple", market="US")
        self.summarizer.set_favorites([fav1])
        self.summarizer.set_favorites([fav2])
        ids = [s.stock_id for s in self.summarizer._favorites]
        assert ids == ["AAPL"]


# ── summarize_article (mocked _call_backend) ─────────────────────────────────

class TestSummarizeArticle:
    @pytest.fixture(autouse=True)
    def _setup(self, mock_config):
        self.summarizer = _make_summarizer(mock_config)

    def test_success_returns_summary_and_ids(self):
        from src.models import StockInfo
        # Favorites must include "2330" or it gets filtered out
        self.summarizer.set_favorites([
            StockInfo(stock_id="2330", stock_name="台積電", market="TWSE")
        ])
        self.summarizer._call_backend = MagicMock(
            return_value='{"summary": "台積電創歷史新高。", "related_stock_ids": ["2330"]}'
        )
        art = make_article(title="TSMC hits ATH")
        summary, ids, ok = self.summarizer.summarize_article(art)

        assert "台積電" in summary
        assert "2330" in ids
        assert ok is True

    def test_api_error_returns_failure_flag(self):
        self.summarizer._call_backend = MagicMock(
            side_effect=Exception("API quota exceeded")
        )
        art = make_article(title="Some news")
        summary, ids, ok = self.summarizer.summarize_article(art)

        assert ok is False
        assert isinstance(summary, str)
        assert isinstance(ids, list)

    def test_empty_article_content_returns_failure(self):
        """Articles with no title and no content should return failure immediately."""
        from src.news.news_fetcher import RawArticle
        from datetime import datetime, timezone
        empty_art = RawArticle(
            title="",
            url="https://example.com",
            source="S",
            published_at=datetime.now(timezone.utc),
            excerpt="",
            full_text="",
            full_text_fetched=False,
        )
        summary, ids, ok = self.summarizer.summarize_article(empty_art)
        assert ok is False


# ── summarize_category ────────────────────────────────────────────────────────

class TestSummarizeCategory:
    @pytest.fixture(autouse=True)
    def _setup(self, mock_config):
        self.summarizer = _make_summarizer(mock_config)

    def test_returns_empty_for_no_valid_articles(self):
        from src.news.news_models import NewsCategory
        text, ok = self.summarizer.summarize_category([], NewsCategory.FINANCIAL)
        assert text == ""
        assert ok is False

    def test_success_path(self):
        from src.news.news_models import NewsCategory
        self.summarizer._call_backend = MagicMock(return_value="整體財經市場今日表現穩定。")
        arts = [make_article(summary="文章摘要 A"), make_article(summary="文章摘要 B")]
        text, ok = self.summarizer.summarize_category(arts, NewsCategory.FINANCIAL)
        assert ok is True
        assert len(text) > 0
