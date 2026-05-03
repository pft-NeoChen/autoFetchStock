"""
Chip-flow storage (Phase 3.5 #3).

Persists daily T86 snapshots under `data/chips/{YYYYMMDD}.json` and
exposes per-stock recent-history lookups so the bottom KPI cards can
compute streaks and 5-day cumulative flow without re-hitting TWSE.

A single JSON per day keeps the file count bounded (≤ ~250/year) and
allows trivial rolling-window reads.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("autofetchstock.chips_storage")


class ChipsStorage:
    """Per-day on-disk cache of TWSE T86 snapshots."""

    def __init__(self, data_dir: str | os.PathLike[str]) -> None:
        self._chips_dir = Path(data_dir) / "chips"
        self._chips_dir.mkdir(parents=True, exist_ok=True)

    # ── Write ───────────────────────────────────────────────────────

    def save_t86_snapshot(self, snapshot_date: date, t86_by_stock: Dict[str, dict]) -> bool:
        """Atomically write a day's T86 snapshot to disk."""
        path = self._snapshot_path(snapshot_date)
        payload = {
            "date": snapshot_date.isoformat(),
            "t86": t86_by_stock,
        }
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(dir=self._chips_dir, suffix=".tmp")
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp_path, path)
            return True
        except OSError as exc:
            logger.warning("save_t86_snapshot failed (%s): %s", snapshot_date, exc)
            return False

    # ── Read ────────────────────────────────────────────────────────

    def load_t86_day(self, snapshot_date: date) -> Optional[Dict[str, dict]]:
        path = self._snapshot_path(snapshot_date)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("load_t86_day failed (%s): %s", snapshot_date, exc)
            return None
        return payload.get("t86") or {}

    def load_recent_for_stock(
        self,
        stock_id: str,
        n_days: int = 5,
        on_or_before: Optional[date] = None,
    ) -> List[dict]:
        """Return up to `n_days` most-recent T86 rows for `stock_id`.

        Each row is the parsed dict written by the fetcher, augmented
        with the snapshot date under key "_date" (str ISO) for sorting.
        Returned list is newest-first.
        """
        cur = on_or_before or date.today()
        out: List[dict] = []
        # Search up to ~3× n_days calendar days to absorb weekends/holidays.
        budget = max(n_days * 3, 14)
        for _ in range(budget):
            if len(out) >= n_days:
                break
            day = self.load_t86_day(cur)
            cur -= timedelta(days=1)
            if not day:
                continue
            row = day.get(stock_id)
            if not row:
                continue
            row = dict(row)
            row["_date"] = (cur + timedelta(days=1)).isoformat()
            out.append(row)
        return out

    def latest_snapshot_date(self, on_or_before: Optional[date] = None) -> Optional[date]:
        """Walk back to find the most recent on-disk snapshot date."""
        cur = on_or_before or date.today()
        for _ in range(30):
            if self._snapshot_path(cur).exists():
                return cur
            cur -= timedelta(days=1)
        return None

    # ── Internals ───────────────────────────────────────────────────

    def _snapshot_path(self, d: date) -> Path:
        return self._chips_dir / f"{d.strftime('%Y%m%d')}.json"
