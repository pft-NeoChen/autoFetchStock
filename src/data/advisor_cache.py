"""Phase 7.4 — disk cache for LLM advisor results.

Cache key = sha1 over the inputs that should invalidate the score
(article ids, fundamentals period, chip date, last close date).
TTL controls how long a cached entry is reused before re-querying.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Sequence

from src.models import (
    Advisor,
    AdvisorBullet,
    AdvisorDimension,
    ChipKpiCard,
    FundamentalsSnapshot,
    RealtimeQuote,
)

logger = logging.getLogger("autofetchstock.advisor_cache")

_TZ_TAIPEI = timezone(timedelta(hours=8))


def compute_key(
    stock_id: str,
    *,
    articles: Sequence[dict],
    chip_cards: Sequence[ChipKpiCard],
    fundamentals: Optional[FundamentalsSnapshot],
    quote: Optional[RealtimeQuote],
    daily_closes: Sequence[float],
) -> str:
    """Deterministic key over inputs that should trigger re-scoring."""
    article_ids = sorted({
        str(a.get("url") or a.get("id") or a.get("title") or "")
        for a in articles
        if a
    })
    chip_sig = "|".join(
        f"{c.label}:{c.direction}:{c.value_text}" for c in chip_cards or []
    )
    if fundamentals:
        fund_sig = (
            f"{fundamentals.eps_period or ''}|{fundamentals.eps_q}|"
            f"{fundamentals.gross_margin}|{fundamentals.pe}"
        )
    else:
        fund_sig = ""
    quote_sig = (
        f"{round(getattr(quote, 'change_percent', 0.0) or 0.0, 1)}"
        if quote else ""
    )
    closes_sig = ""
    if daily_closes:
        closes_sig = f"{len(daily_closes)}:{round(daily_closes[-1], 2)}"
    payload = "||".join([
        stock_id,
        ",".join(article_ids),
        chip_sig,
        fund_sig,
        quote_sig,
        closes_sig,
    ])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


class AdvisorCache:
    """File-based TTL cache for ``Advisor`` snapshots.

    Layout: ``data/cache/advisor/{stock_id}.json`` — one slot per stock
    so warmup overwrites cleanly. Stale entries (TTL exceeded) are
    treated as misses.
    """

    def __init__(self, data_dir: str | os.PathLike, ttl_minutes: int) -> None:
        self._dir = Path(data_dir) / "cache" / "advisor"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ttl = timedelta(minutes=max(1, int(ttl_minutes)))
        self._lock = threading.Lock()

    def get(self, stock_id: str, key: str) -> Optional[Advisor]:
        path = self._path(stock_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("advisor cache read failed [%s]: %s", stock_id, exc)
            return None
        if data.get("key") != key:
            return None
        ts_raw = data.get("ts")
        if not ts_raw:
            return None
        try:
            ts = datetime.fromisoformat(ts_raw)
        except ValueError:
            return None
        if datetime.now(_TZ_TAIPEI) - ts > self._ttl:
            return None
        # Phase 7.4 — schema check: entries written before the badge commit
        # lack `source` / `generated_at`. Treat them as stale so the next call
        # re-queries LLM and overwrites with the new schema.
        advisor_blob = data.get("advisor") or {}
        if "source" not in advisor_blob or "generated_at" not in advisor_blob:
            logger.debug("advisor cache stale schema [%s], invalidating", stock_id)
            return None
        try:
            return _deserialize(advisor_blob)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("advisor cache decode failed [%s]: %s", stock_id, exc)
            return None

    def put(self, stock_id: str, key: str, advisor: Advisor) -> None:
        path = self._path(stock_id)
        payload = {
            "key": key,
            "ts": datetime.now(_TZ_TAIPEI).isoformat(timespec="seconds"),
            "advisor": _serialize(advisor),
        }
        with self._lock:
            try:
                tmp = path.with_suffix(".json.tmp")
                tmp.write_text(
                    json.dumps(payload, ensure_ascii=False),
                    encoding="utf-8",
                )
                os.replace(tmp, path)
            except OSError as exc:
                logger.warning("advisor cache write failed [%s]: %s", stock_id, exc)

    def _path(self, stock_id: str) -> Path:
        safe = "".join(ch for ch in stock_id if ch.isalnum()) or "unknown"
        return self._dir / f"{safe}.json"


def _serialize(advisor: Advisor) -> dict:
    return {
        "overall_score": advisor.overall_score,
        "stance": advisor.stance,
        "confidence": advisor.confidence,
        "delta": advisor.delta,
        "recommendation": advisor.recommendation,
        "source": advisor.source,
        "generated_at": advisor.generated_at,
        "dimensions": [
            {
                "key": d.key,
                "label": d.label,
                "score": d.score,
                "direction": d.direction,
                "summary": d.summary,
                "bullets": [asdict(b) for b in d.bullets],
            }
            for d in advisor.dimensions
        ],
    }


def _deserialize(data: dict) -> Advisor:
    dims = [
        AdvisorDimension(
            key=d["key"],
            label=d["label"],
            score=float(d["score"]),
            direction=d["direction"],
            summary=d.get("summary", ""),
            bullets=[AdvisorBullet(**b) for b in d.get("bullets", [])],
        )
        for d in data.get("dimensions", [])
    ]
    return Advisor(
        overall_score=float(data["overall_score"]),
        stance=data.get("stance", "中性"),
        confidence=float(data.get("confidence", 0.5)),
        delta=data.get("delta", ""),
        dimensions=dims,
        recommendation=data.get("recommendation", ""),
        source=data.get("source", "heuristic"),
        generated_at=data.get("generated_at", ""),
    )
