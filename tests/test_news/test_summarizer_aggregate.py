"""
Unit tests for Phase 1 aggregate analysis methods on NewsSummarizer.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.config import AppConfig
from src.models import StockInfo
from src.news.news_fetcher import RawArticle
from src.news.news_models import FavoriteSignal, GlobalBrief, NewsCategory
from src.news.news_summarizer import NewsSummarizer
from tests.test_news.conftest import make_article


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


# ── Phase 2: sector_heats parsing ────────────────────────────────────────────

def test_summarize_global_parses_sector_heats(summarizer):
    summarizer._call_backend = lambda p: """{
        "overall_summary": "ok",
        "category_highlights": [],
        "market_sentiment": 60,
        "sentiment_reason": "r",
        "sector_heats": [
            {"sector": "AI", "heat_score": 85, "trend": "up", "summary": "AI 熱", "referenced_urls": ["http://a"]},
            {"sector": "半導體", "heat_score": 78, "trend": "up", "summary": "供應鏈緊", "referenced_urls": []},
            {"sector": "電動車", "heat_score": 45, "trend": "flat", "summary": "持平", "referenced_urls": []},
            {"sector": "金融", "heat_score": 30, "trend": "down", "summary": "降息壓力", "referenced_urls": []},
            {"sector": "傳產", "heat_score": 20, "trend": "flat", "summary": "無關注", "referenced_urls": []}
        ]
    }"""

    brief = summarizer.summarize_global({NewsCategory.TECH: [_raw("t")]})
    assert brief.failed is False
    assert len(brief.sector_heats) == 5
    assert brief.sector_heats[0].sector == "AI"
    assert brief.sector_heats[0].heat_score == 85
    assert brief.sector_heats[3].trend == "down"


def test_summarize_global_clamps_sector_heat_score(summarizer):
    summarizer._call_backend = lambda p: """{
        "overall_summary": "x",
        "category_highlights": [],
        "market_sentiment": 50,
        "sector_heats": [
            {"sector": "AI", "heat_score": 999, "trend": "up"},
            {"sector": "金融", "heat_score": -50, "trend": "down"}
        ]
    }"""
    brief = summarizer.summarize_global({NewsCategory.TECH: [_raw("t")]})
    assert brief.sector_heats[0].heat_score == 100
    assert brief.sector_heats[1].heat_score == 0


def test_summarize_global_normalises_invalid_sector_trend(summarizer):
    summarizer._call_backend = lambda p: """{
        "overall_summary": "x",
        "category_highlights": [],
        "market_sentiment": 50,
        "sector_heats": [
            {"sector": "AI", "heat_score": 70, "trend": "skyrocket"}
        ]
    }"""
    brief = summarizer.summarize_global({NewsCategory.TECH: [_raw("t")]})
    assert brief.sector_heats[0].trend == "flat"


def test_summarize_global_dedupes_duplicate_sectors(summarizer):
    summarizer._call_backend = lambda p: """{
        "overall_summary": "x",
        "category_highlights": [],
        "market_sentiment": 50,
        "sector_heats": [
            {"sector": "AI", "heat_score": 80, "trend": "up"},
            {"sector": "AI", "heat_score": 30, "trend": "down"}
        ]
    }"""
    brief = summarizer.summarize_global({NewsCategory.TECH: [_raw("t")]})
    assert len(brief.sector_heats) == 1
    assert brief.sector_heats[0].heat_score == 80


def test_summarize_global_missing_sector_heats_field(summarizer):
    """If LLM omits sector_heats entirely, brief.sector_heats == []."""
    summarizer._call_backend = lambda p: """{
        "overall_summary": "x",
        "category_highlights": [],
        "market_sentiment": 50
    }"""
    brief = summarizer.summarize_global({NewsCategory.TECH: [_raw("t")]})
    assert brief.failed is False
    assert brief.sector_heats == []


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


# ── Phase 3b: event clustering ───────────────────────────────────────────────

def test_cluster_events_parses_valid_response_and_generates_event_id(summarizer):
    article = make_article(
        title="台積電財報優於預期",
        url="https://example.com/a",
        related=["2330"],
    )
    summarizer._call_backend = lambda p: """{
        "clusters": [
            {
                "title": "台積電財報",
                "summary": "台積電財報優於預期",
                "keywords": ["台積電", "財報"],
                "article_urls": ["https://example.com/a"],
                "sectors": ["半導體"],
                "related_stock_ids": ["2330"]
            }
        ]
    }"""

    clusters = summarizer.cluster_events([article])

    assert len(clusters) == 1
    assert clusters[0].event_id
    assert clusters[0].title == "台積電財報"
    assert clusters[0].article_urls == ["https://example.com/a"]
    assert clusters[0].related_stock_ids == ["2330"]


def test_cluster_events_discards_unknown_urls(summarizer):
    article = make_article(url="https://example.com/known")
    summarizer._call_backend = lambda p: """{
        "clusters": [
            {"title": "x", "keywords": ["x"], "article_urls": ["https://bad.example/missing"]}
        ]
    }"""

    assert summarizer.cluster_events([article]) == []


def test_cluster_events_event_id_stable_for_same_title_and_keywords(summarizer):
    raw = """{
        "clusters": [
            {"title": "AI 供應鏈", "keywords": ["AI", "半導體"], "article_urls": ["https://example.com/a"]}
        ]
    }"""
    article = make_article(url="https://example.com/a")
    summarizer._call_backend = lambda p: raw

    first = summarizer.cluster_events([article])[0].event_id
    second = summarizer.cluster_events([article])[0].event_id

    assert first == second


def test_cluster_events_limits_prompt_to_recent_800_articles(summarizer):
    captured = {}

    def fake_call(prompt):
        captured["prompt"] = prompt
        return '{"clusters": []}'

    summarizer._call_backend = fake_call
    base = datetime(2026, 4, 1, tzinfo=timezone.utc)
    articles = [
        make_article(
            title=f"Article {idx}",
            url=f"https://example.com/{idx}",
            published_at=base + timedelta(minutes=idx),
        )
        for idx in range(805)
    ]

    summarizer.cluster_events(articles)

    prompt = captured["prompt"]
    assert "URL: https://example.com/804\n" in prompt
    assert "URL: https://example.com/5\n" in prompt
    assert "URL: https://example.com/4\n" not in prompt
