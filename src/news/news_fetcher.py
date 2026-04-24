"""
News fetcher for autoFetchStock news submodule.

Handles:
- RSS feed parsing via atoma with stdlib XML fallback
- Full-text article fetching via BeautifulSoup with regex fallback
- Per-category and per-stock news collection
- Rate limiting (2s per domain) and source disabling (3 failures → 24h pause)
"""

import html
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

try:
    import atoma
except ImportError:
    atoma = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from src.config import AppConfig
from src.models import StockInfo
from src.news.news_models import NewsCategory

logger = logging.getLogger("autofetchstock.news.fetcher")

TW_TIMEZONE = ZoneInfo("Asia/Taipei")

# ── RSS 來源設定 ─────────────────────────────────────────────────────────────

RSS_SOURCES: Dict[NewsCategory, List[str]] = {
    NewsCategory.INTERNATIONAL: [
        "https://news.google.com/rss/headlines/section/topic/WORLD?hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
        "https://feeds.bbci.co.uk/news/world/rss.xml",
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
        resp = self._session.get(url, timeout=self._config.news_request_timeout)
        resp.raise_for_status()
        return self._parse_feed(resp.content, url)

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

    def _parse_feed(self, content: bytes, source_url: str) -> List[RawArticle]:
        """Parse feed bytes using atoma when available, otherwise stdlib XML."""
        if atoma is not None:
            try:
                return self._parse_feed_with_atoma(content, source_url)
            except Exception as exc:
                logger.debug("atoma 解析失敗，改用內建 XML parser [%s]: %s", source_url, exc)
        return self._parse_feed_with_stdlib(content, source_url)

    def _parse_feed_with_atoma(self, content: bytes, source_url: str) -> List[RawArticle]:
        """Parse RSS/Atom feed bytes via atoma."""
        try:
            feed = atoma.parse_rss_bytes(content)
            return [
                self._build_article(
                    title=item.title or "",
                    link=item.link or "",
                    published_at=item.pub_date,
                    excerpt=item.description or "",
                    fallback_source=source_url,
                )
                for item in feed.items
            ]
        except atoma.exceptions.FeedXMLError:
            try:
                feed = atoma.parse_atom_bytes(content)
                return [
                    self._build_article(
                        title=entry.title.value if entry.title else "",
                        link=entry.links[0].href if entry.links else "",
                        published_at=entry.published or entry.updated,
                        excerpt="",
                        fallback_source=source_url,
                    )
                    for entry in feed.entries
                ]
            except Exception as exc:
                raise RuntimeError(f"RSS/Atom 解析失敗: {exc}") from exc

    def _parse_feed_with_stdlib(self, content: bytes, source_url: str) -> List[RawArticle]:
        """Parse RSS/Atom feed bytes via the Python standard library."""
        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            raise RuntimeError(f"RSS/Atom 解析失敗: {exc}") from exc

        root_tag = self._local_name(root.tag)
        if root_tag == "rss":
            return self._parse_rss_xml(root, source_url)
        if root_tag == "feed":
            return self._parse_atom_xml(root, source_url)
        raise RuntimeError(f"不支援的 feed 格式: {root.tag}")

    def _parse_rss_xml(self, root: ET.Element, source_url: str) -> List[RawArticle]:
        """Parse RSS 2.0 XML into article models."""
        channel = next(
            (child for child in root if self._local_name(child.tag) == "channel"),
            None,
        )
        if channel is None:
            return []

        articles = []
        for item in channel:
            if self._local_name(item.tag) != "item":
                continue
            articles.append(self._build_article(
                title=self._first_child_text(item, "title"),
                link=self._first_child_text(item, "link"),
                published_at=self._parse_datetime(self._first_child_text(item, "pubDate")),
                excerpt=self._first_child_text(item, "description"),
                fallback_source=source_url,
            ))
        return articles

    def _parse_atom_xml(self, root: ET.Element, source_url: str) -> List[RawArticle]:
        """Parse Atom XML into article models."""
        articles = []
        for entry in root:
            if self._local_name(entry.tag) != "entry":
                continue
            articles.append(self._build_article(
                title=self._first_child_text(entry, "title"),
                link=self._first_link(entry),
                published_at=self._parse_datetime(
                    self._first_child_text(entry, "published", "updated")
                ),
                excerpt=self._first_child_text(entry, "summary", "content"),
                fallback_source=source_url,
            ))
        return articles

    def _build_article(
        self,
        title: str,
        link: str,
        published_at: Optional[datetime],
        excerpt: str,
        fallback_source: str,
    ) -> RawArticle:
        """Normalize parsed feed fields into a RawArticle."""
        pub = published_at or datetime.now(tz=TW_TIMEZONE)
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=TW_TIMEZONE)
        return RawArticle(
            title=title,
            url=link,
            source=urlparse(link).netloc or fallback_source,
            published_at=pub,
            excerpt=self._strip_html(excerpt)[:500],
        )

    def _parse_datetime(self, value: str) -> datetime:
        """Parse RSS pubDate or Atom timestamp into a timezone-aware datetime."""
        value = value.strip()
        if not value:
            return datetime.now(tz=TW_TIMEZONE)

        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError, OverflowError):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return datetime.now(tz=TW_TIMEZONE)

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TW_TIMEZONE)
        return parsed

    def _first_child_text(self, element: ET.Element, *names: str) -> str:
        """Return the text content of the first direct child with any matching local name."""
        for child in element:
            if self._local_name(child.tag) in names:
                return "".join(child.itertext()).strip()
        return ""

    def _first_link(self, element: ET.Element) -> str:
        """Extract the first usable link from an Atom entry."""
        for child in element:
            if self._local_name(child.tag) != "link":
                continue
            href = (child.attrib.get("href") or "").strip()
            if href:
                return href
            text = "".join(child.itertext()).strip()
            if text:
                return text
        return ""

    def _local_name(self, tag: str) -> str:
        """Strip XML namespaces from a tag name."""
        return tag.rsplit("}", 1)[-1]

    def _strip_html(self, text: str) -> str:
        """Convert small HTML fragments into plain text."""
        if not text:
            return ""

        if BeautifulSoup is not None:
            try:
                soup = BeautifulSoup(text, "lxml")
            except Exception:
                soup = BeautifulSoup(text, "html.parser")
            return soup.get_text(separator=" ", strip=True)

        text = re.sub(r"<[^>]+>", " ", text)
        return " ".join(html.unescape(text).split())

    def _is_taiwan_stock(self, stock_id: str) -> bool:
        """Pure digits → Taiwan stock; contains letters → US stock."""
        return stock_id.isdigit()

    def _extract_text_from_html(self, html_content: str) -> str:
        """Extract main body text using BeautifulSoup, filtering noise tags."""
        if BeautifulSoup is not None:
            try:
                soup = BeautifulSoup(html_content, "lxml")
            except Exception:
                soup = BeautifulSoup(html_content, "html.parser")
            for tag in soup.find_all(_EXCLUDE_TAGS):
                tag.decompose()
            paragraphs = soup.find_all("p")
            text = " ".join(p.get_text(separator=" ", strip=True) for p in paragraphs)
            return text[:8000]  # cap at 8000 chars to keep token usage reasonable

        cleaned = html_content
        for tag in _EXCLUDE_TAGS:
            cleaned = re.sub(
                rf"<{tag}\b[^>]*>.*?</{tag}>",
                " ",
                cleaned,
                flags=re.IGNORECASE | re.DOTALL,
            )

        paragraphs = re.findall(
            r"<p\b[^>]*>(.*?)</p>",
            cleaned,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if paragraphs:
            text = " ".join(self._strip_html(fragment) for fragment in paragraphs)
        else:
            text = self._strip_html(cleaned)
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
