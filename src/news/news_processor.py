"""
News processor for autoFetchStock news submodule.

Orchestrates the full news collection pipeline:
1. Load favorites from DataStorage
2. Fetch + summarize each category independently
3. Save results to data/news/{yyyymmdd}.json + latest.json
"""

import logging
import time
from datetime import datetime
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from src.config import AppConfig
from src.exceptions import SchedulerTaskError
from src.models import StockInfo
from src.news.news_fetcher import NewsFetcher
from src.news.news_models import (
    FavoriteSignal,
    GlobalBrief,
    NewsCategory,
    NewsArticle,
    NewsCategoryResult,
    NewsRunResult,
    NewsRunStats,
)
from src.news.news_summarizer import NewsSummarizer

logger = logging.getLogger("autofetchstock.news.processor")
TW_TIMEZONE = ZoneInfo("Asia/Taipei")

# Processing order
_FIXED_CATEGORIES = [
    NewsCategory.INTERNATIONAL,
    NewsCategory.FINANCIAL,
    NewsCategory.TECH,
]
_STOCK_CATEGORIES = [
    NewsCategory.STOCK_TW,
    NewsCategory.STOCK_US,
]


class NewsProcessor:
    """Orchestrates news collection and summarization pipeline."""

    def __init__(
        self,
        config: AppConfig,
        storage,  # DataStorage (type hint avoided to prevent circular import)
        fetcher: Optional[NewsFetcher] = None,
        summarizer: Optional[NewsSummarizer] = None,
    ) -> None:
        self._config = config
        self._storage = storage
        self._fetcher = fetcher or NewsFetcher(config=config)
        self._summarizer = summarizer or NewsSummarizer(config=config)

    def run(self) -> NewsRunResult:
        """
        Execute one full news collection and summarization cycle.
        Called by APScheduler every hour between 08:00-15:00.
        """
        run_at = datetime.now(tz=TW_TIMEZONE)
        logger.info("新聞收集開始: %s", run_at.strftime("%Y-%m-%d %H:%M"))
        t_start = time.monotonic()

        favorites = self._load_favorites()
        self._summarizer.set_favorites(favorites)

        categories: Dict[NewsCategory, NewsCategoryResult] = {}
        raw_by_category: Dict[NewsCategory, list] = {}

        # Fetch-only phase（不再逐篇呼叫 LLM 摘要）
        for cat in _FIXED_CATEGORIES:
            try:
                cat_result, raws = self._fetch_category(cat)
                categories[cat] = cat_result
                raw_by_category[cat] = raws
            except Exception as exc:
                logger.error("分類抓取失敗 [%s]: %s", cat.display_name, exc, exc_info=True)
                categories[cat] = NewsCategoryResult(
                    category=cat,
                    fetched_at=datetime.now(tz=TW_TIMEZONE),
                    summary_failed=True,
                )
                raw_by_category[cat] = []

        if favorites:
            for cat in _STOCK_CATEGORIES:
                try:
                    cat_result, raws = self._fetch_stock_category(cat, favorites)
                    categories[cat] = cat_result
                    raw_by_category[cat] = raws
                except Exception as exc:
                    logger.error("個股分類抓取失敗 [%s]: %s", cat.display_name, exc, exc_info=True)
                    categories[cat] = NewsCategoryResult(
                        category=cat,
                        fetched_at=datetime.now(tz=TW_TIMEZONE),
                        summary_failed=True,
                    )
                    raw_by_category[cat] = []
        else:
            logger.warning("我的最愛為空，略過 STOCK_TW / STOCK_US 分類")
            for cat in _STOCK_CATEGORIES:
                categories[cat] = NewsCategoryResult(
                    category=cat,
                    fetched_at=datetime.now(tz=TW_TIMEZONE),
                )
                raw_by_category[cat] = []

        # Aggregate-analysis phase：2 次 Gemini 呼叫
        logger.info("開始全局重點分析 + 自選股影響分析")
        global_brief = self._summarizer.summarize_global(raw_by_category)
        all_raw_articles = [a for arts in raw_by_category.values() for a in arts]
        favorite_signals = self._summarizer.analyze_favorites_impact(
            all_raw_articles, favorites
        )

        duration = time.monotonic() - t_start
        if duration > self._config.news_max_run_minutes * 60:
            logger.warning("新聞收集執行時間過長: %.1f 分鐘", duration / 60)

        stats = self._build_stats(list(categories.values()), duration)
        finished_at = datetime.now(tz=TW_TIMEZONE)
        run_result = NewsRunResult(
            run_at=run_at,
            finished_at=finished_at,
            categories=categories,
            run_stats=stats,
            global_brief=global_brief,
            favorite_signals=favorite_signals,
        )

        try:
            self._storage.save_news(run_result)
        except Exception as exc:
            logger.error("新聞結果儲存失敗: %s", exc, exc_info=True)
            raise SchedulerTaskError(
                task_id="news_collection",
                original_error=exc,
            ) from exc

        logger.info(
            "新聞收集完成: %d 篇文章，%.1f 秒",
            stats.total_articles, duration,
        )
        return run_result

    # ── 分類抓取（不再呼叫 LLM） ────────────────────────────────────────────

    def _fetch_category(
        self,
        category: NewsCategory,
    ) -> "tuple[NewsCategoryResult, list]":
        """Fetch fixed-category news only. Returns (result, raw_articles)."""
        result = NewsCategoryResult(
            category=category,
            fetched_at=datetime.now(tz=TW_TIMEZONE),
        )
        raw_articles = self._fetcher.fetch_category(
            category,
            max_articles=self._config.news_max_articles_per_category,
        )
        articles = self._raws_to_articles(raw_articles, category)
        result.articles = articles
        result.article_count = len(articles)
        result.failed_count = 0
        return result, raw_articles

    def _fetch_stock_category(
        self,
        category: NewsCategory,
        favorites: List[StockInfo],
    ) -> "tuple[NewsCategoryResult, list]":
        """Fetch per-favorite news and merge. Returns (result, raw_articles)."""
        result = NewsCategoryResult(
            category=category,
            fetched_at=datetime.now(tz=TW_TIMEZONE),
        )
        seen_urls: set = set()
        all_raw = []
        related_by_url: Dict[str, List[str]] = {}

        for stock in favorites:
            try:
                raw_list, detected_cat = self._fetcher.fetch_stock_news(stock)
                if detected_cat != category:
                    continue
                for raw in raw_list:
                    related_ids = related_by_url.setdefault(raw.url, [])
                    if stock.stock_id not in related_ids:
                        related_ids.append(stock.stock_id)
                    if raw.url not in seen_urls:
                        seen_urls.add(raw.url)
                        all_raw.append(raw)
            except Exception as exc:
                logger.warning("個股新聞抓取失敗 [%s]: %s", stock.stock_id, exc)

        articles = self._raws_to_articles(all_raw, category, related_by_url)
        result.articles = articles
        result.article_count = len(articles)
        result.failed_count = 0
        return result, all_raw

    @staticmethod
    def _raws_to_articles(
        raw_articles: list,
        category: NewsCategory,
        related_by_url: Optional[Dict[str, List[str]]] = None,
    ) -> List[NewsArticle]:
        """Convert RawArticles to NewsArticles without LLM per-article summarization.
        The `summary` field falls back to the RSS excerpt."""
        articles = []
        related_by_url = related_by_url or {}
        for raw in raw_articles:
            related_ids = list(dict.fromkeys(related_by_url.get(raw.url, [])))
            articles.append(NewsArticle(
                title=raw.title,
                source=raw.source,
                url=raw.url,
                published_at=raw.published_at,
                category=category,
                excerpt=raw.excerpt,
                full_text=raw.full_text,
                summary=raw.excerpt or (raw.full_text[:200] if raw.full_text else ""),
                related_stock_ids=related_ids,
                full_text_fetched=raw.full_text_fetched,
                summary_failed=False,
            ))
        return articles

    # ── 輔助方法 ──────────────────────────────────────────────────────────────

    def _load_favorites(self) -> List[StockInfo]:
        """Load favorites list from DataStorage. Returns [] on any failure (REQ-295)."""
        try:
            raw = self._storage.load_favorites() or []
            result = []
            for item in raw:
                if isinstance(item, dict):
                    result.append(StockInfo(
                        stock_id=item["id"],
                        stock_name=item.get("name", item["id"]),
                        market="TWSE" if item["id"].isdigit() else "US",
                    ))
                elif isinstance(item, StockInfo):
                    result.append(item)
            return result
        except Exception as exc:
            logger.warning("無法讀取我的最愛清單: %s，略過個股分類", exc)
            return []

    def _build_stats(
        self,
        results: List[NewsCategoryResult],
        duration: float,
    ) -> NewsRunStats:
        total = sum(r.article_count + r.failed_count for r in results)
        success = sum(r.article_count for r in results)
        failed = sum(r.failed_count for r in results)
        total_summaries = total
        failed_summaries = sum(
            len([a for a in r.articles if a.summary_failed]) for r in results
        )
        return NewsRunStats(
            total_articles=total,
            successful_articles=success,
            failed_articles=failed,
            total_summaries=total_summaries,
            failed_summaries=failed_summaries,
            duration_seconds=round(duration, 2),
        )
