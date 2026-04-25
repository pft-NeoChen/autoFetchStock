"""
News summarizer for autoFetchStock news submodule.

Uses Gemini API (google-genai SDK) to:
- Translate + summarize each article to Traditional Chinese (≤200 chars)
- Tag related stock IDs from the favorites list
- Generate category-level summaries (≤500 chars)

Fallback: when news_summarizer_backend == "gemini-cli", uses subprocess.
"""

import json
import hashlib
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

from src.config import AppConfig
from src.exceptions import SummarizationError
from src.models import StockInfo
from src.news.news_fetcher import RawArticle
from src.news.news_models import (
    CategoryHighlight,
    EventCluster,
    FavoriteSignal,
    GlobalBrief,
    NewsArticle,
    NewsCategory,
    SectorHeat,
)

logger = logging.getLogger("autofetchstock.news.summarizer")

# ── Prompt 模板 ───────────────────────────────────────────────────────────────

_ARTICLE_PROMPT = """\
你是一位專業財經新聞編輯。請根據以下新聞內容完成兩件事：

1. 將新聞摘要成繁體中文，字數不超過 200 字，重點包含：事件、影響、數據。
2. 從以下股票清單中，判斷哪些股票與此新聞有直接或間接關聯，列出股票代號（無關聯則回傳空列表）。

股票清單（代號: 名稱）：
{stock_list}

新聞標題：{title}
新聞內容：
{content}

請以下列 JSON 格式回應，不要包含其他文字：
{{"summary": "繁體中文摘要...", "related_stock_ids": ["2330", "NVDA"]}}
"""

_CATEGORY_PROMPT = """\
你是一位專業財經新聞編輯。以下是今日「{category_name}」類別的新聞摘要列表，
請整合重點，撰寫一段不超過 500 字的繁體中文總結，涵蓋最重要的趨勢與事件。

各篇摘要：
{summaries}

請直接回應繁體中文總結內容，不需要加標題或格式標記。
"""

_GLOBAL_BRIEF_PROMPT = """\
你是一位資深財經新聞主編。以下是今日從多來源收集的新聞（每則含標題、來源與 excerpt）。
請完成以下任務，全部用繁體中文回應：

1. 寫出「今日重點總結」（不超過 300 字），扼要點出今天全球最重要的事件與其交互影響。
2. 各分類的「重點條列」：**只要某分類在下方「各分類新聞」段落中有出現**，就必須為它產出一組 highlight，
   每個分類列 3~5 條短句，每條不超過 40 字。分類代碼僅能使用：
   INTERNATIONAL（國際）、FINANCIAL（財經）、TECH（科技）、STOCK_TW（台股個股）、STOCK_US（美股個股）。
   若某分類完全沒有新聞則可省略；不要捏造未出現的分類。
3. 給出一個市場情緒分數（0~100 整數）：0=極度恐慌、50=中性、100=極度樂觀，並附上一句話理由。
4. 板塊熱度排名（sector_heats）：判斷今日新聞中以下基礎板塊的熱度，必須產出全部 5 個基礎板塊：
   「AI」、「半導體」、「電動車」、「金融」、「傳產」。
   若新聞中還有其他明顯熱門的板塊（如「軍工」、「生技」、「航運」等），可額外加入最多 2 個。
   每個板塊輸出：
   - heat_score（0~100 整數）：依據相關新聞數量、事件強度、市場關注度給分
   - trend："up"（多空偏多/題材發酵）、"down"（利空/降溫）、"flat"（中性/無明顯方向）
   - summary：一句話（≤80 字）說明為何給此分數
   - referenced_urls：最多 3 個支撐判斷的新聞 URL；若該板塊今日無相關新聞，referenced_urls 留空陣列、
     heat_score 給 30 以下、trend 給 "flat"、summary 寫「今日無相關新聞」。

---

各分類新聞：
{sections}

---

請嚴格以下列 JSON 格式回應（不要加 markdown 程式碼框、不要加其他文字）：
{{
  "overall_summary": "今日重點總結...",
  "category_highlights": [
    {{"category": "INTERNATIONAL", "headline_points": ["要點1", "要點2", "要點3"]}},
    {{"category": "FINANCIAL", "headline_points": ["...", "...", "..."]}},
    {{"category": "TECH", "headline_points": ["...", "...", "..."]}},
    {{"category": "STOCK_TW", "headline_points": ["...", "...", "..."]}},
    {{"category": "STOCK_US", "headline_points": ["...", "...", "..."]}}
  ],
  "market_sentiment": 55,
  "sentiment_reason": "一句話理由",
  "sector_heats": [
    {{"sector": "AI", "heat_score": 80, "trend": "up", "summary": "...", "referenced_urls": ["..."]}},
    {{"sector": "半導體", "heat_score": 75, "trend": "up", "summary": "...", "referenced_urls": ["..."]}},
    {{"sector": "電動車", "heat_score": 50, "trend": "flat", "summary": "...", "referenced_urls": []}},
    {{"sector": "金融", "heat_score": 40, "trend": "down", "summary": "...", "referenced_urls": ["..."]}},
    {{"sector": "傳產", "heat_score": 30, "trend": "flat", "summary": "...", "referenced_urls": []}}
  ]
}}
"""

_FAVORITES_IMPACT_PROMPT = """\
你是一位專業投資分析師。以下是今日收集的所有新聞（每則含標題、來源、URL、excerpt），
以及使用者關注的個股清單。請針對每一檔關注個股，判斷今日新聞對它可能造成的影響。

---

使用者關注個股清單：
{favorites}

---

今日新聞：
{articles}

---

對每一檔個股產出一個判斷，訊號僅能用以下三種之一：
- "bullish"（利多）：新聞對此股有明顯正面影響
- "bearish"（利空）：新聞對此股有明顯負面影響
- "neutral"（中性）：無明顯關聯或影響有限

判斷必須遵守以下中立性護欄（任一不符合一律降為 "neutral"）：
1. 「無相關」是合法答案：若今日新聞與此股完全無直接或間接關聯，必須回 "neutral"，
   reason 寫「今日新聞無明顯關聯」、referenced_urls 留空陣列。不要為了給答案而硬找關聯。
2. 證據強度：bullish 或 bearish 必須有 ≥ 2 篇來源不同（source 不同）的新聞支持；
   只有 1 篇或多篇同來源轉載，必須降為 "neutral"。
3. 雙面論證：reason 須先簡述支持訊號的證據，若有反向證據也須提及；
   找不到反向證據時可寫「未見明顯反向訊息」。整段仍限 ≤ 120 字。
4. referenced_urls：bullish/bearish 至少引用 2 個不同 source 的 URL（最多 3 個）；
   neutral 可留空或最多 1 個。

請嚴格以下列 JSON 格式回應（陣列順序與個股清單一致，不要加 markdown 程式碼框、不要加其他文字）：
{{
  "signals": [
    {{
      "stock_id": "2330",
      "signal": "bullish",
      "reason": "一句話理由（≤120 字）",
      "referenced_urls": ["支撐判斷的新聞 URL（最多 3 個）"]
    }}
  ]
}}
"""

_TAG_BATCH_SIZE = 40

_TAG_ARTICLES_PROMPT = """\
你是新聞關聯標籤助手。給定一批新聞與使用者自選股清單，請判斷每則新聞與哪些自選股有
直接或間接關聯，並標註該關聯的極性。

判斷範圍包含：
- 直接：新聞明確提到此股代號 / 公司名 / 主要產品
- 間接：同產業趨勢、上下游供應鏈、主要客戶或競爭對手、總體經濟對該股的影響、
  政策法規對該股所在產業的影響等

極性定義：
- "bullish"：對此股有正面影響
- "bearish"：對此股有負面影響
- "neutral"：相關但影響不明 / 中性報導

---

自選股清單：
{favorites}

---

新聞列表（含 URL）：
{articles}

---

請嚴格以下列 JSON 格式回應（不要加 markdown 程式碼框、不要加其他文字）：
{{
  "items": [
    {{"url": "https://...", "impacts": [
      {{"stock_id": "2330", "polarity": "bullish"}},
      {{"stock_id": "AAPL", "polarity": "neutral"}}
    ]}}
  ]
}}

規則：
- 一則新聞可同時關聯多檔股票，極性可不同
- 若新聞與所有自選股皆無關聯，impacts 為空陣列
- stock_id 必須來自上方清單，不要捏造
- 寧缺勿濫：找不到合理依據時不要硬標
"""

_FAVORITES_IMPACT_V2_PROMPT = """\
你是一位專業投資分析師。以下是今日針對使用者自選股**逐檔預先篩選並做極性標註**的相關新聞證據。
請根據每檔股票自己的證據區塊，產出該股的最終訊號與理由。

訊號僅能使用 "bullish" / "bearish" / "neutral"。
中立性護欄（任一不符合一律降為 neutral）：
1. 「無相關」是合法答案：若該股的證據區塊為「無」或所有新聞皆無實質影響，回 neutral，
   reason 寫「今日新聞無明顯關聯」、referenced_urls 留空陣列。不要為了給答案而硬找關聯。
2. 證據強度：bullish 或 bearish 必須有 ≥ 2 篇來源不同（source 不同）的新聞支持；
   只有 1 篇或多篇同來源轉載，必須降為 "neutral"。
3. 雙面論證：reason 須先簡述支持訊號的證據，若有反向證據也須提及；
   找不到反向證據時可寫「未見明顯反向訊息」。整段仍限 ≤ 120 字。
4. referenced_urls：bullish/bearish 至少引用 2 個不同 source 的 URL（最多 3 個）；
   neutral 可留空或最多 1 個。
5. 預先標註的極性僅供參考，你應自行檢視證據後判斷最終訊號。

---

各自選股證據區塊：
{evidence_blocks}

---

請嚴格以下列 JSON 格式回應（陣列順序與證據區塊一致，不要加 markdown 程式碼框、不要加其他文字）：
{{
  "signals": [
    {{
      "stock_id": "2330",
      "signal": "bullish",
      "reason": "一句話理由（≤120 字），含正反證據說明",
      "referenced_urls": ["..."]
    }}
  ]
}}
"""

_EVENT_CLUSTER_PROMPT = """\
你是一位財經新聞事件分析師。以下是過去 {window_days} 日的去重新聞清單。
請把這些新聞聚類成「同一議題跨日演進」事件。

規則：
- 最多輸出 50 個事件，優先保留與市場、產業、股市、重大政策相關的事件
- 每個事件必須引用至少 1 個下方新聞 URL
- article_urls 只能使用下方輸入中存在的 URL，不要捏造 URL
- keywords 請給 2~6 個短詞，用於事件跨日追蹤
- sectors 可填 AI、半導體、電動車、金融、傳產、能源、航運、生技等，沒有則空陣列
- related_stock_ids 只能使用新聞中出現的 related_stock_ids，沒有則空陣列

新聞清單：
{articles}

請嚴格以下列 JSON 格式回應（不要加 markdown 程式碼框、不要加其他文字）：
{{
  "clusters": [
    {{
      "title": "事件標題",
      "summary": "事件摘要（≤120 字）",
      "keywords": ["關鍵詞1", "關鍵詞2"],
      "article_urls": ["https://..."],
      "sectors": ["半導體"],
      "related_stock_ids": ["2330"]
    }}
  ]
}}
"""

_MAX_SUMMARY_LEN = 200
_MAX_CATEGORY_SUMMARY_LEN = 500
_MAX_EVENT_CLUSTER_INPUT_ARTICLES = 800
_MAX_EVENT_CLUSTERS = 50


@dataclass
class ArticleTag:
    """Stage 1 output: per-(article, stock) impact tag."""
    url: str
    stock_id: str
    polarity: str  # "bullish" | "bearish" | "neutral"

# Free-tier gemini-3.1-flash-lite 速率限制：15 RPM
# 保留 1 個 buffer 避免邊界 race，用 14 RPM。
_SDK_RPM_LIMIT = 14
_SDK_WINDOW_SECONDS = 60
_SDK_MAX_RETRIES_ON_429 = 2
_RETRY_DELAY_PATTERN = re.compile(r"retry.*?in\s+([\d.]+)s", re.IGNORECASE)


class NewsSummarizer:
    """Summarizes news articles using Gemini API or gemini-cli subprocess."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._backend = config.news_summarizer_backend
        self._favorites: List[StockInfo] = []
        self._client = None
        self._model_name = ""
        self._disabled_reason = ""
        # Sliding window of recent SDK request timestamps for client-side throttling.
        self._sdk_call_times: Deque[float] = deque()
        self._sdk_lock = threading.Lock()

        if self._backend == "gemini":
            self._init_sdk()

    def _init_sdk(self) -> None:
        """Initialize google-genai SDK client."""
        if not self._config.gemini_api_key:
            self._disabled_reason = "GEMINI_API_KEY is not configured"
            logger.warning("Gemini SDK 未啟用: %s", self._disabled_reason)
            return

        try:
            import google.genai as genai
            self._client = genai.Client(api_key=self._config.gemini_api_key)
            self._model_name = "gemini-3.1-flash-lite-preview"
            logger.info("Gemini SDK 初始化完成（model: %s）", self._model_name)
        except Exception as exc:
            self._disabled_reason = str(exc)
            logger.warning("Gemini SDK 初始化失敗，新聞摘要功能將停用: %s", exc)

    def set_favorites(self, favorites: List[StockInfo]) -> None:
        """Set favorites list for stock tagging in each run."""
        self._favorites = favorites

    def summarize_article(self, article: RawArticle) -> Tuple[str, List[str], bool]:
        """
        Translate, summarize, and tag a single article.
        Returns (summary, related_stock_ids, success).
        """
        content = article.full_text if article.full_text_fetched else article.excerpt
        if not content and not article.title:
            return "", [], False

        stock_list = "\n".join(
            f"{s.stock_id}: {s.stock_name}" for s in self._favorites
        ) or "（無）"

        prompt = _ARTICLE_PROMPT.format(
            stock_list=stock_list,
            title=article.title,
            content=content[:5000],  # cap to reduce token cost
        )

        try:
            raw = self._call_backend(prompt)
            return self._parse_article_response(raw)
        except Exception as exc:
            logger.warning("文章摘要失敗 [%s]: %s", article.title[:40], exc)
            return "", [], False

    def summarize_category(
        self,
        articles: List[NewsArticle],
        category: NewsCategory,
    ) -> Tuple[str, bool]:
        """
        Generate a category-level summary from all article summaries.
        Returns (category_summary, success).
        """
        valid = [a for a in articles if a.summary and not a.summary_failed]
        if not valid:
            return "", False

        summaries = "\n".join(
            f"- {a.title}：{a.summary}" for a in valid
        )
        prompt = _CATEGORY_PROMPT.format(
            category_name=category.display_name,
            summaries=summaries[:6000],
        )

        try:
            text = self._call_backend(prompt).strip()
            if len(text) > _MAX_CATEGORY_SUMMARY_LEN:
                text = text[:_MAX_CATEGORY_SUMMARY_LEN]
                logger.debug("分類摘要截斷至 %d 字", _MAX_CATEGORY_SUMMARY_LEN)
            return text, True
        except Exception as exc:
            logger.warning("分類摘要失敗 [%s]: %s", category.display_name, exc)
            return "", False

    # ── Phase 1：聚合分析方法 ────────────────────────────────────────────────

    def summarize_global(
        self,
        articles_by_category: "dict[NewsCategory, List[RawArticle]]",
    ) -> GlobalBrief:
        """
        One-shot aggregate analysis over all today's articles.
        Produces an overall brief, per-category highlights, and a market sentiment score.
        """
        if not any(articles_by_category.values()):
            return GlobalBrief(failed=True, sentiment_reason="無新聞資料")

        sections = self._format_sections(articles_by_category)
        prompt = _GLOBAL_BRIEF_PROMPT.format(sections=sections[:60000])

        try:
            raw = self._call_backend(prompt)
            return self._parse_global_brief_response(raw)
        except Exception as exc:
            logger.warning("全局重點分析失敗: %s", exc)
            return GlobalBrief(failed=True, sentiment_reason=str(exc)[:80])

    def tag_articles(
        self,
        articles: List["RawArticle"],
        favorites: List[StockInfo],
    ) -> List[ArticleTag]:
        """
        Stage 1: classify which favorites each article impacts and the polarity.
        Articles are processed in batches to fit prompt size and RPM budget.
        Returns a flat list of (url, stock_id, polarity) tags.
        """
        if not favorites or not articles:
            return []

        valid_ids = {s.stock_id for s in favorites}
        valid_urls = {a.url for a in articles}
        favorites_block = "\n".join(
            f"- {s.stock_id}: {s.stock_name}" for s in favorites
        )

        all_tags: List[ArticleTag] = []
        total_batches = (len(articles) + _TAG_BATCH_SIZE - 1) // _TAG_BATCH_SIZE
        for idx in range(total_batches):
            batch = articles[idx * _TAG_BATCH_SIZE : (idx + 1) * _TAG_BATCH_SIZE]
            articles_block = self._format_articles_for_tagging(batch)
            prompt = _TAG_ARTICLES_PROMPT.format(
                favorites=favorites_block,
                articles=articles_block[:50000],
            )
            try:
                raw = self._call_backend(prompt)
                tags = self._parse_tag_response(raw, valid_ids, valid_urls)
                all_tags.extend(tags)
                logger.info(
                    "文章標籤批次 %d/%d：%d 篇 → %d 個標籤",
                    idx + 1, total_batches, len(batch), len(tags),
                )
            except Exception as exc:
                logger.warning("文章標籤批次 %d/%d 失敗: %s", idx + 1, total_batches, exc)
        return all_tags

    def analyze_favorites_impact(
        self,
        articles: List["RawArticle"],
        favorites: List[StockInfo],
        tags: Optional[List[ArticleTag]] = None,
    ) -> List[FavoriteSignal]:
        """
        Stage 2: produce a final signal per favorite.
        When `tags` is provided, evidence is segregated per stock so each favorite
        is judged on its own evidence pool (avoids attention-bias toward popular stocks).
        Falls back to the legacy single-prompt design when tags is None or empty.
        """
        if not favorites:
            return []
        if not articles:
            return [
                FavoriteSignal(
                    stock_id=s.stock_id,
                    stock_name=s.stock_name,
                    signal="neutral",
                    reason="今日無相關新聞",
                )
                for s in favorites
            ]

        if tags:
            return self._analyze_with_tags(articles, favorites, tags)

        # Legacy single-prompt path
        favorites_block = "\n".join(
            f"- {s.stock_id}: {s.stock_name}" for s in favorites
        )
        articles_block = self._format_articles_for_impact(articles)
        prompt = _FAVORITES_IMPACT_PROMPT.format(
            favorites=favorites_block,
            articles=articles_block[:60000],
        )

        try:
            raw = self._call_backend(prompt)
            return self._parse_favorites_impact_response(raw, favorites)
        except Exception as exc:
            logger.warning("自選股影響分析失敗: %s", exc)
            return [
                FavoriteSignal(
                    stock_id=s.stock_id,
                    stock_name=s.stock_name,
                    signal="neutral",
                    reason="分析失敗，暫無訊號",
                )
                for s in favorites
            ]

    def _analyze_with_tags(
        self,
        articles: List["RawArticle"],
        favorites: List[StockInfo],
        tags: List[ArticleTag],
    ) -> List[FavoriteSignal]:
        """Stage 2 path that uses pre-segregated evidence per favorite."""
        article_by_url: Dict[str, RawArticle] = {a.url: a for a in articles}
        evidence_by_stock: Dict[str, List[Tuple[RawArticle, str]]] = defaultdict(list)
        seen_pairs: set = set()
        for tag in tags:
            key = (tag.url, tag.stock_id)
            if key in seen_pairs:
                continue
            article = article_by_url.get(tag.url)
            if article is None:
                continue
            seen_pairs.add(key)
            evidence_by_stock[tag.stock_id].append((article, tag.polarity))

        # Stocks with zero evidence → short-circuit to neutral, skip LLM cost.
        stocks_with_evidence = [s for s in favorites if evidence_by_stock.get(s.stock_id)]
        empty_signals = {
            s.stock_id: FavoriteSignal(
                stock_id=s.stock_id,
                stock_name=s.stock_name,
                signal="neutral",
                reason="今日新聞無明顯關聯",
            )
            for s in favorites if not evidence_by_stock.get(s.stock_id)
        }

        if not stocks_with_evidence:
            logger.info("自選股影響分析：所有自選股皆無相關新聞，全部標 neutral")
            return [empty_signals[s.stock_id] for s in favorites]

        evidence_blocks = self._format_evidence_blocks(
            stocks_with_evidence, evidence_by_stock
        )
        prompt = _FAVORITES_IMPACT_V2_PROMPT.format(
            evidence_blocks=evidence_blocks[:60000],
        )

        try:
            raw = self._call_backend(prompt)
            evaluated = self._parse_favorites_impact_response(raw, stocks_with_evidence)
            evaluated_by_id = {sig.stock_id: sig for sig in evaluated}
        except Exception as exc:
            logger.warning("自選股影響分析（V2）失敗: %s", exc)
            evaluated_by_id = {
                s.stock_id: FavoriteSignal(
                    stock_id=s.stock_id,
                    stock_name=s.stock_name,
                    signal="neutral",
                    reason="分析失敗，暫無訊號",
                )
                for s in stocks_with_evidence
            }

        return [
            evaluated_by_id.get(s.stock_id, empty_signals.get(
                s.stock_id,
                FavoriteSignal(
                    stock_id=s.stock_id,
                    stock_name=s.stock_name,
                    signal="neutral",
                    reason="今日新聞無明顯關聯",
                ),
            ))
            for s in favorites
        ]

    # ── Phase 3b：事件聚類 ──────────────────────────────────────────────────

    def cluster_events(
        self,
        articles: List[NewsArticle],
        window_days: int = 7,
    ) -> List[EventCluster]:
        """
        Cluster historical articles into cross-day events with one Gemini call.

        The parser only accepts URLs present in the input and generates event_id
        locally, so LLM output cannot create references to non-existent articles.
        """
        valid_articles = [a for a in articles if a.url and a.title]
        if not valid_articles:
            return []

        valid_articles.sort(key=self._article_sort_key, reverse=True)
        selected = valid_articles[:_MAX_EVENT_CLUSTER_INPUT_ARTICLES]
        articles_block = self._format_articles_for_event_clustering(selected)
        prompt = _EVENT_CLUSTER_PROMPT.format(
            window_days=window_days,
            articles=articles_block[:160000],
        )

        try:
            raw = self._call_backend(prompt)
            return self._parse_event_cluster_response(raw, selected)
        except Exception as exc:
            logger.warning("事件聚類失敗: %s", exc)
            return []

    # ── 私有方法 ──────────────────────────────────────────────────────────────

    def _call_backend(self, prompt: str) -> str:
        """Route to SDK or CLI backend based on config."""
        if self._backend == "gemini-cli":
            return self._call_cli(prompt)
        if self._backend == "gemini":
            return self._call_sdk(prompt)
        raise SummarizationError(
            message="未知的新聞摘要 backend",
            reason=self._backend,
        )

    def _call_sdk(self, prompt: str) -> str:
        """Call Gemini API via google-genai SDK with client-side throttling + 429 retry."""
        if self._client is None:
            raise SummarizationError(
                message="Gemini SDK 不可用",
                reason=self._disabled_reason or "client not initialized",
            )

        attempts = 0
        while True:
            self._throttle_sdk()
            try:
                response = self._client.models.generate_content(
                    model=self._model_name,
                    contents=prompt,
                )
                return response.text or ""
            except Exception as exc:
                if self._is_rate_limit_error(exc) and attempts < _SDK_MAX_RETRIES_ON_429:
                    wait_s = self._extract_retry_delay(exc) or 30.0
                    logger.info("Gemini 429，等待 %.1fs 後重試（第 %d 次）", wait_s, attempts + 1)
                    time.sleep(wait_s + 0.5)
                    attempts += 1
                    continue
                raise

    def _throttle_sdk(self) -> None:
        """Block until next request would fit within the RPM window."""
        with self._sdk_lock:
            now = time.monotonic()
            cutoff = now - _SDK_WINDOW_SECONDS
            while self._sdk_call_times and self._sdk_call_times[0] < cutoff:
                self._sdk_call_times.popleft()
            if len(self._sdk_call_times) >= _SDK_RPM_LIMIT:
                wait_s = _SDK_WINDOW_SECONDS - (now - self._sdk_call_times[0]) + 0.2
                if wait_s > 0:
                    logger.debug("SDK 節流：等待 %.2fs 避開 RPM 上限", wait_s)
                    time.sleep(wait_s)
                    now = time.monotonic()
                    cutoff = now - _SDK_WINDOW_SECONDS
                    while self._sdk_call_times and self._sdk_call_times[0] < cutoff:
                        self._sdk_call_times.popleft()
            self._sdk_call_times.append(now)

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        text = str(exc)
        return "429" in text or "RESOURCE_EXHAUSTED" in text

    @staticmethod
    def _extract_retry_delay(exc: Exception) -> Optional[float]:
        match = _RETRY_DELAY_PATTERN.search(str(exc))
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
        return None

    def _call_cli(self, prompt: str) -> str:
        """
        Call gemini CLI via subprocess (備案 backend).
        Uses a temp file to avoid shell argument length/escape issues.
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(prompt)
            tmp_path = f.name
        try:
            result = subprocess.run(
                ["gemini", "-p", f"@{tmp_path}"],
                capture_output=True,
                text=True,
                timeout=self._config.news_summarizer_timeout,
            )
            if result.returncode != 0:
                raise SummarizationError(
                    message="gemini CLI 執行失敗",
                    reason=result.stderr[:200],
                )
            return result.stdout.strip()
        finally:
            os.unlink(tmp_path)

    def _parse_article_response(
        self, raw: str
    ) -> Tuple[str, List[str], bool]:
        """Parse JSON response from article summarization prompt."""
        raw = raw.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        try:
            data = json.loads(raw)
            summary = str(data.get("summary", "")).strip()
            if len(summary) > _MAX_SUMMARY_LEN:
                summary = summary[:_MAX_SUMMARY_LEN]
                logger.debug("摘要截斷至 %d 字", _MAX_SUMMARY_LEN)
            valid_ids = {s.stock_id for s in self._favorites}
            related = [
                sid for sid in data.get("related_stock_ids", [])
                if sid in valid_ids
            ]
            return summary, related, True
        except (json.JSONDecodeError, KeyError) as exc:
            # Try to extract plain text as summary fallback
            logger.debug("JSON 解析失敗，嘗試純文字 fallback: %s", exc)
            text = raw.strip()[:_MAX_SUMMARY_LEN]
            if text:
                return text, [], True
            return "", [], False

    # ── Phase 1 helper ─────────────────────────────────────────────────────────

    @staticmethod
    def _format_sections(
        articles_by_category: "dict[NewsCategory, List[RawArticle]]",
    ) -> str:
        """Render articles grouped by category for the global-brief prompt."""
        lines: List[str] = []
        for category, arts in articles_by_category.items():
            if not arts:
                continue
            lines.append(f"\n## {category.value} ({category.display_name})")
            for a in arts:
                excerpt = (a.excerpt or a.full_text[:200]).replace("\n", " ").strip()
                lines.append(f"- {a.title} | {a.source} | {excerpt}")
        return "\n".join(lines)

    @staticmethod
    def _format_articles_for_impact(articles: List["RawArticle"]) -> str:
        """Render flat article list for the favorites-impact prompt."""
        lines: List[str] = []
        for a in articles:
            excerpt = (a.excerpt or a.full_text[:200]).replace("\n", " ").strip()
            lines.append(f"- [{a.source}] {a.title}\n  URL: {a.url}\n  {excerpt}")
        return "\n".join(lines)

    @staticmethod
    def _format_articles_for_tagging(articles: List["RawArticle"]) -> str:
        """Render article list for the stage-1 tagging prompt (URL-keyed)."""
        lines: List[str] = []
        for a in articles:
            excerpt = (a.excerpt or a.full_text[:200]).replace("\n", " ").strip()
            lines.append(f"- URL: {a.url}\n  [{a.source}] {a.title}\n  {excerpt}")
        return "\n".join(lines)

    @staticmethod
    def _format_evidence_blocks(
        favorites: List[StockInfo],
        evidence_by_stock: Dict[str, List[Tuple["RawArticle", str]]],
    ) -> str:
        """Render per-stock evidence sections for the V2 favorites-impact prompt."""
        blocks: List[str] = []
        for s in favorites:
            ev = evidence_by_stock.get(s.stock_id, [])
            blocks.append(f"\n=== {s.stock_id} {s.stock_name}（相關新聞 {len(ev)} 篇）===")
            if not ev:
                blocks.append("（無相關新聞）")
                continue
            for art, polarity in ev:
                excerpt = (art.excerpt or art.full_text[:200]).replace("\n", " ").strip()
                blocks.append(
                    f"- [{art.source}] ({polarity}) {art.title}\n"
                    f"  URL: {art.url}\n  {excerpt}"
                )
        return "\n".join(blocks)

    @staticmethod
    def _format_articles_for_event_clustering(articles: List[NewsArticle]) -> str:
        """Render historical articles for the event-clustering prompt."""
        lines: List[str] = []
        for a in articles:
            excerpt = (a.excerpt or a.summary or a.full_text[:200]).replace("\n", " ").strip()
            related = ",".join(a.related_stock_ids) if a.related_stock_ids else "none"
            published_at = a.published_at.isoformat()
            lines.append(
                f"- URL: {a.url}\n"
                f"  published_at: {published_at}\n"
                f"  category: {a.category.value}\n"
                f"  source: {a.source}\n"
                f"  related_stock_ids: {related}\n"
                f"  title: {a.title}\n"
                f"  excerpt: {excerpt}"
            )
        return "\n".join(lines)

    def _parse_tag_response(
        self,
        raw: str,
        valid_ids: set,
        valid_urls: set,
    ) -> List[ArticleTag]:
        """Parse stage-1 tagging JSON response into ArticleTag list."""
        data = self._extract_json_object(raw)
        if data is None:
            logger.warning("文章標籤 JSON 解析失敗，回應前 300 字: %r", raw[:300])
            return []
        items = data.get("items", []) if isinstance(data, dict) else data
        tags: List[ArticleTag] = []
        for item in items:
            url = str(item.get("url", "")).strip()
            if url not in valid_urls:
                continue
            for impact in item.get("impacts", []):
                sid = str(impact.get("stock_id", "")).strip()
                if sid not in valid_ids:
                    continue
                polarity = str(impact.get("polarity", "neutral")).lower()
                if polarity not in ("bullish", "bearish", "neutral"):
                    polarity = "neutral"
                tags.append(ArticleTag(url=url, stock_id=sid, polarity=polarity))
        return tags

    @staticmethod
    def _strip_code_fence(raw: str) -> str:
        raw = raw.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            if len(parts) >= 2:
                raw = parts[1]
                if raw.lstrip().lower().startswith("json"):
                    raw = raw.lstrip()[4:]
        return raw.strip()

    @classmethod
    def _extract_json_object(cls, raw: str) -> Optional[dict]:
        """
        Robustly extract a JSON object/array from an LLM response.

        Handles:
        - direct JSON
        - ```json ... ``` code fences
        - preamble/postamble text around the JSON (locates first { or [ and
          balances brackets to find the matching close)
        Returns None if no parseable JSON object is found.
        """
        candidate = cls._strip_code_fence(raw)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

        for opener, closer in (("{", "}"), ("[", "]")):
            start = candidate.find(opener)
            while start != -1:
                depth = 0
                in_str = False
                esc = False
                for i in range(start, len(candidate)):
                    ch = candidate[i]
                    if in_str:
                        if esc:
                            esc = False
                        elif ch == "\\":
                            esc = True
                        elif ch == '"':
                            in_str = False
                        continue
                    if ch == '"':
                        in_str = True
                    elif ch == opener:
                        depth += 1
                    elif ch == closer:
                        depth -= 1
                        if depth == 0:
                            chunk = candidate[start:i + 1]
                            try:
                                return json.loads(chunk)
                            except json.JSONDecodeError:
                                break
                start = candidate.find(opener, start + 1)
        return None

    def _parse_global_brief_response(self, raw: str) -> GlobalBrief:
        data = self._extract_json_object(raw)
        if data is None:
            logger.warning("全局重點 JSON 解析失敗，回應前 300 字: %r", raw[:300])
            return GlobalBrief(failed=True, sentiment_reason="回應格式錯誤")

        highlights: List[CategoryHighlight] = []
        for h in data.get("category_highlights", []):
            try:
                highlights.append(
                    CategoryHighlight(
                        category=NewsCategory(h["category"]),
                        headline_points=[str(p) for p in h.get("headline_points", [])][:5],
                    )
                )
            except (KeyError, ValueError):
                continue

        sentiment = data.get("market_sentiment", 50)
        try:
            sentiment = max(0, min(100, int(sentiment)))
        except (TypeError, ValueError):
            sentiment = 50

        sectors: List[SectorHeat] = []
        seen_sectors: set = set()
        for s in data.get("sector_heats", []):
            if not isinstance(s, dict):
                continue
            name = str(s.get("sector", "")).strip()
            if not name or name in seen_sectors:
                continue
            seen_sectors.add(name)
            score = s.get("heat_score", 50)
            try:
                score = max(0, min(100, int(score)))
            except (TypeError, ValueError):
                score = 50
            trend = str(s.get("trend", "flat")).lower()
            if trend not in ("up", "down", "flat"):
                trend = "flat"
            sectors.append(SectorHeat(
                sector=name,
                heat_score=score,
                trend=trend,
                summary=str(s.get("summary", "")).strip()[:120],
                referenced_urls=[str(u) for u in s.get("referenced_urls", [])][:3],
            ))

        return GlobalBrief(
            overall_summary=str(data.get("overall_summary", "")).strip()[:600],
            category_highlights=highlights,
            market_sentiment=sentiment,
            sentiment_reason=str(data.get("sentiment_reason", "")).strip()[:120],
            sector_heats=sectors,
            failed=False,
        )

    def _parse_event_cluster_response(
        self,
        raw: str,
        input_articles: List[NewsArticle],
    ) -> List[EventCluster]:
        """Parse event-clustering JSON and discard unsupported URLs."""
        data = self._extract_json_object(raw)
        if data is None:
            logger.warning("事件聚類 JSON 解析失敗，回應前 300 字: %r", raw[:300])
            return []

        if isinstance(data, list):
            entries = data
        else:
            entries = data.get("clusters", [])

        valid_urls = {a.url for a in input_articles}
        valid_stock_ids = {
            sid
            for article in input_articles
            for sid in article.related_stock_ids
        }
        clusters: List[EventCluster] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            urls = []
            for url in entry.get("article_urls", []):
                url = str(url).strip()
                if url in valid_urls and url not in urls:
                    urls.append(url)
            if not urls:
                continue

            keywords = [
                str(k).strip()
                for k in entry.get("keywords", [])
                if str(k).strip()
            ][:6]
            title = str(entry.get("title", "")).strip()
            if not title:
                title = next((a.title for a in input_articles if a.url == urls[0]), "")
            sectors = [
                str(s).strip()
                for s in entry.get("sectors", [])
                if str(s).strip()
            ][:8]
            related_stock_ids = [
                str(s).strip()
                for s in entry.get("related_stock_ids", [])
                if str(s).strip() in valid_stock_ids
            ][:20]
            clusters.append(EventCluster(
                event_id=self._stable_event_id(title, keywords),
                title=title[:80],
                summary=str(entry.get("summary", "")).strip()[:160],
                keywords=keywords,
                article_urls=urls,
                sectors=list(dict.fromkeys(sectors)),
                related_stock_ids=list(dict.fromkeys(related_stock_ids)),
            ))
            if len(clusters) >= _MAX_EVENT_CLUSTERS:
                break
        return clusters

    @staticmethod
    def _stable_event_id(title: str, keywords: List[str]) -> str:
        normalized = NewsSummarizer._normalize_event_text(title)
        keyword_part = "|".join(
            sorted(NewsSummarizer._normalize_event_text(k) for k in keywords if k)
        )
        digest = hashlib.sha1(f"{keyword_part}|{normalized}".encode("utf-8")).hexdigest()
        return digest[:12]

    @staticmethod
    def _normalize_event_text(text: str) -> str:
        return re.sub(r"\s+", "", str(text).lower())

    @staticmethod
    def _article_sort_key(article: NewsArticle) -> str:
        return article.published_at.isoformat()

    def _parse_favorites_impact_response(
        self,
        raw: str,
        favorites: List[StockInfo],
    ) -> List[FavoriteSignal]:
        fav_map = {s.stock_id: s for s in favorites}
        data = self._extract_json_object(raw)
        if data is None:
            logger.warning("自選股影響 JSON 解析失敗，回應前 300 字: %r", raw[:300])
            return [
                FavoriteSignal(
                    stock_id=s.stock_id,
                    stock_name=s.stock_name,
                    signal="neutral",
                    reason="回應格式錯誤",
                )
                for s in favorites
            ]

        # Tolerate responses that drop the "signals" wrapper (a top-level array).
        if isinstance(data, list):
            entries = data
        else:
            entries = data.get("signals", [])

        by_id: dict = {}
        for entry in entries:
            sid = str(entry.get("stock_id", "")).strip()
            if sid not in fav_map:
                continue
            signal = str(entry.get("signal", "neutral")).lower()
            if signal not in ("bullish", "bearish", "neutral"):
                signal = "neutral"
            urls = [str(u) for u in entry.get("referenced_urls", [])][:3]
            by_id[sid] = FavoriteSignal(
                stock_id=sid,
                stock_name=fav_map[sid].stock_name,
                signal=signal,
                reason=str(entry.get("reason", "")).strip()[:120],
                referenced_urls=urls,
            )

        # 確保每檔自選股都有一筆結果（順序與輸入一致）
        return [
            by_id.get(
                s.stock_id,
                FavoriteSignal(
                    stock_id=s.stock_id,
                    stock_name=s.stock_name,
                    signal="neutral",
                    reason="今日無明顯相關新聞",
                ),
            )
            for s in favorites
        ]
