"""Phase 7.4 — daily LLM call quota tracker for advisor.

Persists a per-day counter and an append-only JSONL audit log so we can
see how the budget is being used and tune the cap later.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("autofetchstock.advisor_quota")

_TZ_TAIPEI = timezone(timedelta(hours=8))


@dataclass
class QuotaState:
    date: str = ""
    count: int = 0


class AdvisorQuota:
    """Daily-resetting counter with JSONL audit log.

    Thread-safe. Persists state to ``data/cache/advisor/quota.json``
    so restarts don't lose the day's count. Audit rows go to
    ``logs/advisor_quota.jsonl``.
    """

    def __init__(
        self,
        data_dir: str | os.PathLike,
        log_dir: str | os.PathLike,
        daily_limit: int,
    ) -> None:
        self._daily_limit = max(0, int(daily_limit))
        self._state_path = Path(data_dir) / "cache" / "advisor" / "quota.json"
        self._log_path = Path(log_dir) / "advisor_quota.jsonl"
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._state = self._load()

    @property
    def daily_limit(self) -> int:
        return self._daily_limit

    def remaining(self) -> int:
        with self._lock:
            self._roll_if_new_day_locked()
            return max(0, self._daily_limit - self._state.count)

    def can_call(self) -> bool:
        return self.remaining() > 0

    def record(
        self,
        *,
        stock_id: str,
        cache_status: str,
        trigger: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        latency_ms: int = 0,
        error: Optional[str] = None,
    ) -> int:
        """Record a call attempt. Returns the new daily count."""
        with self._lock:
            self._roll_if_new_day_locked()
            self._state.count += 1
            new_count = self._state.count
            self._save_locked()

        row = {
            "ts": datetime.now(_TZ_TAIPEI).isoformat(timespec="seconds"),
            "stock_id": stock_id,
            "cache": cache_status,
            "trigger": trigger,
            "tokens_in": int(tokens_in),
            "tokens_out": int(tokens_out),
            "latency_ms": int(latency_ms),
            "daily_count": new_count,
            "daily_limit": self._daily_limit,
        }
        if error:
            row["error"] = error[:300]
        try:
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("advisor quota log write failed: %s", exc)
        return new_count

    def _today_key(self) -> str:
        return datetime.now(_TZ_TAIPEI).strftime("%Y-%m-%d")

    def _roll_if_new_day_locked(self) -> None:
        today = self._today_key()
        if self._state.date != today:
            if self._state.date:
                logger.info(
                    "advisor quota reset: %s ended with %d/%d calls",
                    self._state.date, self._state.count, self._daily_limit,
                )
            self._state = QuotaState(date=today, count=0)
            self._save_locked()

    def _load(self) -> QuotaState:
        if not self._state_path.exists():
            return QuotaState(date=self._today_key(), count=0)
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            state = QuotaState(date=str(data.get("date", "")), count=int(data.get("count", 0)))
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning("advisor quota state corrupt, resetting: %s", exc)
            state = QuotaState(date=self._today_key(), count=0)
        if state.date != self._today_key():
            state = QuotaState(date=self._today_key(), count=0)
        return state

    def _save_locked(self) -> None:
        try:
            tmp = self._state_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps({"date": self._state.date, "count": self._state.count}),
                encoding="utf-8",
            )
            os.replace(tmp, self._state_path)
        except OSError as exc:
            logger.warning("advisor quota state save failed: %s", exc)
