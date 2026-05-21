"""TASK-D01 — Local data coverage audit.

Scans ``data/`` for daily / intraday / minute_kbar files and reports per-stock
coverage (first_date, last_date, record_count) plus a backtest-readiness flag.

Usage:
    python scripts/audit_local_data.py [--data-root data] [--out analysis/local_data_audit.md]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger("autofetchstock.scripts.audit_local_data")

BACKTEST_MIN_DAYS_SPAN = 365 * 2  # spec: ≥ 2 years of daily coverage

_DATED_FILE_RE = re.compile(r"^(?P<stock_id>[A-Za-z0-9]+)_(?P<yyyymmdd>\d{8})\.json$")


@dataclass(frozen=True)
class DataCoverage:
    first_date: date
    last_date: date
    record_count: int


@dataclass
class StockCoverage:
    stock_id: str
    stock_name: str = ""
    daily: DataCoverage | None = None
    intraday: DataCoverage | None = None
    minute_kbar: DataCoverage | None = None

    @property
    def backtest_ready(self) -> bool:
        if self.daily is None:
            return False
        span_days = (self.daily.last_date - self.daily.first_date).days
        return span_days >= BACKTEST_MIN_DAYS_SPAN


def _parse_date(text: str) -> date:
    return datetime.fromisoformat(text.split("T", 1)[0]).date()


def _scan_daily(stocks_dir: Path, report: dict[str, StockCoverage]) -> None:
    if not stocks_dir.is_dir():
        return
    for path in sorted(stocks_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("skip corrupt daily file %s: %s", path, exc)
            continue
        stock_id = payload.get("stock_id") or path.stem
        rows = payload.get("daily_data") or []
        if not rows:
            continue
        dates = sorted(_parse_date(r["date"]) for r in rows if "date" in r)
        if not dates:
            continue
        cov = report.setdefault(stock_id, StockCoverage(stock_id=stock_id))
        cov.stock_name = cov.stock_name or payload.get("stock_name", "")
        cov.daily = DataCoverage(first_date=dates[0], last_date=dates[-1], record_count=len(dates))


def _scan_dated_dir(
    directory: Path,
    payload_records_key: str,
    setter: str,
    report: dict[str, StockCoverage],
) -> None:
    if not directory.is_dir():
        return
    # Aggregate per stock first.
    per_stock: dict[str, dict[str, object]] = {}
    for path in sorted(directory.glob("*.json")):
        m = _DATED_FILE_RE.match(path.name)
        if not m:
            continue
        stock_id = m.group("stock_id")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("skip corrupt file %s: %s", path, exc)
            continue
        records = payload.get(payload_records_key) or []
        file_date = _parse_date(payload.get("date", m.group("yyyymmdd")[:4] + "-" + m.group("yyyymmdd")[4:6] + "-" + m.group("yyyymmdd")[6:8]))
        bucket = per_stock.setdefault(stock_id, {"count": 0, "dates": [], "name": payload.get("stock_name", "")})
        bucket["count"] = int(bucket["count"]) + len(records)
        dates_list: list[date] = bucket["dates"]  # type: ignore[assignment]
        dates_list.append(file_date)

    for stock_id, info in per_stock.items():
        dates_list: list[date] = sorted(info["dates"])  # type: ignore[assignment]
        if not dates_list:
            continue
        cov = report.setdefault(stock_id, StockCoverage(stock_id=stock_id))
        cov.stock_name = cov.stock_name or str(info["name"])
        coverage = DataCoverage(
            first_date=dates_list[0],
            last_date=dates_list[-1],
            record_count=int(info["count"]),
        )
        setattr(cov, setter, coverage)


def audit_local_data(data_root: Path) -> dict[str, StockCoverage]:
    """Scan ``data_root`` and produce per-stock coverage report."""
    data_root = Path(data_root)
    report: dict[str, StockCoverage] = {}
    _scan_daily(data_root / "stocks", report)
    _scan_dated_dir(data_root / "intraday", "ticks", "intraday", report)
    _scan_dated_dir(data_root / "minute_kbars", "bars", "minute_kbar", report)
    return report


def render_markdown_report(report: dict[str, StockCoverage]) -> str:
    lines: list[str] = []
    lines.append("# Local Data Coverage Audit")
    lines.append("")
    lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"Total stocks: {len(report)}")
    ready = [s for s, c in report.items() if c.backtest_ready]
    lines.append(f"Backtest-ready (daily span ≥ {BACKTEST_MIN_DAYS_SPAN} days): {len(ready)}")
    lines.append("")
    lines.append("## Per-stock coverage")
    lines.append("")
    lines.append("| stock_id | name | daily | intraday | minute_kbar | backtest_ready |")
    lines.append("|----------|------|-------|----------|-------------|----------------|")
    for stock_id in sorted(report):
        cov = report[stock_id]
        lines.append(
            "| {sid} | {name} | {daily} | {intraday} | {minute} | {ready} |".format(
                sid=stock_id,
                name=cov.stock_name or "—",
                daily=_fmt_cov(cov.daily),
                intraday=_fmt_cov(cov.intraday),
                minute=_fmt_cov(cov.minute_kbar),
                ready="✅" if cov.backtest_ready else "—",
            )
        )
    lines.append("")
    return "\n".join(lines)


def _fmt_cov(c: DataCoverage | None) -> str:
    if c is None:
        return "—"
    return f"{c.first_date}~{c.last_date} ({c.record_count})"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit local data coverage")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--out", type=Path, default=Path("analysis/local_data_audit.md"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = audit_local_data(args.data_root)
    md = render_markdown_report(report)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md, encoding="utf-8")
    print(f"Audit written → {args.out} ({len(report)} stocks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
