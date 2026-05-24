"""S2 — Daily advisor score snapshot cron (V2 §5).

Captures one Advisor snapshot per universe stock into
``data/advisor_snapshots/<YYYYMMDD>.jsonl`` so a 3-6 month rolling
collection becomes a feature stream we can IC-analyse alongside the
quantitative features (`src.signals.ic_analysis`).

Currently uses the heuristic advisor path (no LLM runtime) so it runs
unattended without API keys. When LLM runtime is configured later, the
same script will record LLM-scored snapshots transparently — the JSONL
schema preserves a ``source`` field for downstream IC slicing.

Suggested cron (16:00 weekdays, after market close):
    0 16 * * 1-5 cd /path/to/repo && .venv/bin/python -m scripts.snapshot_advisor_scores
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from src.data.advisor import build_advisor
from src.models import Advisor

logger = logging.getLogger("autofetchstock.scripts.snapshot_advisor")

DEFAULT_DAILY_CLOSE_LIMIT = 60


@dataclass(frozen=True)
class SnapshotRecord:
    snapshot_date: date
    stock_id: str
    overall_score: float
    confidence: float
    stance: str
    source: str
    dim_news: float
    dim_chip: float
    dim_fund: float
    dim_tech: float

    def to_jsonable(self) -> dict:
        d = asdict(self)
        d["snapshot_date"] = self.snapshot_date.isoformat()
        return d


def list_local_stock_ids(data_dir: Path) -> List[str]:
    stocks_dir = data_dir / "stocks"
    if not stocks_dir.exists():
        return []
    return sorted(p.stem for p in stocks_dir.glob("*.json"))


def load_daily_closes(
    data_dir: Path, stock_id: str, *, limit: int = DEFAULT_DAILY_CLOSE_LIMIT
) -> List[float]:
    path = data_dir / "stocks" / f"{stock_id}.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    rows = payload.get("daily_data") or []
    closes = [float(r["close"]) for r in rows if "close" in r]
    return closes[-limit:] if limit > 0 else closes


def _dimension_score(advisor: Advisor, key: str) -> float:
    for dim in advisor.dimensions:
        if dim.key == key:
            return float(dim.score)
    return 0.0


def snapshot_one(
    *,
    stock_id: str,
    snapshot_date: date,
    closes: Sequence[float],
    advisor_builder: Callable[..., Advisor] = build_advisor,
) -> Optional[SnapshotRecord]:
    """Build one snapshot or return None when the stock has no close history."""
    if not closes:
        return None
    advisor = advisor_builder(
        stock_id,
        daily_closes=list(closes),
        stock_name=stock_id,
        trigger="snapshot_cron",
    )
    return SnapshotRecord(
        snapshot_date=snapshot_date,
        stock_id=stock_id,
        overall_score=float(advisor.overall_score),
        confidence=float(advisor.confidence),
        stance=str(advisor.stance),
        source=str(advisor.source),
        dim_news=_dimension_score(advisor, "news"),
        dim_chip=_dimension_score(advisor, "chip"),
        dim_fund=_dimension_score(advisor, "fund"),
        dim_tech=_dimension_score(advisor, "tech"),
    )


def write_snapshot_records(
    out_dir: Path, records: Sequence[SnapshotRecord], *, snapshot_date: date
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{snapshot_date.strftime('%Y%m%d')}.jsonl"
    with path.open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec.to_jsonable(), ensure_ascii=False) + "\n")
    return path


def is_already_snapshotted(out_dir: Path, snapshot_date: date) -> bool:
    path = out_dir / f"{snapshot_date.strftime('%Y%m%d')}.jsonl"
    return path.exists() and path.stat().st_size > 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/advisor_snapshots"),
    )
    parser.add_argument("--force", action="store_true",
                        help="Overwrite today's snapshot if it already exists")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    today = date.today()
    if not args.force and is_already_snapshotted(args.out_dir, today):
        logger.info("snapshot already exists for %s; skipping (use --force to overwrite)", today)
        return

    stock_ids = list_local_stock_ids(args.data_dir)
    logger.info("snapshotting %d stocks for %s", len(stock_ids), today)
    records: list[SnapshotRecord] = []
    for sid in stock_ids:
        try:
            rec = snapshot_one(
                stock_id=sid,
                snapshot_date=today,
                closes=load_daily_closes(args.data_dir, sid),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("snapshot %s failed: %s", sid, exc)
            continue
        if rec is not None:
            records.append(rec)

    path = write_snapshot_records(args.out_dir, records, snapshot_date=today)
    logger.info("wrote %d records to %s", len(records), path)


if __name__ == "__main__":
    main()
