"""Unit tests for Phase 4.6 batch per-article summary."""

from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

from src.config import AppConfig
from src.news.news_fetcher import RawArticle
from src.news.news_models import (
    NewsArticle,
    NewsCategory,
    NewsCategoryResult,
    NewsDailyFile,
    NewsRunResult,
    NewsRunStats,
)
from src.news.news_summarizer import NewsSummarizer
from src.news.news_processor import NewsProcessor


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def summarizer():
    cfg = AppConfig()
    cfg.news_summarizer_backend = "gemini"
    with patch.object(NewsSummarizer, "_init_sdk", lambda self: None):
        s = NewsSummarizer(cfg)
    # Tests bypass real SDK by stubbing _call_backend on the instance.
    # Pretend the SDK is wired so summarize_articles_batch doesn't early-return.
    s._client = object()
    s._model_name = "test"
    return s


def _raw(idx: int) -> RawArticle:
    return RawArticle(
        title=f"標題 {idx}",
        url=f"https://example.com/a{idx}",
        source="Src",
        published_at=datetime(2026, 5, 8),
        excerpt=f"excerpt {idx}",
        full_text=f"full text {idx}",
        full_text_fetched=True,
    )


# ── summarize_articles_batch ───────────────────────────────────────────────


def test_batch_returns_url_to_summary_map(summarizer):
    raws = [_raw(i) for i in range(3)]
    summarizer._call_backend = lambda prompt: (
        '[{"url":"https://example.com/a0","summary":"摘要 0"},'
        ' {"url":"https://example.com/a1","summary":"摘要 1"},'
        ' {"url":"https://example.com/a2","summary":"摘要 2"}]'
    )

    out = summarizer.summarize_articles_batch(raws, chunk_size=10)

    assert out == {
        "https://example.com/a0": "摘要 0",
        "https://example.com/a1": "摘要 1",
        "https://example.com/a2": "摘要 2",
    }


def test_batch_chunks_by_size_and_calls_once_per_chunk(summarizer):
    raws = [_raw(i) for i in range(7)]
    calls = []

    def fake_backend(prompt: str) -> str:
        calls.append(prompt)
        # Echo back two known url entries from the prompt to keep the test
        # deterministic regardless of chunking order.
        idx = len(calls) - 1
        start = idx * 3
        end = start + 3
        items = [
            f'{{"url":"https://example.com/a{i}","summary":"s{i}"}}'
            for i in range(start, min(end, 7))
        ]
        return "[" + ",".join(items) + "]"

    summarizer._call_backend = fake_backend

    out = summarizer.summarize_articles_batch(raws, chunk_size=3)

    # 7 articles / 3 = 3 chunks (3 + 3 + 1)
    assert len(calls) == 3
    assert len(out) == 7


def test_batch_chunk_failure_isolates_other_chunks(summarizer):
    raws = [_raw(i) for i in range(4)]
    backend_calls = {"n": 0}

    def fake_backend(prompt: str) -> str:
        backend_calls["n"] += 1
        if backend_calls["n"] == 1:
            return "this is not json at all"
        # Second chunk OK
        return (
            '[{"url":"https://example.com/a2","summary":"ok2"},'
            ' {"url":"https://example.com/a3","summary":"ok3"}]'
        )

    summarizer._call_backend = fake_backend

    out = summarizer.summarize_articles_batch(raws, chunk_size=2)

    assert "https://example.com/a0" not in out
    assert "https://example.com/a1" not in out
    assert out["https://example.com/a2"] == "ok2"
    assert out["https://example.com/a3"] == "ok3"


def test_batch_strips_markdown_code_fence(summarizer):
    raws = [_raw(0)]
    summarizer._call_backend = lambda prompt: (
        '```json\n[{"url":"https://example.com/a0","summary":"OK"}]\n```'
    )
    out = summarizer.summarize_articles_batch(raws, chunk_size=5)
    assert out == {"https://example.com/a0": "OK"}


def test_batch_drops_entries_with_blank_summary(summarizer):
    raws = [_raw(0), _raw(1)]
    summarizer._call_backend = lambda prompt: (
        '[{"url":"https://example.com/a0","summary":""},'
        ' {"url":"https://example.com/a1","summary":"有摘要"}]'
    )
    out = summarizer.summarize_articles_batch(raws, chunk_size=5)
    assert out == {"https://example.com/a1": "有摘要"}


def test_batch_empty_input_short_circuits(summarizer):
    summarizer._call_backend = lambda prompt: pytest.fail("must not be called")
    assert summarizer.summarize_articles_batch([]) == {}


# ── _format_sections honours summary_map ───────────────────────────────────


def test_format_sections_prefers_summary_over_excerpt():
    raws_by_cat = {
        NewsCategory.FINANCIAL: [
            RawArticle(
                title="台積電法說",
                url="https://example.com/x",
                source="Src",
                published_at=datetime(2026, 5, 8),
                excerpt="excerpt-fallback",
            ),
        ],
    }
    rendered = NewsSummarizer._format_sections(
        raws_by_cat, summary_map={"https://example.com/x": "AI 摘要"}
    )
    assert "AI 摘要" in rendered
    assert "excerpt-fallback" not in rendered


def test_format_sections_falls_back_to_excerpt_when_url_missing():
    raws_by_cat = {
        NewsCategory.FINANCIAL: [
            RawArticle(
                title="t",
                url="https://example.com/x",
                source="Src",
                published_at=datetime(2026, 5, 8),
                excerpt="excerpt-fallback",
            ),
        ],
    }
    rendered = NewsSummarizer._format_sections(raws_by_cat, summary_map={})
    assert "excerpt-fallback" in rendered


# ── NewsProcessor cache + apply helpers ────────────────────────────────────


def _make_processor():
    cfg = AppConfig()
    storage = MagicMock()
    fetcher = MagicMock()
    summarizer = MagicMock()
    p = NewsProcessor(
        config=cfg, storage=storage, fetcher=fetcher, summarizer=summarizer,
    )
    return p, storage, summarizer


def _make_daily_file(articles_by_url):
    """Build a NewsDailyFile with one run + one FINANCIAL category covering given urls."""
    arts = []
    for url, (summary, excerpt) in articles_by_url.items():
        arts.append(
            NewsArticle(
                title="t",
                source="s",
                url=url,
                published_at=datetime(2026, 5, 8),
                category=NewsCategory.FINANCIAL,
                excerpt=excerpt,
                full_text="",
                summary=summary,
            )
        )
    cat_result = NewsCategoryResult(
        category=NewsCategory.FINANCIAL,
        articles=arts,
        article_count=len(arts),
    )
    run = NewsRunResult(
        run_at=datetime(2026, 5, 8),
        finished_at=datetime(2026, 5, 8),
        categories={NewsCategory.FINANCIAL: cat_result},
        run_stats=NewsRunStats(),
    )
    return NewsDailyFile(date="20260508", runs=[run])


def test_load_summary_cache_returns_only_real_summaries():
    p, storage, _ = _make_processor()
    storage.load_news.return_value = _make_daily_file({
        "u1": ("這是一段足夠長的 AI 摘要文字內容超過二十字元", "原始 excerpt"),
        "u2": ("excerpt verbatim", "excerpt verbatim"),  # ← excerpt fallback
        "u3": ("短", "短"),  # ← too short
    })
    cache = p._load_summary_cache()
    assert "u1" in cache
    assert "u2" not in cache
    assert "u3" not in cache


def test_load_summary_cache_handles_missing_file():
    p, storage, _ = _make_processor()
    storage.load_news.return_value = None
    assert p._load_summary_cache() == {}


def test_apply_summaries_overwrites_summary_and_clears_failure_flag():
    p, _, _ = _make_processor()
    cat_result = NewsCategoryResult(
        category=NewsCategory.FINANCIAL,
        articles=[
            NewsArticle(
                title="t", source="s", url="u1",
                published_at=datetime(2026, 5, 8),
                category=NewsCategory.FINANCIAL,
                excerpt="excerpt", full_text="",
                summary="excerpt",  # placeholder fallback
                summary_failed=True,
            ),
            NewsArticle(
                title="t", source="s", url="u2",
                published_at=datetime(2026, 5, 8),
                category=NewsCategory.FINANCIAL,
                excerpt="excerpt2", full_text="",
                summary="excerpt2",
                summary_failed=False,
            ),
        ],
    )
    categories = {NewsCategory.FINANCIAL: cat_result}
    p._apply_summaries(categories, {"u1": "AI 真摘要"})

    art1, art2 = cat_result.articles
    assert art1.summary == "AI 真摘要"
    assert art1.summary_failed is False
    # u2 missed in summary_map → flag failure but keep excerpt fallback
    assert art2.summary == "excerpt2"
    assert art2.summary_failed is True


def test_dedupe_raws_preserves_order():
    a, b, c = _raw(1), _raw(2), _raw(1)  # a and c share URL
    assert NewsProcessor._dedupe_raws([a, b, c]) == [a, b]


def test_batch_summarize_articles_skips_when_all_cached():
    p, storage, summarizer = _make_processor()
    storage.load_news.return_value = _make_daily_file({
        "https://example.com/a0": ("長度足夠的 AI 摘要文字 over twenty chars", "excerpt"),
    })
    raws = [_raw(0)]
    out = p._batch_summarize_articles(raws)
    summarizer.summarize_articles_batch.assert_not_called()
    assert out["https://example.com/a0"].startswith("長度足夠")


def test_batch_summarize_articles_calls_llm_for_uncached_only():
    p, storage, summarizer = _make_processor()
    storage.load_news.return_value = _make_daily_file({
        "https://example.com/a0": ("AI 摘要長度足夠 over twenty chars total here", "excerpt"),
    })
    summarizer.summarize_articles_batch.return_value = {
        "https://example.com/a1": "新摘要",
    }
    raws = [_raw(0), _raw(1)]
    out = p._batch_summarize_articles(raws)

    summarizer.summarize_articles_batch.assert_called_once()
    sent = summarizer.summarize_articles_batch.call_args[0][0]
    assert [r.url for r in sent] == ["https://example.com/a1"]
    assert out["https://example.com/a0"].startswith("AI 摘要")
    assert out["https://example.com/a1"] == "新摘要"
