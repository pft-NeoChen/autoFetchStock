"""
News collection and summarization submodule for autoFetchStock.

Provides:
- NewsFetcher: RSS + full-text article fetching
- NewsSummarizer: Gemini API summarization + stock tagging
- NewsProcessor: Orchestrates the full collection pipeline
- news_models: All dataclasses and enums for the news submodule
"""

from src.news.news_models import (
    NewsCategory,
    NewsArticle,
    NewsCategoryResult,
    NewsRunStats,
    NewsRunResult,
    NewsDailyFile,
)
from src.news.news_fetcher import NewsFetcher
from src.news.news_summarizer import NewsSummarizer
from src.news.news_processor import NewsProcessor

__all__ = [
    "NewsCategory",
    "NewsArticle",
    "NewsCategoryResult",
    "NewsRunStats",
    "NewsRunResult",
    "NewsDailyFile",
    "NewsFetcher",
    "NewsSummarizer",
    "NewsProcessor",
]
