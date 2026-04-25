"""
Unit tests for Phase 3 news history storage helpers.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone

from src.news.news_models import (
    NewsCategory,
    NewsDailyFile,
)
from src.storage.data_storage import DataStorage
from tests.test_news.conftest import make_article, make_category_result, make_run_result


def _save_daily(storage: DataStorage, date_str: str, daily: NewsDailyFile | None = None) -> None:
    daily = daily or NewsDailyFile(date=date_str, runs=[make_run_result()])
    storage._atomic_write(storage.news_dir / f"{date_str}.json", daily.to_dict())


def test_list_news_dates_filters_sidecars_and_sorts(tmp_path):
    storage = DataStorage(data_dir=str(tmp_path))
    _save_daily(storage, "20260410")
    _save_daily(storage, "20260408")
    storage._atomic_write(storage.news_dir / "latest.json", {"run_at": "x"})
    storage._atomic_write(storage.news_dir / "events.json", {"clusters": []})
    storage._atomic_write(storage.news_dir / "rag_metadata.json", {"items": []})
    (storage.news_dir / "20260409.tmp").write_text("{}", encoding="utf-8")

    assert storage.list_news_dates() == ["20260408", "20260410"]


def test_cleanup_old_news_deletes_only_old_date_files(tmp_path):
    storage = DataStorage(data_dir=str(tmp_path))
    _save_daily(storage, "20260325")
    _save_daily(storage, "20260326")
    _save_daily(storage, "20260424")
    storage._atomic_write(storage.news_dir / "latest.json", {"run_at": "x"})
    storage._atomic_write(storage.news_dir / "events.json", {"clusters": []})
    storage._atomic_write(storage.news_dir / "rag_metadata.json", {"items": []})
    (storage.news_dir / "rag_embeddings.npz").write_bytes(b"fake")

    deleted = storage.cleanup_old_news(30, now=date(2026, 4, 25))

    assert deleted == 1
    assert not (storage.news_dir / "20260325.json").exists()
    assert (storage.news_dir / "20260326.json").exists()
    assert (storage.news_dir / "20260424.json").exists()
    assert (storage.news_dir / "latest.json").exists()
    assert (storage.news_dir / "events.json").exists()
    assert (storage.news_dir / "rag_metadata.json").exists()
    assert (storage.news_dir / "rag_embeddings.npz").exists()


def test_load_news_range_skips_corrupted_file(tmp_path):
    storage = DataStorage(data_dir=str(tmp_path))
    _save_daily(storage, "20260410")
    (storage.news_dir / "20260411.json").write_text("{bad json", encoding="utf-8")
    _save_daily(storage, "20260412")

    daily_files = storage.load_news_range("20260410", "20260412")

    assert [d.date for d in daily_files] == ["20260410", "20260412"]


def test_iter_news_articles_dedupes_by_url_and_keeps_latest_occurrence(tmp_path):
    storage = DataStorage(data_dir=str(tmp_path))
    old_article = make_article(
        title="Old version",
        summary="old",
        related=["2330"],
        url="https://example.com/duplicate",
    )
    new_article = replace(old_article, title="New version", summary="new", related_stock_ids=["2317"])
    other_article = make_article(
        title="Other",
        summary="other",
        url="https://example.com/other",
        category=NewsCategory.TECH,
    )

    run1 = make_run_result({
        NewsCategory.FINANCIAL: make_category_result(NewsCategory.FINANCIAL, [old_article]),
    })
    run2 = make_run_result({
        NewsCategory.FINANCIAL: make_category_result(NewsCategory.FINANCIAL, [new_article]),
        NewsCategory.TECH: make_category_result(NewsCategory.TECH, [other_article]),
    })
    _save_daily(storage, "20260410", NewsDailyFile(date="20260410", runs=[run1, run2]))

    articles = list(storage.iter_news_articles("20260410", "20260410"))

    assert [a.url for a in articles] == [
        "https://example.com/duplicate",
        "https://example.com/other",
    ]
    assert articles[0].title == "New version"
    assert articles[0].summary == "new"
    assert articles[0].related_stock_ids == ["2317"]


def test_news_article_local_date_uses_asia_taipei_timezone():
    article = make_article(
        published_at=datetime(2026, 4, 10, 16, 30, tzinfo=timezone.utc),
    )

    assert DataStorage.news_article_local_date(article) == "20260411"
