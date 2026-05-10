"""Phase 7.4 — Gemini-backed advisor scorer.

Single LLM call covers all four dimensions plus overall stance and
recommendation text. Caller is responsible for cache + quota; this
module just shapes the request/response.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Optional, Sequence, Tuple

from src.config import AppConfig
from src.models import (
    Advisor,
    AdvisorBullet,
    AdvisorDimension,
    ChipKpiCard,
    FundamentalsSnapshot,
    RealtimeQuote,
)

logger = logging.getLogger("autofetchstock.advisor_llm")

_MODEL = "gemini-3.1-flash-lite-preview"
_MAX_ARTICLES = 12
_MAX_CLOSES = 30
_REQ_TIMEOUT_S = 30

_PROMPT = """\
你是台股專業投資顧問。請依下列資料為股票 {stock_id}（{stock_name}）產生 4 個面向的評分（0-10）與建議。
評分越高越偏多；5.0 為中性；越低越偏空。每個面向需給 score、direction（up/down/neu）、summary（≤60 字）、
最多 3 點 bullets（每點 tag = bull/bear/neu，text ≤ 40 字）。最後加上 overall_score（0-10）、stance
（偏多/中性/偏空）、confidence（0-1，反映資料完整度）、recommendation（≤80 字，給出具體觀察重點）。

僅回傳 JSON 物件，不要 markdown、不要其他文字。Schema：
{{
  "overall_score": 5.5,
  "stance": "中性",
  "confidence": 0.6,
  "recommendation": "...",
  "dimensions": [
    {{"key": "news", "label": "新聞面", "score": 5.0, "direction": "neu", "summary": "...",
      "bullets": [{{"tag": "neu", "text": "..."}}]}},
    {{"key": "chip", "label": "籌碼面", ...}},
    {{"key": "fund", "label": "基本面", ...}},
    {{"key": "tech", "label": "技術面", ...}}
  ]
}}

— 新聞（最多 {n_articles} 則，僅供參考）：
{articles_block}

— 籌碼指標：
{chips_block}

— 基本面：
{fund_block}

— 即時報價：
{quote_block}

— 近期日線收盤（最舊→最新，最多 {n_closes} 筆）：
{closes_block}
"""


class AdvisorLLM:
    """Wraps Gemini SDK to produce a single-call advisor JSON."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._client = None
        self._disabled_reason = ""
        if not config.gemini_api_key:
            self._disabled_reason = "GEMINI_API_KEY not configured"
            return
        try:
            import google.genai as genai
            self._client = genai.Client(api_key=config.gemini_api_key)
        except Exception as exc:
            self._disabled_reason = f"sdk init failed: {exc}"
            logger.warning("AdvisorLLM disabled: %s", self._disabled_reason)

    @property
    def available(self) -> bool:
        return self._client is not None

    @property
    def disabled_reason(self) -> str:
        return self._disabled_reason

    def score(
        self,
        stock_id: str,
        stock_name: str,
        *,
        articles: Sequence[dict],
        chip_cards: Sequence[ChipKpiCard],
        fundamentals: Optional[FundamentalsSnapshot],
        quote: Optional[RealtimeQuote],
        daily_closes: Sequence[float],
    ) -> Tuple[Optional[Advisor], int, int, int]:
        """Run one LLM call. Returns (advisor, tokens_in, tokens_out, latency_ms).

        Advisor is None on any failure (parse error, network, etc.) and
        the caller should fall back to heuristic. Token counts are best
        effort — Gemini SDK exposes them on ``response.usage_metadata``.
        """
        if not self.available:
            return None, 0, 0, 0

        prompt = _PROMPT.format(
            stock_id=stock_id,
            stock_name=stock_name or stock_id,
            n_articles=_MAX_ARTICLES,
            n_closes=_MAX_CLOSES,
            articles_block=_render_articles(articles),
            chips_block=_render_chips(chip_cards),
            fund_block=_render_fund(fundamentals),
            quote_block=_render_quote(quote),
            closes_block=_render_closes(daily_closes),
        )

        t0 = time.monotonic()
        try:
            response = self._client.models.generate_content(
                model=_MODEL,
                contents=prompt,
            )
        except Exception as exc:
            latency_ms = int((time.monotonic() - t0) * 1000)
            logger.warning("advisor LLM call failed [%s]: %s", stock_id, exc)
            return None, 0, 0, latency_ms

        latency_ms = int((time.monotonic() - t0) * 1000)
        text = (response.text or "").strip()
        tokens_in, tokens_out = _extract_token_usage(response)

        advisor = _parse_response(text)
        if advisor is None:
            logger.warning(
                "advisor LLM parse failed [%s]: %r", stock_id, text[:200],
            )
        return advisor, tokens_in, tokens_out, latency_ms


def _render_articles(articles: Sequence[dict]) -> str:
    if not articles:
        return "（無）"
    rows = []
    for idx, art in enumerate(articles[:_MAX_ARTICLES], start=1):
        title = str(art.get("title") or "未命名")[:80]
        impact = art.get("impact_direction") or art.get("impact") or "neu"
        score = art.get("impact_score")
        summary = str(art.get("summary") or art.get("excerpt") or "")[:160]
        rows.append(f"{idx}. [{impact}/{score}] {title} — {summary}")
    return "\n".join(rows)


def _render_chips(cards: Sequence[ChipKpiCard]) -> str:
    if not cards:
        return "（無）"
    return "\n".join(
        f"- {c.label}: {c.value_text} ({c.direction}) {c.caption}".rstrip()
        for c in cards
    )


def _render_fund(fund: Optional[FundamentalsSnapshot]) -> str:
    if not fund:
        return "（無）"
    parts = []
    if fund.eps_q is not None:
        yoy = f"YoY {fund.eps_yoy:+.1f}%" if fund.eps_yoy is not None else ""
        parts.append(f"EPS {fund.eps_period} {fund.eps_q:.2f} {yoy}".strip())
    if fund.gross_margin is not None:
        delta = f"({fund.gm_delta:+.1f}pp)" if fund.gm_delta is not None else ""
        parts.append(f"毛利率 {fund.gross_margin:.1f}% {delta}".strip())
    if fund.pe is not None:
        avg = f"近均 {fund.pe_avg:.1f}x" if fund.pe_avg else ""
        parts.append(f"本益比 {fund.pe:.1f}x {avg}".strip())
    return "; ".join(parts) if parts else "（無）"


def _render_quote(quote: Optional[RealtimeQuote]) -> str:
    if not quote:
        return "（無）"
    pct = float(getattr(quote, "change_percent", 0.0) or 0.0)
    price = getattr(quote, "current_price", None)
    vol = getattr(quote, "total_volume", 0)
    return f"現價 {price} 漲跌幅 {pct:+.2f}% 成交量 {vol:,} 張"


def _render_closes(closes: Sequence[float]) -> str:
    if not closes:
        return "（無）"
    cleaned = [float(v) for v in closes if isinstance(v, (int, float))]
    tail = cleaned[-_MAX_CLOSES:]
    return ", ".join(f"{v:.2f}" for v in tail)


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _parse_response(text: str) -> Optional[Advisor]:
    if not text:
        return None
    candidates = [text]
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        candidates.insert(0, fence.group(1))
    obj = None
    for cand in candidates:
        try:
            obj = json.loads(cand)
            break
        except json.JSONDecodeError:
            continue
    if not isinstance(obj, dict):
        return None

    try:
        dims_raw = obj.get("dimensions") or []
        dims = []
        for d in dims_raw:
            if not isinstance(d, dict):
                continue
            key = d.get("key")
            if key not in ("news", "chip", "fund", "tech"):
                continue
            bullets = []
            for b in d.get("bullets") or []:
                if not isinstance(b, dict):
                    continue
                tag = b.get("tag", "neu")
                if tag not in ("bull", "bear", "neu"):
                    tag = "neu"
                bullets.append(AdvisorBullet(tag=tag, text=str(b.get("text", ""))[:80]))
            direction = d.get("direction", "neu")
            if direction not in ("up", "down", "neu"):
                direction = "neu"
            dims.append(AdvisorDimension(
                key=key,
                label=str(d.get("label") or _default_label(key)),
                score=_clamp(float(d.get("score", 5.0)), 0.0, 10.0),
                direction=direction,
                summary=str(d.get("summary") or "")[:120],
                bullets=bullets[:3],
            ))
        if len(dims) < 4:
            return None

        overall = _clamp(float(obj.get("overall_score", 5.0)), 0.0, 10.0)
        stance = str(obj.get("stance") or _stance_from_score(overall))
        confidence = _clamp(float(obj.get("confidence", 0.5)), 0.0, 1.0)
        recommendation = str(obj.get("recommendation") or "")[:160]
        delta_value = (overall - 5.0) * 0.18
        delta = f"{delta_value:+.1f} vs 昨日"

        return Advisor(
            overall_score=round(overall, 1),
            stance=stance,
            confidence=round(confidence, 2),
            delta=delta,
            dimensions=dims,
            recommendation=recommendation,
        )
    except (TypeError, ValueError, KeyError) as exc:
        logger.debug("advisor LLM parse error: %s", exc)
        return None


def _default_label(key: str) -> str:
    return {"news": "新聞面", "chip": "籌碼面", "fund": "基本面", "tech": "技術面"}.get(key, key)


def _stance_from_score(score: float) -> str:
    if score >= 6.6:
        return "偏多"
    if score <= 4.4:
        return "偏空"
    return "中性"


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def _extract_token_usage(response: object) -> Tuple[int, int]:
    meta = getattr(response, "usage_metadata", None)
    if not meta:
        return 0, 0
    tin = getattr(meta, "prompt_token_count", 0) or 0
    tout = getattr(meta, "candidates_token_count", 0) or 0
    return int(tin), int(tout)
