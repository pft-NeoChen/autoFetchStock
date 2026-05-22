"""TASK-D01b — Backfill historical daily OHLC to ≥ 2 years.

Iterates the local universe (one JSON per stock under ``data/stocks/``) and
calls TWSE STOCK_DAY month-by-month for any month not yet sufficiently
covered. The script delegates rate limiting, retries and atomic JSON writes
to ``DataFetcher`` / ``DataStorage`` — it only orchestrates the loop.

Run:

    python -m scripts.backfill_historical_daily --years 2

The script honours the 3-second TWSE rate limit between requests. With
~40 stocks × 24 months that's roughly 50 minutes per full re-pull; repeated
runs are idempotent and skip months that already have ≥ ``min_records``.
"""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Iterable, Protocol

logger = logging.getLogger("autofetchstock.scripts.backfill")

DEFAULT_MIN_RECORDS_PER_MONTH = 15
DEFAULT_SLEEP_SECONDS = 3.0


# ── Pure helpers ────────────────────────────────────────────────────────────


def is_month_covered(
    existing_dates: Iterable[date],
    *,
    year: int,
    month: int,
    min_records: int = DEFAULT_MIN_RECORDS_PER_MONTH,
    today: date | None = None,
) -> bool:
    """Return True if the (year, month) bucket already has ≥ min_records.

    The current month always returns False so that fresh trading days are
    picked up on each run.
    """
    if today is not None and (year, month) == (today.year, today.month):
        return False
    count = sum(1 for d in existing_dates if d.year == year and d.month == month)
    return count >= min_records


def _iter_months(start: date, end: date) -> Iterable[tuple[int, int]]:
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield (y, m)
        m += 1
        if m > 12:
            m = 1
            y += 1


def compute_missing_months(
    existing_dates: set[date],
    *,
    target_start: date,
    today: date,
    min_records: int = DEFAULT_MIN_RECORDS_PER_MONTH,
) -> list[tuple[int, int]]:
    """Return the list of (year, month) pairs that still need fetching."""
    missing: list[tuple[int, int]] = []
    for y, m in _iter_months(target_start, today):
        if not is_month_covered(
            existing_dates, year=y, month=m, min_records=min_records, today=today
        ):
            missing.append((y, m))
    return missing


# ── Protocols ───────────────────────────────────────────────────────────────


class _FetcherLike(Protocol):
    def fetch_daily_history(self, stock_id: str, year: int, month: int):
        ...


class _StorageLike(Protocol):
    def load_daily_data(self, stock_id: str):
        ...

    def save_daily_data(self, stock_id: str, stock_name: str, records) -> bool:
        ...


@dataclass
class BackfillReport:
    successful_stocks: list[str] = field(default_factory=list)
    failed_stocks: list[str] = field(default_factory=list)
    fetched_months: int = 0
    saved_records: int = 0


# ── Orchestrator ────────────────────────────────────────────────────────────


def run_backfill(
    *,
    fetcher: _FetcherLike,
    storage: _StorageLike,
    stock_ids: Iterable[str],
    target_start: date,
    today: date,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    min_records: int = DEFAULT_MIN_RECORDS_PER_MONTH,
    stock_name_lookup: Callable[[str], str] = lambda sid: sid,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> BackfillReport:
    report = BackfillReport()
    first_request = True

    for sid in stock_ids:
        try:
            existing = storage.load_daily_data(sid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("backfill: load_daily_data failed for %s: %s", sid, exc)
            report.failed_stocks.append(sid)
            continue

        existing_dates: set[date] = (
            {rec.date for rec in existing.daily_data} if existing is not None else set()
        )
        missing = compute_missing_months(
            existing_dates,
            target_start=target_start,
            today=today,
            min_records=min_records,
        )
        if not missing:
            logger.info("backfill: %s already fully covered", sid)
            report.successful_stocks.append(sid)
            continue

        stock_name = stock_name_lookup(sid)
        month_errors: list[str] = []
        months_saved = 0
        for year, month in missing:
            if not first_request and sleep_seconds > 0:
                sleep_fn(sleep_seconds)
            first_request = False

            try:
                records = fetcher.fetch_daily_history(sid, year, month)
                report.fetched_months += 1
                if records:
                    storage.save_daily_data(sid, stock_name, records)
                    report.saved_records += len(records)
                    months_saved += 1
            except Exception as exc:  # noqa: BLE001 — per-month isolation
                month_errors.append(f"{year}/{month:02d}:{exc}")
                logger.warning(
                    "backfill: %s skipped %d/%02d (%s)", sid, year, month, exc
                )

        if month_errors and months_saved == 0:
            report.failed_stocks.append(sid)
        else:
            report.successful_stocks.append(sid)
            if month_errors:
                logger.warning(
                    "backfill: %s partial — %d/%d months ok, errors: %s",
                    sid, months_saved, len(missing), month_errors,
                )

    return report


# ── CLI ─────────────────────────────────────────────────────────────────────


def _list_local_stock_ids(data_dir: Path) -> list[str]:
    stocks_dir = data_dir / "stocks"
    if not stocks_dir.exists():
        return []
    return sorted(p.stem for p in stocks_dir.glob("*.json"))


def resolve_stock_ids(
    data_dir: Path,
    *,
    override: list[str] | None = None,
) -> list[str]:
    """Choose backfill targets: explicit override > local glob."""
    if override:
        return sorted({sid.strip() for sid in override if sid.strip()})
    return _list_local_stock_ids(data_dir)


def main() -> int:  # pragma: no cover — CLI glue
    parser = argparse.ArgumentParser(description="Backfill historical daily OHLC.")
    parser.add_argument("--years", type=int, default=2, help="Lookback window in years")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP_SECONDS)
    parser.add_argument(
        "--stocks",
        type=str,
        default=None,
        help="Comma-separated stock_ids (overrides local glob; for new stocks)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    today = date.today()
    target_start = date(today.year - args.years, today.month, 1)

    from src.fetcher.data_fetcher import DataFetcher
    from src.storage.data_storage import DataStorage

    storage = DataStorage(str(args.data_dir))
    fetcher = DataFetcher(storage=storage)

    override = args.stocks.split(",") if args.stocks else None
    stock_ids = resolve_stock_ids(args.data_dir, override=override)
    logger.info("backfilling %d stocks from %s to %s", len(stock_ids), target_start, today)

    report = run_backfill(
        fetcher=fetcher,
        storage=storage,
        stock_ids=stock_ids,
        target_start=target_start,
        today=today,
        sleep_seconds=args.sleep,
    )

    logger.info(
        "done — ok=%d fail=%d months=%d records=%d failed_ids=%s",
        len(report.successful_stocks),
        len(report.failed_stocks),
        report.fetched_months,
        report.saved_records,
        report.failed_stocks,
    )
    return 0 if not report.failed_stocks else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
