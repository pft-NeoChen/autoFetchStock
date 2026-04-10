"""
News summarizer for autoFetchStock news submodule.

Uses Gemini API (google-genai SDK) to:
- Translate + summarize each article to Traditional Chinese (≤200 chars)
- Tag related stock IDs from the favorites list
- Generate category-level summaries (≤500 chars)

Fallback: when news_summarizer_backend == "gemini-cli", uses subprocess.
"""

import json
import logging
import os
import subprocess
import tempfile
from typing import List, Optional, Tuple

from src.config import AppConfig
from src.exceptions import SummarizationError
from src.models import StockInfo
from src.news.news_fetcher import RawArticle
from src.news.news_models import NewsArticle, NewsCategory

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

_MAX_SUMMARY_LEN = 200
_MAX_CATEGORY_SUMMARY_LEN = 500


class NewsSummarizer:
    """Summarizes news articles using Gemini API or gemini-cli subprocess."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._backend = config.news_summarizer_backend
        self._favorites: List[StockInfo] = []
        self._model = None

        if self._backend == "gemini":
            self._init_sdk()

    def _init_sdk(self) -> None:
        """Initialize google-genai SDK client."""
        try:
            import google.genai as genai
            self._client = genai.Client(api_key=self._config.gemini_api_key)
            self._model_name = "gemini-2.0-flash"
            logger.info("Gemini SDK 初始化完成（model: %s）", self._model_name)
        except Exception as exc:
            raise SummarizationError(
                message="Gemini SDK 初始化失敗",
                reason=str(exc),
            ) from exc

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

    # ── 私有方法 ──────────────────────────────────────────────────────────────

    def _call_backend(self, prompt: str) -> str:
        """Route to SDK or CLI backend based on config."""
        if self._backend == "gemini-cli":
            return self._call_cli(prompt)
        return self._call_sdk(prompt)

    def _call_sdk(self, prompt: str) -> str:
        """Call Gemini API via google-genai SDK."""
        import google.genai as genai
        response = self._client.models.generate_content(
            model=self._model_name,
            contents=prompt,
        )
        return response.text or ""

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
