"""
Data models for the news collection and summarization submodule.

Defines:
- NewsCategory: Enum for news categories
- NewsArticle: Single news article dataclass
- NewsCategoryResult: Collection result for one category
- NewsRunStats: Execution statistics
- NewsRunResult: Single run result
- NewsDailyFile: Daily JSON file root structure
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional


class NewsCategory(Enum):
    """News category types."""
    INTERNATIONAL = "INTERNATIONAL"   # 國際新聞
    FINANCIAL     = "FINANCIAL"       # 財經/經濟新聞
    TECH          = "TECH"            # 科技產業新聞
    STOCK_TW      = "STOCK_TW"        # 台灣個股相關新聞
    STOCK_US      = "STOCK_US"        # 美國個股相關新聞

    @property
    def display_name(self) -> str:
        """Return Chinese display name."""
        names = {
            NewsCategory.INTERNATIONAL: "國際",
            NewsCategory.FINANCIAL:     "財經",
            NewsCategory.TECH:          "科技",
            NewsCategory.STOCK_TW:      "台股個股",
            NewsCategory.STOCK_US:      "美股個股",
        }
        return names[self]


@dataclass
class NewsArticle:
    """Single news article with summary and stock tags."""
    title: str                              # 文章標題（原文）
    source: str                             # 新聞來源（如 "Reuters"）
    url: str                                # 原始文章 URL
    published_at: datetime                  # 發布時間
    category: NewsCategory                  # 所屬分類
    excerpt: str                            # RSS 提供的短摘錄
    full_text: str                          # 全文內容（BeautifulSoup 解析）
    summary: str                            # 繁體中文摘要（Gemini 生成，≤200 字）
    related_stock_ids: List[str] = field(default_factory=list)  # 關聯股票代號
    full_text_fetched: bool = True          # 是否成功取得全文
    summary_failed: bool = False            # 摘要是否失敗

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "source": self.source,
            "url": self.url,
            "published_at": self.published_at.isoformat(),
            "category": self.category.value,
            "excerpt": self.excerpt,
            "full_text": self.full_text,
            "summary": self.summary,
            "related_stock_ids": self.related_stock_ids,
            "full_text_fetched": self.full_text_fetched,
            "summary_failed": self.summary_failed,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NewsArticle":
        return cls(
            title=data["title"],
            source=data["source"],
            url=data["url"],
            published_at=datetime.fromisoformat(data["published_at"]),
            category=NewsCategory(data["category"]),
            excerpt=data.get("excerpt", ""),
            full_text=data.get("full_text", ""),
            summary=data.get("summary", ""),
            related_stock_ids=data.get("related_stock_ids", []),
            full_text_fetched=data.get("full_text_fetched", True),
            summary_failed=data.get("summary_failed", False),
        )


@dataclass
class NewsCategoryResult:
    """Collection and summarization result for a single news category."""
    category: NewsCategory
    articles: List[NewsArticle] = field(default_factory=list)
    category_summary: str = ""              # 分類整體摘要（≤500 字）
    fetched_at: Optional[datetime] = None   # 本次收集時間戳記
    article_count: int = 0                  # 成功收集篇數
    failed_count: int = 0                   # 失敗篇數
    summary_failed: bool = False            # 整體摘要是否失敗

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "articles": [a.to_dict() for a in self.articles],
            "category_summary": self.category_summary,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "article_count": self.article_count,
            "failed_count": self.failed_count,
            "summary_failed": self.summary_failed,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NewsCategoryResult":
        return cls(
            category=NewsCategory(data["category"]),
            articles=[NewsArticle.from_dict(a) for a in data.get("articles", [])],
            category_summary=data.get("category_summary", ""),
            fetched_at=datetime.fromisoformat(data["fetched_at"]) if data.get("fetched_at") else None,
            article_count=data.get("article_count", 0),
            failed_count=data.get("failed_count", 0),
            summary_failed=data.get("summary_failed", False),
        )


@dataclass
class NewsRunStats:
    """Statistics for a single news collection run."""
    total_articles: int = 0
    successful_articles: int = 0
    failed_articles: int = 0
    total_summaries: int = 0
    failed_summaries: int = 0
    duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "total_articles": self.total_articles,
            "successful_articles": self.successful_articles,
            "failed_articles": self.failed_articles,
            "total_summaries": self.total_summaries,
            "failed_summaries": self.failed_summaries,
            "duration_seconds": self.duration_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NewsRunStats":
        return cls(
            total_articles=data.get("total_articles", 0),
            successful_articles=data.get("successful_articles", 0),
            failed_articles=data.get("failed_articles", 0),
            total_summaries=data.get("total_summaries", 0),
            failed_summaries=data.get("failed_summaries", 0),
            duration_seconds=data.get("duration_seconds", 0.0),
        )


@dataclass
class CategoryHighlight:
    """Per-category key points extracted by global summary."""
    category: NewsCategory
    headline_points: List[str] = field(default_factory=list)  # 3~5 個要點

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "headline_points": self.headline_points,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CategoryHighlight":
        return cls(
            category=NewsCategory(data["category"]),
            headline_points=data.get("headline_points", []),
        )


@dataclass
class GlobalBrief:
    """Aggregated insight produced by a single Gemini call over all articles."""
    overall_summary: str = ""                 # 今日重點總結（≤300 字）
    category_highlights: List[CategoryHighlight] = field(default_factory=list)
    market_sentiment: int = 50                # 市場情緒 0~100（0=極度恐慌, 100=極度樂觀）
    sentiment_reason: str = ""                # 情緒分數的一句話理由
    failed: bool = False                      # 是否整體失敗

    def to_dict(self) -> dict:
        return {
            "overall_summary": self.overall_summary,
            "category_highlights": [h.to_dict() for h in self.category_highlights],
            "market_sentiment": self.market_sentiment,
            "sentiment_reason": self.sentiment_reason,
            "failed": self.failed,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GlobalBrief":
        return cls(
            overall_summary=data.get("overall_summary", ""),
            category_highlights=[
                CategoryHighlight.from_dict(h) for h in data.get("category_highlights", [])
            ],
            market_sentiment=int(data.get("market_sentiment", 50)),
            sentiment_reason=data.get("sentiment_reason", ""),
            failed=data.get("failed", False),
        )


@dataclass
class FavoriteSignal:
    """Per-favorite-stock impact signal derived from today's news."""
    stock_id: str
    stock_name: str
    signal: str = "neutral"                   # "bullish" | "neutral" | "bearish"
    reason: str = ""                          # 一句話理由（≤120 字）
    referenced_urls: List[str] = field(default_factory=list)  # 支撐判斷的新聞 URL

    def to_dict(self) -> dict:
        return {
            "stock_id": self.stock_id,
            "stock_name": self.stock_name,
            "signal": self.signal,
            "reason": self.reason,
            "referenced_urls": self.referenced_urls,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FavoriteSignal":
        return cls(
            stock_id=data["stock_id"],
            stock_name=data.get("stock_name", data["stock_id"]),
            signal=data.get("signal", "neutral"),
            reason=data.get("reason", ""),
            referenced_urls=data.get("referenced_urls", []),
        )


@dataclass
class NewsRunResult:
    """Result of a single news collection and summarization run."""
    run_at: datetime                                              # 執行觸發時間（Asia/Taipei）
    finished_at: Optional[datetime] = None                       # 完成時間
    categories: Dict[NewsCategory, NewsCategoryResult] = field(default_factory=dict)
    run_stats: Optional[NewsRunStats] = None
    global_brief: Optional[GlobalBrief] = None                  # Phase 1: 今日重點聚合分析
    favorite_signals: List[FavoriteSignal] = field(default_factory=list)  # Phase 1: 自選股訊號

    def to_dict(self) -> dict:
        return {
            "run_at": self.run_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "categories": {
                cat.value: result.to_dict()
                for cat, result in self.categories.items()
            },
            "run_stats": self.run_stats.to_dict() if self.run_stats else None,
            "global_brief": self.global_brief.to_dict() if self.global_brief else None,
            "favorite_signals": [s.to_dict() for s in self.favorite_signals],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NewsRunResult":
        cats: Dict[NewsCategory, NewsCategoryResult] = {}
        for key, val in data.get("categories", {}).items():
            try:
                cat = NewsCategory(key)
                cats[cat] = NewsCategoryResult.from_dict(val)
            except ValueError:
                pass  # skip unknown categories
        return cls(
            run_at=datetime.fromisoformat(data["run_at"]),
            finished_at=datetime.fromisoformat(data["finished_at"]) if data.get("finished_at") else None,
            categories=cats,
            run_stats=NewsRunStats.from_dict(data["run_stats"]) if data.get("run_stats") else None,
            global_brief=GlobalBrief.from_dict(data["global_brief"]) if data.get("global_brief") else None,
            favorite_signals=[
                FavoriteSignal.from_dict(s) for s in data.get("favorite_signals", [])
            ],
        )


@dataclass
class NewsDailyFile:
    """Root structure for daily news JSON file (data/news/{yyyymmdd}.json)."""
    date: str                               # 格式 "YYYYMMDD"（Asia/Taipei）
    runs: List[NewsRunResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "runs": [r.to_dict() for r in self.runs],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NewsDailyFile":
        return cls(
            date=data["date"],
            runs=[NewsRunResult.from_dict(r) for r in data.get("runs", [])],
        )
