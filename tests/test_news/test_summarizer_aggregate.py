"""
Unit tests for Phase 1 aggregate analysis methods on NewsSummarizer.
"""

from datetime import datetime
from unittest.mock import patch

import pytest

from src.config import AppConfig
from src.models import StockInfo
from src.news.news_fetcher import RawArticle
from src.news.news_models import FavoriteSignal, GlobalBrief, NewsCategory
from src.news.news_summarizer import NewsSummarizer


@pytest.fixture
def summarizer():
    cfg = AppConfig()
    cfg.news_summarizer_backend = "gemini"
    # Skip real SDK init; inject a fake backend call.
    with patch.object(NewsSummarizer, "_init_sdk", lambda self: None):
        s = NewsSummarizer(cfg)
    s._model_name = "test"
    return s


def _raw(title: str, excerpt: str = "x", url: str = "http://x") -> RawArticle:
    return RawArticle(
        title=title,
        url=url,
        source="Src",
        published_at=datetime.now(),
        excerpt=excerpt,
    )


# ── summarize_global ─────────────────────────────────────────────────────────

def test_summarize_global_parses_valid_response(summarizer):
    summarizer._call_backend = lambda prompt: """{
        "overall_summary": "今日要點",
        "category_highlights": [
            {"category": "INTERNATIONAL", "headline_points": ["a", "b"]},
            {"category": "FINANCIAL", "headline_points": ["c"]}
        ],
        "market_sentiment": 72,
        "sentiment_reason": "強勁資金流入"
    }"""

    brief = summarizer.summarize_global({
        NewsCategory.INTERNATIONAL: [_raw("t1")],
        NewsCategory.FINANCIAL: [_raw("t2")],
    })

    assert isinstance(brief, GlobalBrief)
    assert brief.failed is False
    assert brief.overall_summary == "今日要點"
    assert brief.market_sentiment == 72
    assert len(brief.category_highlights) == 2
    assert brief.category_highlights[0].headline_points == ["a", "b"]


def test_summarize_global_empty_articles_returns_failed(summarizer):
    brief = summarizer.summarize_global({NewsCategory.INTERNATIONAL: []})
    assert brief.failed is True


def test_summarize_global_handles_code_fence(summarizer):
    summarizer._call_backend = lambda p: (
        '```json\n{"overall_summary": "ok", "category_highlights": [], "market_sentiment": 50}\n```'
    )
    brief = summarizer.summarize_global({NewsCategory.TECH: [_raw("t")]})
    assert brief.failed is False
    assert brief.overall_summary == "ok"


def test_summarize_global_clamps_sentiment(summarizer):
    summarizer._call_backend = lambda p: (
        '{"overall_summary": "", "category_highlights": [], "market_sentiment": 999}'
    )
    brief = summarizer.summarize_global({NewsCategory.TECH: [_raw("t")]})
    assert brief.market_sentiment == 100


def test_summarize_global_fallback_on_backend_exception(summarizer):
    def raise_exc(_):
        raise RuntimeError("boom")
    summarizer._call_backend = raise_exc
    brief = summarizer.summarize_global({NewsCategory.TECH: [_raw("t")]})
    assert brief.failed is True
    assert "boom" in brief.sentiment_reason


# ── analyze_favorites_impact ─────────────────────────────────────────────────

def test_analyze_favorites_impact_parses_signals(summarizer):
    summarizer._call_backend = lambda p: """{
        "signals": [
            {"stock_id": "2330", "signal": "bullish", "reason": "AI 需求強", "referenced_urls": ["http://a"]},
            {"stock_id": "NVDA", "signal": "bearish", "reason": "中國禁令"}
        ]
    }"""

    signals = summarizer.analyze_favorites_impact(
        [_raw("t")],
        [
            StockInfo(stock_id="2330", stock_name="台積電", market="TWSE"),
            StockInfo(stock_id="NVDA", stock_name="Nvidia", market="US"),
        ],
    )

    assert len(signals) == 2
    assert signals[0].stock_id == "2330"
    assert signals[0].signal == "bullish"
    assert signals[0].referenced_urls == ["http://a"]
    assert signals[1].signal == "bearish"


def test_analyze_favorites_impact_empty_favorites(summarizer):
    assert summarizer.analyze_favorites_impact([_raw("t")], []) == []


def test_analyze_favorites_impact_no_articles_returns_neutral(summarizer):
    signals = summarizer.analyze_favorites_impact(
        [],
        [StockInfo(stock_id="2330", stock_name="台積電", market="TWSE")],
    )
    assert len(signals) == 1
    assert signals[0].signal == "neutral"
    assert "今日無相關新聞" in signals[0].reason


def test_analyze_favorites_impact_fills_missing_stock(summarizer):
    """LLM 只回 2 檔中的 1 檔，另一檔補 neutral。"""
    summarizer._call_backend = lambda p: '{"signals": [{"stock_id": "2330", "signal": "bullish", "reason": "ok"}]}'

    signals = summarizer.analyze_favorites_impact(
        [_raw("t")],
        [
            StockInfo(stock_id="2330", stock_name="台積電", market="TWSE"),
            StockInfo(stock_id="2317", stock_name="鴻海", market="TWSE"),
        ],
    )
    assert len(signals) == 2
    assert signals[0].signal == "bullish"
    assert signals[1].stock_id == "2317"
    assert signals[1].signal == "neutral"


def test_analyze_favorites_impact_normalizes_unknown_signal(summarizer):
    summarizer._call_backend = lambda p: '{"signals": [{"stock_id": "2330", "signal": "very bullish", "reason": "x"}]}'
    signals = summarizer.analyze_favorites_impact(
        [_raw("t")],
        [StockInfo(stock_id="2330", stock_name="台積電", market="TWSE")],
    )
    assert signals[0].signal == "neutral"


def test_analyze_favorites_impact_fallback_on_backend_exception(summarizer):
    def raise_exc(_):
        raise RuntimeError("boom")
    summarizer._call_backend = raise_exc
    signals = summarizer.analyze_favorites_impact(
        [_raw("t")],
        [StockInfo(stock_id="2330", stock_name="台積電", market="TWSE")],
    )
    assert len(signals) == 1
    assert signals[0].signal == "neutral"
    assert "分析失敗" in signals[0].reason
