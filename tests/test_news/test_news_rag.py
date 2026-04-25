"""
Unit tests for Phase 3d news RAG.
"""
import json
from datetime import datetime
from types import SimpleNamespace

import numpy as np

from src.config import AppConfig
from src.news.news_rag import NewsRagService
from tests.test_news.conftest import make_article


def _cfg(enabled: bool = True):
    cfg = AppConfig()
    cfg.news_rag_enabled = enabled
    cfg.gemini_api_key = ""
    cfg.news_rag_top_k = 2
    cfg.news_rag_window_days = 30
    cfg.news_rag_max_new_embeddings_per_day = 100
    cfg.news_rag_embedding_model = "test-embedding"
    cfg.news_rag_max_chat_history_turns = 2
    return cfg


def test_answer_disabled_returns_graceful_response(tmp_path):
    service = NewsRagService(_cfg(enabled=False), tmp_path)

    answer = service.answer("台積電最近如何？")

    assert answer.failed is True
    assert "未啟用" in answer.answer


def test_build_index_dedupes_content_hash_and_retrieve_sorts(tmp_path):
    cfg = _cfg(enabled=True)
    service = NewsRagService(cfg, tmp_path)
    service._client = object()

    def fake_embed(text):
        if "AI" in text:
            return np.array([1.0, 0.0])
        return np.array([0.0, 1.0])

    service._embed_text = fake_embed
    articles = [
        make_article(title="AI demand", url="https://example.com/ai"),
        make_article(title="AI demand", url="https://example.com/ai"),
        make_article(title="Bank earnings", url="https://example.com/bank"),
    ]

    added = service.build_or_update_index(articles)
    citations = service.retrieve("AI outlook", top_k=2)

    assert added == 2
    assert citations[0].url == "https://example.com/ai"
    assert citations[0].score >= citations[1].score


def test_build_index_respects_daily_embedding_limit(tmp_path):
    cfg = _cfg(enabled=True)
    cfg.news_rag_max_new_embeddings_per_day = 1
    service = NewsRagService(cfg, tmp_path)
    service._client = object()
    service._embed_text = lambda text: np.array([1.0, 0.0])

    added = service.build_or_update_index([
        make_article(title="AI 1", url="https://example.com/1"),
        make_article(title="AI 2", url="https://example.com/2"),
    ])

    assert added == 1


def test_build_index_gc_removes_rows_outside_window(tmp_path):
    cfg = _cfg(enabled=True)
    service = NewsRagService(cfg, tmp_path)
    service._client = object()
    np.savez(tmp_path / "rag_embeddings.npz", embeddings=np.array([[1.0, 0.0], [0.0, 1.0]]))
    with open(tmp_path / "rag_metadata.json", "w", encoding="utf-8") as f:
        json.dump({
            "items": [
                {
                    "url": "https://example.com/old",
                    "title": "old",
                    "published_at": "2000-01-01T00:00:00",
                    "content_hash": "old",
                },
                {
                    "url": "https://example.com/new",
                    "title": "new",
                    "published_at": datetime.now().isoformat(),
                    "content_hash": "new",
                },
            ]
        }, f)

    added = service.build_or_update_index([])
    matrix, metadata = service._load_index()

    assert added == 0
    assert matrix.shape[0] == 1
    assert metadata[0]["url"] == "https://example.com/new"


def test_answer_uses_retrieved_citations(tmp_path):
    cfg = _cfg(enabled=True)
    service = NewsRagService(cfg, tmp_path)
    service._client = SimpleNamespace(
        models=SimpleNamespace(
            generate_content=lambda **kwargs: SimpleNamespace(text="根據新聞 [1]，AI 需求升溫。")
        )
    )
    service.retrieve = lambda query: [
        SimpleNamespace(
            url="https://example.com/ai",
            title="AI demand",
            source="Src",
            published_at="2026-04-25T00:00:00+00:00",
            score=0.9,
        )
    ]

    answer = service.answer("AI 最近如何？", chat_history=[{"role": "user", "content": "x"}])

    assert answer.failed is False
    assert answer.citations[0].url == "https://example.com/ai"
    assert "[1]" in answer.answer


def test_trim_history_limits_turns(tmp_path):
    cfg = _cfg(enabled=True)
    service = NewsRagService(cfg, tmp_path)
    history = [{"role": "user", "content": str(i)} for i in range(10)]

    trimmed = service._trim_history(history)

    assert len(trimmed) == 4
    assert trimmed[0]["content"] == "6"
