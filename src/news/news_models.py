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
class SectorHeat:
    """Phase 2: per-sector heat indicator extracted from today's news."""
    sector: str                                # 板塊名稱（如「AI」、「半導體」、「電動車」、「金融」、「傳產」）
    heat_score: int = 50                       # 熱度 0~100（0=極冷, 100=極熱）
    trend: str = "flat"                        # "up" | "down" | "flat"
    summary: str = ""                          # 一句話說明（≤80 字）
    referenced_urls: List[str] = field(default_factory=list)  # 支撐判斷的新聞 URL（最多 3 個）

    def to_dict(self) -> dict:
        return {
            "sector": self.sector,
            "heat_score": self.heat_score,
            "trend": self.trend,
            "summary": self.summary,
            "referenced_urls": self.referenced_urls,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SectorHeat":
        score = data.get("heat_score", 50)
        try:
            score = max(0, min(100, int(score)))
        except (TypeError, ValueError):
            score = 50
        trend = str(data.get("trend", "flat")).lower()
        if trend not in ("up", "down", "flat"):
            trend = "flat"
        return cls(
            sector=str(data.get("sector", "")).strip(),
            heat_score=score,
            trend=trend,
            summary=str(data.get("summary", "")).strip(),
            referenced_urls=[str(u) for u in data.get("referenced_urls", [])][:3],
        )


@dataclass
class GlobalBrief:
    """Aggregated insight produced by a single Gemini call over all articles."""
    overall_summary: str = ""                 # 今日重點總結（≤300 字）
    category_highlights: List[CategoryHighlight] = field(default_factory=list)
    market_sentiment: int = 50                # 市場情緒 0~100（0=極度恐慌, 100=極度樂觀）
    sentiment_reason: str = ""                # 情緒分數的一句話理由
    sector_heats: List[SectorHeat] = field(default_factory=list)  # Phase 2: 板塊熱度排名
    failed: bool = False                      # 是否整體失敗

    def to_dict(self) -> dict:
        return {
            "overall_summary": self.overall_summary,
            "category_highlights": [h.to_dict() for h in self.category_highlights],
            "market_sentiment": self.market_sentiment,
            "sentiment_reason": self.sentiment_reason,
            "sector_heats": [s.to_dict() for s in self.sector_heats],
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
            sector_heats=[
                SectorHeat.from_dict(s) for s in data.get("sector_heats", [])
            ],
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
class EventCluster:
    """Phase 3b: cross-day event cluster for news timeline analysis."""
    event_id: str
    title: str
    summary: str = ""
    keywords: List[str] = field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""
    article_urls: List[str] = field(default_factory=list)
    daily_count: Dict[str, int] = field(default_factory=dict)
    sectors: List[str] = field(default_factory=list)
    related_stock_ids: List[str] = field(default_factory=list)
    is_anomaly: bool = False
    anomaly_score: float = 0.0
    anomaly_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "title": self.title,
            "summary": self.summary,
            "keywords": self.keywords,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "article_urls": self.article_urls,
            "daily_count": self.daily_count,
            "sectors": self.sectors,
            "related_stock_ids": self.related_stock_ids,
            "is_anomaly": self.is_anomaly,
            "anomaly_score": self.anomaly_score,
            "anomaly_reason": self.anomaly_reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EventCluster":
        daily_count: Dict[str, int] = {}
        for day, count in (data.get("daily_count") or {}).items():
            try:
                daily_count[str(day)] = max(0, int(count))
            except (TypeError, ValueError):
                daily_count[str(day)] = 0
        try:
            anomaly_score = float(data.get("anomaly_score", 0.0))
        except (TypeError, ValueError):
            anomaly_score = 0.0
        return cls(
            event_id=str(data.get("event_id", "")).strip(),
            title=str(data.get("title", "")).strip(),
            summary=str(data.get("summary", "")).strip(),
            keywords=[str(k).strip() for k in data.get("keywords", []) if str(k).strip()],
            first_seen=str(data.get("first_seen", "")).strip(),
            last_seen=str(data.get("last_seen", "")).strip(),
            article_urls=[str(u) for u in data.get("article_urls", []) if str(u)],
            daily_count=daily_count,
            sectors=[str(s).strip() for s in data.get("sectors", []) if str(s).strip()],
            related_stock_ids=[
                str(s).strip()
                for s in data.get("related_stock_ids", [])
                if str(s).strip()
            ],
            is_anomaly=bool(data.get("is_anomaly", False)),
            anomaly_score=anomaly_score,
            anomaly_reason=str(data.get("anomaly_reason", "")).strip(),
        )


@dataclass
class NewsEventFile:
    """Root structure for data/news/events.json."""
    generated_at: datetime = field(default_factory=datetime.now)
    window_start: str = ""
    window_end: str = ""
    clusters: List[EventCluster] = field(default_factory=list)
    source_article_count: int = 0

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at.isoformat(),
            "window_start": self.window_start,
            "window_end": self.window_end,
            "clusters": [c.to_dict() for c in self.clusters],
            "source_article_count": self.source_article_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NewsEventFile":
        try:
            generated_at = datetime.fromisoformat(data["generated_at"])
        except (KeyError, TypeError, ValueError):
            generated_at = datetime.now()
        try:
            source_article_count = max(0, int(data.get("source_article_count", 0)))
        except (TypeError, ValueError):
            source_article_count = 0
        return cls(
            generated_at=generated_at,
            window_start=str(data.get("window_start", "")).strip(),
            window_end=str(data.get("window_end", "")).strip(),
            clusters=[
                EventCluster.from_dict(c)
                for c in data.get("clusters", [])
                if isinstance(c, dict)
            ],
            source_article_count=source_article_count,
        )


@dataclass
class NewsRagCitation:
    """A retrieved news source used by the RAG answer."""
    url: str
    title: str
    source: str = ""
    published_at: str = ""
    score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "source": self.source,
            "published_at": self.published_at,
            "score": self.score,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NewsRagCitation":
        try:
            score = float(data.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        return cls(
            url=str(data.get("url", "")),
            title=str(data.get("title", "")),
            source=str(data.get("source", "")),
            published_at=str(data.get("published_at", "")),
            score=score,
        )


@dataclass
class NewsRagAnswer:
    """Answer returned by the news RAG subsystem."""
    answer: str
    citations: List[NewsRagCitation] = field(default_factory=list)
    failed: bool = False
    error_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "citations": [c.to_dict() for c in self.citations],
            "failed": self.failed,
            "error_reason": self.error_reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NewsRagAnswer":
        return cls(
            answer=str(data.get("answer", "")),
            citations=[
                NewsRagCitation.from_dict(c) for c in data.get("citations", [])
                if isinstance(c, dict)
            ],
            failed=bool(data.get("failed", False)),
            error_reason=str(data.get("error_reason", "")),
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
