"""Phase 6 — per-stock event timeline (Variant N1) data layer.

Builds ``StockEvent`` rows for one stock from the existing
``NewsEventFile`` clusters produced by ``news_processor``.

Two improvements vs the initial Phase 6.4 stub:
1. Cluster ``kind`` is classified by a keyword heuristic against the
   7-class taxonomy in DESIGN_SPEC §4.2 (price / inst / fund / macro /
   tech / ai / news).
2. Each event hydrates its article list (time / title / source / impact)
   from a caller-supplied URL → article meta map so the UI can mimic the
   news-variants.jsx mock.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from src.models import StockEvent


# Keyword rules for kind classification. Order matters — first-match wins,
# so place more specific buckets (macro, inst, fund) before broader ones
# (ai, news). All matching is case-insensitive substring on title +
# keywords combined.
_KIND_RULES: List[Tuple[str, Sequence[str]]] = [
    ("macro", (
        "Fed", "聯準會", "通膨", "CPI", "升息", "降息", "美元",
        "匯率", "關稅", "OPEC", "原油", "FOMC", "GDP", "失業率",
    )),
    ("inst", (
        "外資", "投信", "自營", "三大法人", "買超", "賣超",
        "融資", "融券", "大戶", "處置", "警示",
    )),
    ("fund", (
        "EPS", "營收", "毛利", "法說", "財報", "營業利益",
        "季報", "年報", "股利", "獲利", "營益",
    )),
    ("price", (
        "漲停", "跌停", "跳空", "重挫", "暴漲", "跌深",
        "創高", "創低", "新高", "新低",
    )),
    ("tech", (
        "突破", "跌破", "均線", "KD", "RSI", "MACD", "技術線",
        "黃金交叉", "死亡交叉", "壓力", "支撐",
    )),
    ("ai", (
        "AI", "人工智慧", "CoWoS", "HBM", "GPU", "算力",
        "訓練模型", "推論", "大型語言模型", "LLM",
    )),
]


def classify_event_kind(title: str, keywords: Sequence[str]) -> str:
    """Pick a 7-class kind for one cluster. Falls back to 'news'."""
    text = (title or "") + " " + " ".join(keywords or [])
    text_lower = text.lower()
    for kind, kws in _KIND_RULES:
        for kw in kws:
            if kw.lower() in text_lower:
                return kind
    return "news"


def build_stock_event_timeline(
    stock_id: Optional[str],
    event_data: Optional[dict],
    *,
    window_days: int = 7,
    articles_by_url: Optional[Dict[str, dict]] = None,
) -> List[StockEvent]:
    """Filter NewsEventFile clusters down to one stock's recent events.

    ``articles_by_url`` is an optional URL → article-meta lookup; when
    provided, each event hydrates an ``articles`` list with time / title /
    source / impact fields used by the renderer.
    """
    if not stock_id or not event_data:
        return []

    clusters = event_data.get("clusters") or []
    cutoff = date.today() - timedelta(days=window_days)
    article_map = articles_by_url or {}

    out: List[StockEvent] = []
    for c in clusters:
        related = c.get("related_stock_ids") or []
        if stock_id not in related:
            continue

        last_seen = _parse_date(c.get("last_seen"))
        if last_seen is None or last_seen < cutoff:
            continue

        urls = list(c.get("article_urls") or [])
        kind = classify_event_kind(c.get("title", ""), c.get("keywords") or [])

        # Cluster URLs include every article in the topical cluster, but
        # not every article necessarily mentions this stock — keep only
        # those whose ``related_stock_ids`` contain ``stock_id`` so the
        # inline news list doesn't surface unrelated headlines.
        relevant_urls: List[str] = []
        for url in urls:
            meta = article_map.get(url) or {}
            if stock_id in (meta.get("related_stock_ids") or []):
                relevant_urls.append(url)
        if not relevant_urls:
            relevant_urls = list(urls)

        # n 則 reflects this stock's relevant article count, not the raw
        # cluster size — otherwise filtered-down events show a misleading
        # total (e.g. cluster of 3 → 1 relevant for 3661 but UI showed 3).
        news_count = len(relevant_urls)

        # Weight = max article impact_score (0~10) among relevant articles.
        # Boosts when the cluster trips the news_processor anomaly flag, or
        # when many relevant articles agree (volume bonus). Falls back to a
        # mild news-count heuristic when no article carries a real impact.
        impacts = [
            float((article_map.get(u) or {}).get("impact_score") or 0.0)
            for u in relevant_urls
        ]
        impacts = [s for s in impacts if s > 0]
        if impacts:
            base = max(impacts)
            volume_bonus = min(1.5, 0.4 * max(0, news_count - 1))
            anomaly_bonus = 1.0 if c.get("is_anomaly") else 0.0
            weight = min(10.0, base + volume_bonus + anomaly_bonus)
        else:
            weight = min(10.0, news_count * 1.2)

        direction = _direction_from_articles(relevant_urls, article_map)
        articles = [
            _article_meta(url, article_map.get(url))
            for url in relevant_urls[:5]
        ]
        articles = [a for a in articles if a]

        out.append(StockEvent(
            date=last_seen.isoformat(),
            kind=kind,
            label=str(c.get("title") or "未命名議題")[:60],
            summary=str(c.get("summary") or "")[:240],
            weight=round(weight, 1),
            news_count=news_count,
            direction=direction,
            is_anomaly=bool(c.get("is_anomaly", False)),
            articles=articles,
            event_id=str(c.get("event_id") or ""),
        ))

    out.sort(key=lambda e: (e.date, e.weight), reverse=True)
    return out


def _direction_from_articles(
    urls: Sequence[str],
    article_map: Dict[str, dict],
) -> str:
    """Aggregate cluster sentiment from member articles' impact_direction."""
    bull = bear = 0
    for url in urls:
        a = article_map.get(url)
        if not a:
            continue
        d = a.get("impact_direction")
        if d in ("up", "bull", "bullish"):
            bull += 1
        elif d in ("down", "bear", "bearish"):
            bear += 1
    if bull and bull > bear:
        return "up"
    if bear and bear > bull:
        return "down"
    return "neu"


def _article_meta(url: str, article: Optional[dict]) -> Optional[dict]:
    if not article:
        return {"url": url, "title": "", "source": "", "time": "", "impact_direction": "neutral", "impact_score": 0.0}
    pub = article.get("published_at") or ""
    time_text = ""
    try:
        if pub:
            dt = datetime.fromisoformat(str(pub))
            time_text = dt.strftime("%m/%d %H:%M")
    except (TypeError, ValueError):
        time_text = ""
    return {
        "url": url,
        "title": article.get("title") or "",
        "source": article.get("source") or "",
        "time": time_text,
        "impact_direction": article.get("impact_direction") or "neutral",
        "impact_score": float(article.get("impact_score") or 0.0),
    }


def _parse_date(value) -> Optional[date]:
    """NewsEventFile cluster dates ship as ``YYYYMMDD`` strings; tolerate
    ISO ``YYYY-MM-DD`` and full ISO datetimes too for safety."""
    if not value:
        return None
    s = str(value).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except (TypeError, ValueError):
            pass
    try:
        return datetime.fromisoformat(s).date()
    except (TypeError, ValueError):
        return None
