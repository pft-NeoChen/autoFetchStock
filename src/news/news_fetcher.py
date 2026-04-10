"""
News fetcher for autoFetchStock news submodule.

Handles:
- RSS feed parsing via atoma
- Full-text article fetching via BeautifulSoup
- Per-category and per-stock news collection
- Rate limiting (2s per domain) and source disabling (3 failures → 24h pause)
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import atoma
import requests
from bs4 import BeautifulSoup

from src.config import AppConfig
from src.models import StockInfo
from src.news.news_models import NewsCategory

logger = logging.getLogger("autofetchstock.news.fetcher")

TW_TIMEZONE = ZoneInfo("Asia/Taipei")

# ── RSS 來源設定 ─────────────────────────────────────────────────────────────

RSS_SOURCES: Dict[NewsCategory, List[str]] = {
    NewsCategory.INTERNATIONAL: [
        "https://feeds.reuters.com/reuters/worldNews",
        "https://news.google.com/rss/headlines/section/topic/WORLD?hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    ],
    NewsCategory.FINANCIAL: [
        "https://finance.yahoo.com/news/rssindex",
        "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    ],
    NewsCategory.TECH: [
        "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
        "https://techcrunch.com/feed/",
    ],
}

# Google News 個股查詢 URL 模板
GNEWS_TW_URL = (
    "https://news.google.com/rss/search"
    "?q={keyword}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
)
GNEWS_US_URL = (
    "https://news.google.com/rss/search"
    "?q={keyword}&hl=en-US&gl=US&ceid=US:en"
)

# HTML 全文解析：排除這些標籤的文字
_EXCLUDE_TAGS = {"script", "style", "nav", "header", "footer", "aside", "iframe"}


@dataclass
class RawArticle:
    """Intermediate data before summarization."""
    title: str
    url: str
    source: str
    published_at: datetime
    excerpt: str
    full_text: str = ""
    full_text_fetched: bool = False


@dataclass
class _SourceState:
    """Tracks failure state for a single RSS source URL."""
    consecutive_failures: int = 0
    disabled_until: Optional[datetime] = None

    def is_disabled(self) -> bool:
        if self.disabled_until is None:
            return False
        return datetime.now(tz=TW_TIMEZONE) < self.disabled_until

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= 3:
            self.disabled_until = datetime.now(tz=TW_TIMEZONE) + timedelta(hours=24)
            logger.warning("新聞來源已停用 24 小時（連續失敗 %d 次）", self.consecutive_failures)

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.disabled_until = None


class NewsFetcher:
    """Fetches news articles from RSS feeds and full-text URLs."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        })
        # domain → last request timestamp（速率限制）
        self._domain_last_request: Dict[str, float] = {}
        # url → source state（停用追蹤）
        self._source_states: Dict[str, _SourceState] = {}

    # ── 公開介面 ──────────────────────────────────────────────────────────────

    def fetch_category(
        self,
        category: NewsCategory,
        max_articles: int = 20,
    ) -> List[RawArticle]:
        """
        Fetch articles for a fixed category (INTERNATIONAL / FINANCIAL / TECH).
        Combines results from all configured RSS sources, deduplicates by URL.
        """
        sources = RSS_SOURCES.get(category, [])
        seen_urls: set = set()
        results: List[RawArticle] = []

        for url in sources:
            if len(results) >= max_articles:
                break
            state = self._source_states.setdefault(url, _SourceState())
            if state.is_disabled():
                logger.info("跳過停用來源: %s", url)
                continue
            try:
                articles = self.fetch_rss(url)
                state.record_success()
                for art in articles:
                    if art.url not in seen_urls and len(results) < max_articles:
                        seen_urls.add(art.url)
                        art.full_text, art.full_text_fetched = self.fetch_full_text(art.url)
                        results.append(art)
            except Exception as exc:
                state.record_failure()
                logger.warning("RSS 來源抓取失敗 %s: %s", url, exc)

        logger.info("分類 %s 取得 %d 篇文章", category.display_name, len(results))
        return results

    def fetch_stock_news(
        self,
        stock_info: StockInfo,
        max_articles: int = 10,
    ) -> Tuple[List[RawArticle], NewsCategory]:
        """
        Fetch news for a specific stock.
        Returns (articles, category) where category is STOCK_TW or STOCK_US.
        """
        if self._is_taiwan_stock(stock_info.stock_id):
            keyword = f"{stock_info.stock_id} {stock_info.stock_name}"
            url = GNEWS_TW_URL.format(keyword=requests.utils.quote(keyword))
            category = NewsCategory.STOCK_TW
        else:
            keyword = stock_info.stock_id
            url = GNEWS_US_URL.format(keyword=requests.utils.quote(keyword))
            category = NewsCategory.STOCK_US

        state = self._source_states.setdefault(url, _SourceState())
        if state.is_disabled():
            logger.info("個股來源停用中，跳過 %s", stock_info.stock_id)
            return [], category

        try:
            articles = self.fetch_rss(url)
            state.record_success()
            results = []
            for art in articles[:max_articles]:
                art.full_text, art.full_text_fetched = self.fetch_full_text(art.url)
                results.append(art)
            return results, category
        except Exception as exc:
            state.record_failure()
            logger.warning("個股新聞抓取失敗 %s: %s", stock_info.stock_id, exc)
            return [], category

    def fetch_rss(self, url: str) -> List[RawArticle]:
        """Parse an RSS/Atom feed URL and return list of RawArticle."""
        self._rate_limit(url)
        try:
            resp = self._session.get(url, timeout=self._config.news_request_timeout)
            resp.raise_for_status()
            feed = atoma.parse_rss_bytes(resp.content)
            articles = []
            for item in feed.items:
                pub = item.pub_date or datetime.now(tz=TW_TIMEZONE)
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=TW_TIMEZONE)
                link = item.link or ""
                excerpt = ""
                if item.description:
                    # Strip HTML tags from description
                    soup = BeautifulSoup(item.description, "lxml")
                    excerpt = soup.get_text(separator=" ", strip=True)[:500]
                source = urlparse(link).netloc or url
                articles.append(RawArticle(
                    title=item.title or "",
                    url=link,
                    source=source,
                    published_at=pub,
                    excerpt=excerpt,
                ))
            return articles
        except atoma.exceptions.FeedXMLError:
            # Try Atom format
            try:
                self._rate_limit(url)
                resp = self._session.get(url, timeout=self._config.news_request_timeout)
                feed = atoma.parse_atom_bytes(resp.content)
                articles = []
                for entry in feed.entries:
                    pub = entry.published or entry.updated or datetime.now(tz=TW_TIMEZONE)
                    if pub.tzinfo is None:
                        pub = pub.replace(tzinfo=TW_TIMEZONE)
                    link = entry.links[0].href if entry.links else ""
                    source = urlparse(link).netloc or url
                    articles.append(RawArticle(
                        title=entry.title.value if entry.title else "",
                        url=link,
                        source=source,
                        published_at=pub,
                        excerpt="",
                    ))
                return articles
            except Exception as exc:
                raise RuntimeError(f"RSS/Atom 解析失敗: {exc}") from exc

    def fetch_full_text(self, url: str) -> Tuple[str, bool]:
        """
        Fetch full article text from URL.
        Returns (text, success). On failure returns ("", False).
        """
        if not url:
            return "", False
        try:
            self._rate_limit(url)
            resp = self._session.get(
                url,
                timeout=self._config.news_request_timeout,
                allow_redirects=True,
            )
            resp.raise_for_status()
            text = self._extract_text_from_html(resp.text)
            if len(text) < 100:
                return "", False
            return text, True
        except Exception as exc:
            logger.debug("全文抓取失敗 %s: %s", url, exc)
            return "", False

    # ── 私有方法 ──────────────────────────────────────────────────────────────

    def _is_taiwan_stock(self, stock_id: str) -> bool:
        """Pure digits → Taiwan stock; contains letters → US stock."""
        return stock_id.isdigit()

    def _extract_text_from_html(self, html: str) -> str:
        """Extract main body text using BeautifulSoup, filtering noise tags."""
        soup = BeautifulSoup(html, "lxml")
        for tag in soup.find_all(_EXCLUDE_TAGS):
            tag.decompose()
        paragraphs = soup.find_all("p")
        text = " ".join(p.get_text(separator=" ", strip=True) for p in paragraphs)
        return text[:8000]  # cap at 8000 chars to keep token usage reasonable

    def _rate_limit(self, url: str) -> None:
        """Enforce minimum 2-second interval between requests to the same domain."""
        domain = urlparse(url).netloc
        last = self._domain_last_request.get(domain, 0.0)
        elapsed = time.monotonic() - last
        wait = self._config.news_request_interval - elapsed
        if wait > 0:
            time.sleep(wait)
        self._domain_last_request[domain] = time.monotonic()
