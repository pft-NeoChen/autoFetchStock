"""Phase 7.4 AI advisor with Gemini scorer + heuristic fallback.

The dispatcher tries the LLM path (cache → quota check → Gemini call)
and falls back to the deterministic heuristic when the LLM is disabled,
quota is exhausted, parsing fails, or the network call errors.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Iterable, Optional, Sequence

from src.config import AppConfig
from src.data.advisor_cache import AdvisorCache, compute_key
from src.data.advisor_llm import AdvisorLLM
from src.data.advisor_quota import AdvisorQuota
from src.models import (
    Advisor,
    AdvisorBullet,
    AdvisorDimension,
    ChipKpiCard,
    FundamentalsSnapshot,
    RealtimeQuote,
)

logger = logging.getLogger("autofetchstock.advisor")

DIMENSION_ORDER = ("news", "chip", "fund", "tech")

_runtime_lock = threading.Lock()
_runtime: Optional["_AdvisorRuntime"] = None

_inflight_lock = threading.Lock()
_inflight: dict[str, threading.Event] = {}


class _AdvisorRuntime:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.llm = AdvisorLLM(config)
        self.cache = AdvisorCache(
            data_dir=config.data_dir,
            ttl_minutes=config.advisor_cache_ttl_min,
        )
        log_dir = os.path.dirname(config.log_file) or "logs"
        self.quota = AdvisorQuota(
            data_dir=config.data_dir,
            log_dir=log_dir,
            daily_limit=config.advisor_daily_quota,
        )
        self.enabled = bool(config.advisor_llm_enabled and self.llm.available)
        if config.advisor_llm_enabled and not self.llm.available:
            logger.info(
                "advisor LLM enabled in config but client unavailable: %s",
                self.llm.disabled_reason,
            )


def configure(config: AppConfig) -> None:
    """Install runtime (called once during app bootstrap)."""
    global _runtime
    with _runtime_lock:
        _runtime = _AdvisorRuntime(config)
        logger.info(
            "advisor configured: llm=%s ttl=%dm quota=%d",
            _runtime.enabled,
            config.advisor_cache_ttl_min,
            config.advisor_daily_quota,
        )


def get_runtime() -> Optional[_AdvisorRuntime]:
    return _runtime


def build_advisor(
    stock_id: Optional[str],
    *,
    articles: Optional[Sequence[dict]] = None,
    chip_cards: Optional[Sequence[ChipKpiCard]] = None,
    fundamentals: Optional[FundamentalsSnapshot] = None,
    quote: Optional[RealtimeQuote] = None,
    daily_closes: Optional[Sequence[float]] = None,
    stock_name: Optional[str] = None,
    trigger: str = "on_demand",
) -> Advisor:
    """Build an advisor snapshot.

    Tries LLM (cached) → falls back to heuristic on any failure. Inputs
    are optional and missing sources degrade gracefully on either path.
    """
    arts = list(articles or [])
    cards = list(chip_cards or [])
    fund = fundamentals or FundamentalsSnapshot()
    closes = list(daily_closes or [])

    runtime = _runtime
    if runtime and runtime.enabled and stock_id:
        cached, used_cache = _try_llm_path(
            runtime,
            stock_id=stock_id,
            stock_name=stock_name or stock_id,
            articles=arts,
            chip_cards=cards,
            fundamentals=fund,
            quote=quote,
            daily_closes=closes,
            trigger=trigger,
        )
        if cached is not None:
            if used_cache:
                logger.debug("advisor cache hit [%s]", stock_id)
            return cached

    return _heuristic_advisor(
        stock_id,
        articles=arts,
        chip_cards=cards,
        fundamentals=fund,
        quote=quote,
        daily_closes=closes,
    )


def warmup(
    stock_id: str,
    *,
    stock_name: Optional[str] = None,
    articles: Optional[Sequence[dict]] = None,
    chip_cards: Optional[Sequence[ChipKpiCard]] = None,
    fundamentals: Optional[FundamentalsSnapshot] = None,
    quote: Optional[RealtimeQuote] = None,
    daily_closes: Optional[Sequence[float]] = None,
) -> bool:
    """Force a cache refresh for ``stock_id``. Returns True if LLM call succeeded."""
    runtime = _runtime
    if not (runtime and runtime.enabled and stock_id):
        return False
    advisor, used_cache = _try_llm_path(
        runtime,
        stock_id=stock_id,
        stock_name=stock_name or stock_id,
        articles=list(articles or []),
        chip_cards=list(chip_cards or []),
        fundamentals=fundamentals or FundamentalsSnapshot(),
        quote=quote,
        daily_closes=list(daily_closes or []),
        trigger="warmup",
        force_miss=True,
    )
    return advisor is not None and not used_cache


def _try_llm_path(
    runtime: _AdvisorRuntime,
    *,
    stock_id: str,
    stock_name: str,
    articles: Sequence[dict],
    chip_cards: Sequence[ChipKpiCard],
    fundamentals: FundamentalsSnapshot,
    quote: Optional[RealtimeQuote],
    daily_closes: Sequence[float],
    trigger: str,
    force_miss: bool = False,
) -> tuple[Optional[Advisor], bool]:
    """Returns (advisor_or_None, used_cache)."""
    key = compute_key(
        stock_id,
        articles=articles,
        chip_cards=chip_cards,
        fundamentals=fundamentals,
        quote=quote,
        daily_closes=daily_closes,
    )

    if not force_miss:
        cached = runtime.cache.get(stock_id, key)
        if cached is not None:
            return cached, True

    inflight_key = f"{stock_id}:{key}"
    wait_event: Optional[threading.Event] = None
    own_inflight = False
    with _inflight_lock:
        existing = _inflight.get(inflight_key)
        if existing is not None:
            wait_event = existing
        else:
            own_event = threading.Event()
            _inflight[inflight_key] = own_event
            own_inflight = True

    if wait_event is not None and not force_miss:
        wait_event.wait(timeout=60)
        cached = runtime.cache.get(stock_id, key)
        if cached is not None:
            return cached, True
        return None, False

    try:
        if not runtime.quota.can_call():
            runtime.quota.record(
                stock_id=stock_id,
                cache_status="quota_exhausted",
                trigger=trigger,
                error="daily limit reached",
            )
            return None, False

        advisor, tin, tout, latency_ms = runtime.llm.score(
            stock_id=stock_id,
            stock_name=stock_name,
            articles=articles,
            chip_cards=chip_cards,
            fundamentals=fundamentals,
            quote=quote,
            daily_closes=daily_closes,
        )
        runtime.quota.record(
            stock_id=stock_id,
            cache_status="miss" if advisor is not None else "miss_failed",
            trigger=trigger,
            tokens_in=tin,
            tokens_out=tout,
            latency_ms=latency_ms,
            error=None if advisor is not None else "parse_or_call_failed",
        )
        if advisor is not None:
            runtime.cache.put(stock_id, key, advisor)
            return advisor, False
        return None, False
    finally:
        if own_inflight:
            with _inflight_lock:
                evt = _inflight.pop(inflight_key, None)
            if evt is not None:
                evt.set()


# ── Heuristic fallback (formerly the only implementation) ────────────────


def _heuristic_advisor(
    stock_id: Optional[str],
    *,
    articles: Sequence[dict],
    chip_cards: Sequence[ChipKpiCard],
    fundamentals: FundamentalsSnapshot,
    quote: Optional[RealtimeQuote],
    daily_closes: Sequence[float],
) -> Advisor:
    dimensions = [
        _build_news_dimension(articles),
        _build_chip_dimension(chip_cards),
        _build_fund_dimension(fundamentals),
        _build_tech_dimension(quote, daily_closes),
    ]

    weights = {"news": 0.30, "chip": 0.25, "fund": 0.20, "tech": 0.25}
    overall = sum(d.score * weights[d.key] for d in dimensions)
    overall = _clamp_score(overall)

    if overall >= 6.6:
        stance = "偏多"
    elif overall <= 4.4:
        stance = "偏空"
    else:
        stance = "中性"

    confidence = _confidence(articles, chip_cards, fundamentals, quote, daily_closes)
    delta_value = (overall - 5.0) * 0.18
    delta = f"{delta_value:+.1f} vs 昨日"
    recommendation = _recommendation(stock_id, stance, overall, dimensions)

    return Advisor(
        overall_score=round(overall, 1),
        stance=stance,
        confidence=round(confidence, 2),
        delta=delta,
        dimensions=dimensions,
        recommendation=recommendation,
    )


def _build_news_dimension(articles: Sequence[dict]) -> AdvisorDimension:
    if not articles:
        return AdvisorDimension(
            key="news",
            label="新聞面",
            score=5.0,
            direction="neu",
            summary="目前未取得此股相關新聞，新聞面維持中性觀察。",
            bullets=[AdvisorBullet("neu", "等待新一輪新聞批次更新。")],
        )

    scored = sorted(
        articles,
        key=lambda a: float(a.get("impact_score", 0.0) or 0.0),
        reverse=True,
    )
    bull = sum(1 for a in scored if a.get("impact_direction") == "up")
    bear = sum(1 for a in scored if a.get("impact_direction") == "down")
    avg_impact = sum(float(a.get("impact_score", 0.0) or 0.0) for a in scored) / max(1, len(scored))
    score = _clamp_score(5.0 + (bull - bear) * 0.55 + (avg_impact - 5.0) * 0.35)
    direction = _direction(score)
    summary = f"近 {len(scored)} 則相關新聞中，利多 {bull} 則、利空 {bear} 則，平均影響 {avg_impact:.1f}。"
    bullets = [
        AdvisorBullet(_bullet_tag(a.get("impact_direction")), str(a.get("title") or "未命名新聞")[:54])
        for a in scored[:3]
    ]
    return AdvisorDimension("news", "新聞面", round(score, 1), direction, summary, bullets)


def _build_chip_dimension(cards: Sequence[ChipKpiCard]) -> AdvisorDimension:
    if not cards:
        return AdvisorDimension(
            key="chip",
            label="籌碼面",
            score=5.0,
            direction="neu",
            summary="尚無法人或融資資料，籌碼面暫以中性處理。",
            bullets=[AdvisorBullet("neu", "等待三大法人與融資資料更新。")],
        )

    bull = sum(1 for c in cards if c.direction == "up")
    bear = sum(1 for c in cards if c.direction == "down")
    score = _clamp_score(5.0 + bull * 0.85 - bear * 0.85)
    summary = f"籌碼指標中 {bull} 項偏多、{bear} 項偏空，觀察外資、投信與融資變化。"
    bullets = [
        AdvisorBullet(_bullet_tag(c.direction), f"{c.label} {c.value_text} {c.caption}".strip())
        for c in cards[:4]
    ]
    return AdvisorDimension("chip", "籌碼面", round(score, 1), _direction(score), summary, bullets)


def _build_fund_dimension(fund: FundamentalsSnapshot) -> AdvisorDimension:
    score = 5.0
    bullets: list[AdvisorBullet] = []

    if fund.eps_yoy is not None:
        score += 0.8 if fund.eps_yoy > 10 else -0.6 if fund.eps_yoy < -10 else 0.0
        bullets.append(AdvisorBullet(
            "bull" if fund.eps_yoy > 0 else "bear" if fund.eps_yoy < 0 else "neu",
            f"EPS {fund.eps_period or ''} {fund.eps_q:.2f}，YoY {fund.eps_yoy:+.0f}%。",
        ))
    else:
        bullets.append(AdvisorBullet("neu", "EPS 資料尚未取得。"))

    if fund.gm_delta is not None and fund.gross_margin is not None:
        score += 0.7 if fund.gm_delta > 1 else -0.7 if fund.gm_delta < -1 else 0.0
        bullets.append(AdvisorBullet(
            "bull" if fund.gm_delta > 0 else "bear" if fund.gm_delta < 0 else "neu",
            f"毛利率 {fund.gross_margin:.1f}%，較前期 {fund.gm_delta:+.1f} 個百分點。",
        ))
    else:
        bullets.append(AdvisorBullet("neu", "毛利率變化資料不足。"))

    if fund.pe is not None and fund.pe_avg is not None and fund.pe_avg > 0:
        pe_gap = (fund.pe - fund.pe_avg) / fund.pe_avg
        score += 0.4 if pe_gap < -0.12 else -0.4 if pe_gap > 0.18 else 0.0
        bullets.append(AdvisorBullet(
            "bull" if pe_gap < -0.12 else "bear" if pe_gap > 0.18 else "neu",
            f"本益比 {fund.pe:.1f}x，近均值 {fund.pe_avg:.1f}x。",
        ))
    else:
        bullets.append(AdvisorBullet("neu", "本益比均值資料不足。"))

    score = _clamp_score(score)
    summary = "基本面以 EPS 成長、毛利率變化與估值位置綜合判斷。"
    return AdvisorDimension("fund", "基本面", round(score, 1), _direction(score), summary, bullets[:3])


def _build_tech_dimension(
    quote: Optional[RealtimeQuote],
    daily_closes: Sequence[float],
) -> AdvisorDimension:
    score = 5.0
    bullets: list[AdvisorBullet] = []

    if quote is not None:
        pct = float(getattr(quote, "change_percent", 0.0) or 0.0)
        score += max(-1.5, min(1.5, pct * 0.25))
        bullets.append(AdvisorBullet(
            "bull" if pct > 0 else "bear" if pct < 0 else "neu",
            f"盤中漲跌幅 {pct:+.2f}%，成交量 {getattr(quote, 'total_volume', 0):,} 張。",
        ))
    else:
        bullets.append(AdvisorBullet("neu", "即時報價尚未取得。"))

    closes = [float(v) for v in daily_closes if isinstance(v, (int, float))]
    if len(closes) >= 20:
        last = closes[-1]
        ma5 = _avg(closes[-5:])
        ma20 = _avg(closes[-20:])
        ma60 = _avg(closes[-60:]) if len(closes) >= 60 else None
        above_short = last >= ma5 >= ma20
        below_short = last <= ma5 <= ma20
        score += 1.0 if above_short else -1.0 if below_short else 0.0
        bullets.append(AdvisorBullet(
            "bull" if above_short else "bear" if below_short else "neu",
            f"收盤 {last:.2f}，MA5 {ma5:.2f}、MA20 {ma20:.2f}。",
        ))
        if ma60 is not None:
            score += 0.4 if last >= ma60 else -0.4
            bullets.append(AdvisorBullet(
                "bull" if last >= ma60 else "bear",
                f"股價目前{'站上' if last >= ma60 else '跌破'} MA60 {ma60:.2f}。",
            ))
    else:
        bullets.append(AdvisorBullet("neu", "日線資料不足，均線訊號暫不計分。"))

    score = _clamp_score(score)
    summary = "技術面結合盤中漲跌、成交量與均線排列，作為短線風險提示。"
    return AdvisorDimension("tech", "技術面", round(score, 1), _direction(score), summary, bullets[:3])


def _confidence(
    articles: Sequence[dict],
    cards: Sequence[ChipKpiCard],
    fund: Optional[FundamentalsSnapshot],
    quote: Optional[RealtimeQuote],
    closes: Sequence[float],
) -> float:
    score = 0.28
    if articles:
        score += min(0.20, len(articles) * 0.03)
    if cards and any(c.value_text != "--" for c in cards):
        score += 0.18
    if fund and any(v is not None for v in (fund.eps_q, fund.gross_margin, fund.pe)):
        score += 0.17
    if quote:
        score += 0.12
    if len(closes) >= 20:
        score += 0.10
    return max(0.20, min(0.92, score))


def _recommendation(
    stock_id: Optional[str],
    stance: str,
    score: float,
    dimensions: Iterable[AdvisorDimension],
) -> str:
    weakest = min(dimensions, key=lambda d: d.score)
    stock_text = stock_id or "目前標的"
    if stance == "偏多":
        return f"{stock_text} 綜合分數 {score:.1f}，可偏多觀察；仍需留意{weakest.label}是否轉弱。"
    if stance == "偏空":
        return f"{stock_text} 綜合分數 {score:.1f}，先控制部位風險；等待{weakest.label}改善再提高權重。"
    return f"{stock_text} 綜合分數 {score:.1f}，訊號尚未形成明確方向，適合等待量價或新聞確認。"


def _direction(score: float) -> str:
    if score >= 6.2:
        return "up"
    if score <= 4.6:
        return "down"
    return "neu"


def _bullet_tag(direction: Optional[str]) -> str:
    if direction in ("up", "bull", "bullish"):
        return "bull"
    if direction in ("down", "bear", "bearish"):
        return "bear"
    return "neu"


def _avg(values: Sequence[float]) -> float:
    return sum(values) / max(1, len(values))


def _clamp_score(value: float) -> float:
    return max(0.0, min(10.0, float(value)))
