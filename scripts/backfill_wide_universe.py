"""TASK-S3-BACKFILL — Resumable wide-universe OHLC backfill.

Seeds the backfill universe from ``analysis/sector_map.json`` (produced by
TASK-S2-SECTOR), excludes already-local stocks and explicit non-stock ids
(ETF / TDR), then runs the existing per-month idempotent backfill loop
(``scripts.backfill_historical_daily.run_backfill``) over each stock while
maintaining a **stock-list-level** state file. Re-invoking with ``--resume``
skips any stock whose state is already ``ok``.

Resume protocol (STRATEGY_REVIEW.md §F.4): when the user says
"繼續 backfill" in a new session, Claude runs::

    python -m scripts.backfill_wide_universe --resume

and reports remaining / completed counts.

State file (default ``analysis/backfill_state_wide.json``)::

    {
      "started_at": ISO timestamp,
      "last_update": ISO timestamp,
      "stock_ids": [...frozen at run start...],
      "completed": {"1101": "ok", "2330": "failed", ...},
      "current": "3008" or null,
      "errors": {"2330": "timeout"}
    }
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from scripts.backfill_historical_daily import (
    DEFAULT_MIN_RECORDS_PER_MONTH,
    DEFAULT_SLEEP_SECONDS,
    run_backfill,
)


logger = logging.getLogger("autofetchstock.scripts.backfill_wide")

DEFAULT_STATE_PATH = Path("analysis/backfill_state_wide.json")
DEFAULT_EXCLUDE: tuple[str, ...] = ("0050", "9110")


@dataclass
class WideBackfillState:
    started_at: str
    last_update: str
    stock_ids: list[str]
    completed: dict[str, str] = field(default_factory=dict)
    current: str | None = None
    errors: dict[str, str] = field(default_factory=dict)


# ── universe selection ─────────────────────────────────────────────────────


def select_wide_universe(
    *,
    sector_map_path: Path,
    data_dir: Path,
    exclude: Iterable[str] = DEFAULT_EXCLUDE,
) -> list[str]:
    """Return sorted list of stock_ids in sector_map that need backfill."""
    mapping = json.loads(sector_map_path.read_text(encoding="utf-8"))
    excluded = {str(sid) for sid in exclude}
    stocks_dir = data_dir / "stocks"
    already_local: set[str] = set()
    if stocks_dir.exists():
        already_local = {p.stem for p in stocks_dir.glob("*.json")}
    return sorted(
        sid
        for sid in mapping
        if sid not in excluded and sid not in already_local
    )


# ── state file ─────────────────────────────────────────────────────────────


def save_state(state_path: Path, state: WideBackfillState) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(state_path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(asdict(state), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(tmp, state_path)


def load_state(state_path: Path) -> WideBackfillState | None:
    if not state_path.exists():
        return None
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.warning("state %s unreadable (%s); treating as missing", state_path, exc)
        return None
    return WideBackfillState(
        started_at=raw.get("started_at", ""),
        last_update=raw.get("last_update", ""),
        stock_ids=list(raw.get("stock_ids") or []),
        completed=dict(raw.get("completed") or {}),
        current=raw.get("current"),
        errors=dict(raw.get("errors") or {}),
    )


# ── orchestration ──────────────────────────────────────────────────────────


def run_wide_backfill(
    *,
    fetcher,
    storage,
    stock_ids: list[str],
    state_path: Path,
    target_start: date,
    today: date,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    min_records: int = DEFAULT_MIN_RECORDS_PER_MONTH,
    resume: bool = False,
) -> WideBackfillState:
    """Backfill ``stock_ids`` one at a time, flushing state after each."""
    now = datetime.now().isoformat(timespec="seconds")
    state = load_state(state_path) if resume else None
    if state is None:
        state = WideBackfillState(
            started_at=now,
            last_update=now,
            stock_ids=list(stock_ids),
        )
    else:
        state.last_update = now

    for sid in stock_ids:
        if state.completed.get(sid) == "ok":
            continue
        # Use the canonical module reference so monkey-patched save_state is honoured.
        import scripts.backfill_wide_universe as _self  # local import

        state.current = sid
        state.last_update = datetime.now().isoformat(timespec="seconds")
        _self.save_state(state_path, state)

        try:
            report = run_backfill(
                fetcher=fetcher,
                storage=storage,
                stock_ids=[sid],
                target_start=target_start,
                today=today,
                sleep_seconds=sleep_seconds,
                min_records=min_records,
            )
            if sid in report.successful_stocks:
                state.completed[sid] = "ok"
                state.errors.pop(sid, None)
            else:
                state.completed[sid] = "failed"
                state.errors[sid] = "no months saved"
        except Exception as exc:  # noqa: BLE001
            state.completed[sid] = "failed"
            state.errors[sid] = str(exc)
            logger.warning("backfill_wide: %s raised %s", sid, exc)

        state.current = None
        state.last_update = datetime.now().isoformat(timespec="seconds")
        _self.save_state(state_path, state)

    return state


# ── CLI ────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:  # pragma: no cover
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sector-map",
        type=Path,
        default=Path("analysis/sector_map.json"),
        help="path to sector mapping JSON (from TASK-S2-SECTOR)",
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE_PATH,
        help="path to wide-backfill state file",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=4,
        help="how many years back from today to backfill (default 4)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="skip stocks already marked 'ok' in the state file",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=DEFAULT_SLEEP_SECONDS,
        help="TWSE rate-limit sleep between months",
    )
    parser.add_argument(
        "--exclude",
        type=str,
        nargs="*",
        default=list(DEFAULT_EXCLUDE),
        help="stock ids to skip (ETF, TDR, etc.)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="optional cap on number of stocks for one run",
    )
    return parser.parse_args(argv)


def main() -> int:  # pragma: no cover — CLI glue
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args()

    targets = select_wide_universe(
        sector_map_path=args.sector_map,
        data_dir=args.data_dir,
        exclude=tuple(args.exclude),
    )
    if args.limit:
        targets = targets[: args.limit]
    logger.info("wide backfill: %d candidate stocks (resume=%s)", len(targets), args.resume)

    if not targets:
        logger.info("nothing to do")
        return 0

    # Late imports to keep test surface clean
    from src.config import AppConfig
    from src.fetcher.data_fetcher import DataFetcher
    from src.storage.data_storage import DataStorage

    config = AppConfig.from_env()
    fetcher = DataFetcher(config)
    storage = DataStorage(config)
    today = date.today()
    target_start = date(today.year - args.years, today.month, 1)

    state = run_wide_backfill(
        fetcher=fetcher,
        storage=storage,
        stock_ids=targets,
        state_path=args.state,
        target_start=target_start,
        today=today,
        sleep_seconds=args.sleep_seconds,
        resume=args.resume,
    )

    ok = sum(1 for v in state.completed.values() if v == "ok")
    failed = sum(1 for v in state.completed.values() if v == "failed")
    pending = len(targets) - ok - failed
    logger.info(
        "backfill_wide done: ok=%d / failed=%d / pending=%d / state=%s",
        ok, failed, pending, args.state,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
