"""TASK-D01c — Backfill historical chip-flow snapshots to ≥ 2 years.

Date-major orchestrator: each calendar day yields up to four TWSE/TPEX
requests (T86 TWSE + T86 TPEX + MI_MARGN TWSE + MI_MARGN TPEX) which are
merged and persisted via :class:`ChipsStorage` snapshot writers.

Run:

    python -m scripts.backfill_historical_chips --years 2

~500 trading days × 4 requests × 3 s ≈ 100 minutes per full re-pull.
Repeat runs are idempotent: any day whose T86 *and* margin snapshots
already exist on disk is skipped.
"""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Protocol

logger = logging.getLogger("autofetchstock.scripts.backfill_chips")

DEFAULT_SLEEP_SECONDS = 3.0


# ── Pure helpers ────────────────────────────────────────────────────────────


def is_trading_day(d: date) -> bool:
    """Weekday heuristic — skip Sat/Sun. Holidays handled at fetch level
    (TWSE returns empty payload → orchestrator records no snapshot).
    """
    return d.weekday() < 5


def _iter_dates(start: date, end: date) -> Iterable[date]:
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def compute_missing_dates(
    *,
    target_start: date,
    today: date,
    has_t86: Callable[[date], bool],
    has_margin: Callable[[date], bool],
) -> List[date]:
    """Return weekdays in [target_start, today] missing either snapshot.

    A date is *missing* when its T86 **or** margin snapshot is absent.
    Weekends are unconditionally skipped.
    """
    missing: List[date] = []
    for d in _iter_dates(target_start, today):
        if not is_trading_day(d):
            continue
        if has_t86(d) and has_margin(d):
            continue
        missing.append(d)
    return missing


# ── Protocols ───────────────────────────────────────────────────────────────


class _ChipsFetcherLike(Protocol):
    def fetch_t86(self, target_date: date) -> Optional[dict]: ...
    def fetch_tpex_t86(self, target_date: date) -> Optional[dict]: ...
    def fetch_margin(self, target_date: date) -> Optional[dict]: ...
    def fetch_tpex_margin(self, target_date: date) -> Optional[dict]: ...


class _ChipsStorageLike(Protocol):
    def load_t86_day(self, snapshot_date: date) -> Optional[dict]: ...
    def load_margin_day(self, snapshot_date: date) -> Optional[dict]: ...
    def save_t86_snapshot(self, snapshot_date: date, merged: dict) -> bool: ...
    def save_margin_snapshot(self, snapshot_date: date, merged: dict) -> bool: ...


@dataclass
class ChipsBackfillReport:
    fetched_days: int = 0
    saved_t86_days: int = 0
    saved_margin_days: int = 0
    failed_days: List[date] = field(default_factory=list)
    skipped_empty_days: List[date] = field(default_factory=list)


# ── Orchestrator ────────────────────────────────────────────────────────────


def _safe_call(fn: Callable, *args, label: str, d: date) -> Optional[dict]:
    """Run ``fn(*args)``; log + swallow exceptions so the day loop survives."""
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 — per-endpoint isolation
        logger.warning("backfill_chips: %s failed for %s: %s", label, d, exc)
        return None


def run_chips_backfill(
    *,
    fetcher: _ChipsFetcherLike,
    storage: _ChipsStorageLike,
    target_start: date,
    today: date,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> ChipsBackfillReport:
    """Walk weekdays in [target_start, today]; persist any missing T86 /
    margin snapshot per market with TWSE+TPEX merged.
    """
    raise NotImplementedError("RED stub — implement in GREEN step")


# ── CLI ─────────────────────────────────────────────────────────────────────


def main() -> int:  # pragma: no cover — CLI glue
    parser = argparse.ArgumentParser(description="Backfill historical chip-flow snapshots.")
    parser.add_argument("--years", type=int, default=2, help="Lookback window in years")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP_SECONDS)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    today = date.today()
    target_start = date(today.year - args.years, today.month, today.day)

    from src.fetcher.chips_fetcher import ChipsFetcher
    from src.storage.chips_storage import ChipsStorage

    fetcher = ChipsFetcher()
    storage = ChipsStorage(str(args.data_dir))

    logger.info("backfill_chips from %s to %s", target_start, today)
    report = run_chips_backfill(
        fetcher=fetcher,
        storage=storage,
        target_start=target_start,
        today=today,
        sleep_seconds=args.sleep,
    )

    logger.info(
        "done — fetched_days=%d t86=%d margin=%d failed=%d empty=%d",
        report.fetched_days,
        report.saved_t86_days,
        report.saved_margin_days,
        len(report.failed_days),
        len(report.skipped_empty_days),
    )
    return 0 if not report.failed_days else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
