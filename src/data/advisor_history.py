"""Phase 7.5 — daily advisor score history for real `delta vs 昨日`.

Stores one row per (stock_id, date) with the day's overall_score so the
next day's advisor render can compute a real delta instead of the
synthetic ``(score - 5.0) * 0.18`` placeholder.

File layout: ``data/cache/advisor/history/{stock_id}.json``
Schema: ``{"entries": [{"date": "YYYY-MM-DD", "score": float, "ts": iso}]}``
Retention: keep last 30 entries per stock so files stay tiny.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("autofetchstock.advisor_history")

_TZ_TAIPEI = timezone(timedelta(hours=8))
_RETENTION = 30

_dir: Optional[Path] = None
_lock = threading.Lock()


def configure(data_dir: str) -> None:
    global _dir
    _dir = Path(data_dir) / "cache" / "advisor" / "history"
    _dir.mkdir(parents=True, exist_ok=True)


def record_score(stock_id: str, score: float) -> None:
    """Append today's score (overwrite if today already has an entry)."""
    if not stock_id or _dir is None:
        return
    path = _path(stock_id)
    today = datetime.now(_TZ_TAIPEI).strftime("%Y-%m-%d")
    now_iso = datetime.now(_TZ_TAIPEI).isoformat(timespec="seconds")
    with _lock:
        entries = _load_entries(path)
        entries = [e for e in entries if e.get("date") != today]
        entries.append({"date": today, "score": float(score), "ts": now_iso})
        entries = entries[-_RETENTION:]
        try:
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            logger.debug("advisor history save failed [%s]: %s", stock_id, exc)


def previous_score(stock_id: str) -> Optional[float]:
    """Return the score from the most recent date BEFORE today.

    Returns None if no prior entry exists (first time analyzing) — caller
    should fall back to a neutral delta or hide the comparison.
    """
    if not stock_id or _dir is None:
        return None
    path = _path(stock_id)
    if not path.exists():
        return None
    today = datetime.now(_TZ_TAIPEI).strftime("%Y-%m-%d")
    entries = _load_entries(path)
    for entry in reversed(entries):
        if entry.get("date") and entry["date"] != today:
            try:
                return float(entry.get("score"))
            except (TypeError, ValueError):
                continue
    return None


def _path(stock_id: str) -> Path:
    safe = "".join(ch for ch in stock_id if ch.isalnum()) or "unknown"
    return _dir / f"{safe}.json"


def _load_entries(path: Path) -> list:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data.get("entries") or [])
    except (json.JSONDecodeError, OSError):
        return []
