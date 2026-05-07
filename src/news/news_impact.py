"""
News impact scoring — Phase 4 (Variant N2).

Pure-rule heuristic that assigns each `NewsArticle` an impact_score in [0, 10]
and an impact_direction in {"up", "down", "neutral"}.

Designed to be deterministic, side-effect free, and cheap (no LLM call).
Phase 6 may swap this with an LLM-driven sentiment scorer; the public
contract `score_news(article) -> (score, direction)` will remain stable.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Tuple

from src.news.news_models import NewsArticle, NewsCategory

logger = logging.getLogger("autofetchstock.news.impact")


# ── Keyword tiers (matched in title + summary, case-insensitive substring) ──

_TIER1_KEYWORDS = (
    "下修", "重訊", "停牌", "召回", "管制", "調查", "資安",
    "跳空", "漲停", "跌停", "違約", "破產", "下市", "違反",
)
_TIER2_KEYWORDS = (
    "目標價", "上修", "法說", "併購", "分拆", "新訂單", "減產", "擴產",
    "利空", "利多", "獲利", "虧損", "庫存", "出貨",
)
_TIER3_KEYWORDS = (
    "財報", "EPS", "毛利率", "產能", "關稅", "匯率", "升息", "降息",
    "營收", "訂單", "投資", "庫藏股", "配息",
)

_TIER1_WEIGHT = 3.0
_TIER2_WEIGHT = 2.0
_TIER3_WEIGHT = 1.0
_KEYWORD_CAP = 6.0


# ── Direction polarity word lists ───────────────────────────────────────────

_BULLISH_WORDS = (
    "上修", "利多", "獲利", "成長", "創高", "突破", "新訂單", "擴產",
    "漲停", "回升", "增持", "看好", "目標價", "受惠", "受益",
)
_BEARISH_WORDS = (
    "下修", "利空", "虧損", "衰退", "重訊", "停牌", "召回", "管制",
    "調查", "跌停", "違約", "破產", "下市", "減產", "庫存", "下修",
    "資安", "違反", "罰", "失利",
)


def _keyword_score(text: str) -> float:
    """Sum tier weights for matched keywords; cap at _KEYWORD_CAP."""
    score = 0.0
    for kw in _TIER1_KEYWORDS:
        if kw in text:
            score += _TIER1_WEIGHT
    for kw in _TIER2_KEYWORDS:
        if kw in text:
            score += _TIER2_WEIGHT
    for kw in _TIER3_KEYWORDS:
        if kw in text:
            score += _TIER3_WEIGHT
    return min(score, _KEYWORD_CAP)


def _recency_bonus(published_at: datetime, now: datetime) -> float:
    """Linear decay 2.0 (now) → 0.0 (24h+). Negative ages clipped to fresh."""
    pub = published_at
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=timezone.utc)
    cur = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (cur - pub).total_seconds() / 3600.0)
    if age_hours >= 24.0:
        return 0.0
    return 2.0 * (1.0 - age_hours / 24.0)


def _category_bonus(category: NewsCategory) -> float:
    if category in (NewsCategory.FINANCIAL, NewsCategory.STOCK_TW):
        return 1.0
    if category == NewsCategory.STOCK_US:
        return 0.5
    return 0.0


def _direction(text: str) -> str:
    """Majority-vote on bullish vs bearish word count."""
    bull = sum(1 for w in _BULLISH_WORDS if w in text)
    bear = sum(1 for w in _BEARISH_WORDS if w in text)
    if bull == 0 and bear == 0:
        return "neutral"
    if bull > bear:
        return "up"
    if bear > bull:
        return "down"
    return "neutral"


def score_news(
    article: NewsArticle,
    now: datetime | None = None,
) -> Tuple[float, str]:
    """Compute impact score (0-10) and direction for a single article.

    Args:
        article: NewsArticle to score.
        now: Reference time for recency decay. Defaults to current UTC time.

    Returns:
        (score, direction) tuple. Score is rounded to 1 decimal.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    text = f"{article.title} {article.summary} {article.excerpt}"

    score = (
        _keyword_score(text)
        + _recency_bonus(article.published_at, now)
        + (1.0 if article.related_stock_ids else 0.0)
        + _category_bonus(article.category)
    )
    score = max(0.0, min(10.0, score))
    direction = _direction(text)
    return round(score, 1), direction


def annotate_article(article: NewsArticle, now: datetime | None = None) -> None:
    """Mutate article in place, setting impact_score and impact_direction."""
    score, direction = score_news(article, now=now)
    article.impact_score = score
    article.impact_direction = direction
