"""
Minute K-bar storage for autoFetchStock volume spike detection.

Persists 1-minute K bars per (stock_id, date) under data/minute_kbars/,
provides atomic writes, same-time-slot historical queries (for baseline
法 B), and recent-N queries (for baseline 法 A fallback).

Files: data/minute_kbars/{stock_id}_{YYYYMMDD}.json (StockMinuteKFile schema)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from src.exceptions import DiskSpaceError
from src.models import MinuteKBar, StockMinuteKFile

logger = logging.getLogger("autofetchstock.storage.minute_kbar")


class MinuteKBarStorage:
    """
    Atomic JSON storage for 1-minute K bars.

    Concurrency: per (stock_id, date) reentrant lock so scheduler tick
    appends and warmup backfills cannot interleave a load+save cycle.
    """

    DEFAULT_DATA_DIR: Path = Path("data/minute_kbars")
    DEFAULT_BACKUP_DIR: Path = Path("data/backup")
    MIN_DISK_SPACE_MB: int = 100

    def __init__(
        self,
        data_dir: Path = DEFAULT_DATA_DIR,
        backup_dir: Path = DEFAULT_BACKUP_DIR,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._backup_dir = Path(backup_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._backup_dir.mkdir(parents=True, exist_ok=True)

        self._locks: Dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()
        logger.info("MinuteKBarStorage initialized at %s", self._data_dir)

    # ── public API ─────────────────────────────────────────────────────────

    def save(self, file: StockMinuteKFile) -> None:
        """Atomic write of a full StockMinuteKFile (overwrites the day file)."""
        self._check_disk_space()
        path = self._file_path(file.stock_id, file.date)
        with self._lock_for(file.stock_id, file.date):
            self._atomic_write(path, file.to_dict())
        logger.debug(
            "Saved %d minute kbars for %s on %s",
            len(file.bars), file.stock_id, file.date,
        )

    def load(self, stock_id: str, target_date: date) -> Optional[StockMinuteKFile]:
        """Load a day's bars. Returns None if missing or corrupted (auto-backup)."""
        path = self._file_path(stock_id, target_date)
        if not path.exists():
            return None

        with self._lock_for(stock_id, target_date):
            data = self._load_json(path)
            if data is None:
                self._backup_corrupted(path)
                return None
            try:
                return StockMinuteKFile.from_dict(data)
            except (KeyError, ValueError, TypeError) as exc:
                logger.error(
                    "Invalid minute kbar file %s: %s — backing up", path, exc
                )
                self._backup_corrupted(path)
                return None

    def append_bar(
        self,
        stock_id: str,
        stock_name: str,
        bar: MinuteKBar,
    ) -> None:
        """
        Append/replace a single bar in the day file under per-day lock.

        If a bar with the same minute timestamp already exists it is replaced
        (e.g. when detector re-runs to fill in baseline/severity later).
        """
        target_date = bar.timestamp.date()
        with self._lock_for(stock_id, target_date):
            existing = self.load(stock_id, target_date)
            if existing is None:
                existing = StockMinuteKFile(
                    stock_id=stock_id,
                    stock_name=stock_name,
                    date=target_date,
                    bars=[],
                )
            else:
                existing.bars = [
                    b for b in existing.bars
                    if b.timestamp != bar.timestamp
                ]

            existing.bars.append(bar)
            existing.bars.sort(key=lambda b: b.timestamp)
            self.save(existing)

    def load_same_time_bars(
        self,
        stock_id: str,
        target_time: time,
        days: int = 5,
        end_date: Optional[date] = None,
    ) -> List[MinuteKBar]:
        """
        Read past N trading-day bars at the same minute slot.

        end_date is **exclusive** (the reference day, typically today).
        Iterates back from end_date - 1, skipping weekends, until `days`
        bars are collected or 30 calendar days have been scanned.

        Returns bars sorted newest → oldest (依日期由近至遠).
        """
        if days <= 0:
            return []

        cursor = (end_date or date.today()) - timedelta(days=1)
        scanned = 0
        max_scan = max(days * 3, 30)
        results: List[MinuteKBar] = []

        while len(results) < days and scanned < max_scan:
            if cursor.weekday() < 5:  # Mon-Fri
                file = self.load(stock_id, cursor)
                if file is not None:
                    match = self._find_bar_at_time(file.bars, target_time)
                    if match is not None:
                        results.append(match)
            cursor -= timedelta(days=1)
            scanned += 1

        return results

    def load_recent_bars(
        self,
        stock_id: str,
        target_date: date,
        before_timestamp: datetime,
        n: int = 20,
    ) -> List[MinuteKBar]:
        """Latest N bars on `target_date` strictly before `before_timestamp`."""
        if n <= 0:
            return []
        file = self.load(stock_id, target_date)
        if file is None:
            return []

        filtered = [b for b in file.bars if b.timestamp < before_timestamp]
        filtered.sort(key=lambda b: b.timestamp)
        return filtered[-n:]

    # ── internals ──────────────────────────────────────────────────────────

    def _file_path(self, stock_id: str, target_date: date) -> Path:
        return self._data_dir / f"{stock_id}_{target_date.strftime('%Y%m%d')}.json"

    def _lock_for(self, stock_id: str, target_date: date) -> threading.RLock:
        key = f"{stock_id}_{target_date.isoformat()}"
        with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._locks[key] = lock
        return lock

    @staticmethod
    def _find_bar_at_time(
        bars: List[MinuteKBar], target_time: time
    ) -> Optional[MinuteKBar]:
        for bar in bars:
            if bar.timestamp.time().replace(microsecond=0) == target_time.replace(microsecond=0):
                return bar
        return None

    def _atomic_write(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def _load_json(self, path: Path) -> Optional[dict]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as exc:
            logger.error("JSON decode error in %s: %s", path, exc)
            return None
        except OSError as exc:
            logger.error("Failed to read %s: %s", path, exc)
            return None

    def _backup_corrupted(self, path: Path) -> None:
        if not path.exists():
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = self._backup_dir / f"{path.stem}_{ts}.json.corrupted"
        try:
            shutil.move(str(path), str(backup))
            logger.warning("Backed up corrupted minute kbar file: %s -> %s", path, backup)
        except OSError as exc:
            logger.error("Failed to back up corrupted file %s: %s", path, exc)

    def _check_disk_space(self) -> None:
        try:
            stat = shutil.disk_usage(self._data_dir)
        except OSError as exc:
            logger.warning("Could not check disk space: %s", exc)
            return
        available_mb = stat.free / (1024 * 1024)
        if available_mb < self.MIN_DISK_SPACE_MB:
            raise DiskSpaceError(
                available_mb=available_mb,
                required_mb=self.MIN_DISK_SPACE_MB,
            )
