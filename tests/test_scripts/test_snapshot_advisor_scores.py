"""S2 — Advisor snapshot daily cron tests.

Captures daily Advisor scores per stock into JSONL so we can run IC
analysis on advisor recommendations after a 3-6 month collection
window (V2 §5).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.snapshot_advisor_scores import (
    SnapshotRecord,
    is_already_snapshotted,
    list_local_stock_ids,
    load_daily_closes,
    snapshot_one,
    write_snapshot_records,
)
from src.models import Advisor, AdvisorDimension


pytestmark = pytest.mark.unit


# ── list_local_stock_ids ────────────────────────────────────────────────────


def test_list_local_stock_ids_returns_sorted_set(tmp_path: Path) -> None:
    stocks = tmp_path / "stocks"
    stocks.mkdir()
    (stocks / "2330.json").write_text("{}")
    (stocks / "0050.json").write_text("{}")
    (stocks / "not_json.txt").write_text("ignore")
    assert list_local_stock_ids(tmp_path) == ["0050", "2330"]


def test_list_local_stock_ids_empty_when_missing(tmp_path: Path) -> None:
    assert list_local_stock_ids(tmp_path) == []


# ── load_daily_closes ──────────────────────────────────────────────────────


def test_load_daily_closes_returns_last_n_closes(tmp_path: Path) -> None:
    stocks = tmp_path / "stocks"
    stocks.mkdir()
    payload = {
        "stock_id": "2330",
        "daily_data": [
            {"date": "2026-05-01", "open": 99, "high": 101, "low": 98, "close": 100, "volume": 1},
            {"date": "2026-05-02", "open": 100, "high": 102, "low": 99, "close": 102, "volume": 1},
            {"date": "2026-05-03", "open": 102, "high": 104, "low": 101, "close": 103, "volume": 1},
        ],
    }
    (stocks / "2330.json").write_text(json.dumps(payload))
    closes = load_daily_closes(tmp_path, "2330", limit=2)
    assert closes == [102.0, 103.0]


def test_load_daily_closes_missing_returns_empty(tmp_path: Path) -> None:
    assert load_daily_closes(tmp_path, "9999", limit=20) == []


# ── snapshot_one ───────────────────────────────────────────────────────────


def _fake_advisor(score: float = 0.65) -> Advisor:
    return Advisor(
        overall_score=score,
        stance="bullish",
        confidence=0.4,
        delta="+0.05",
        dimensions=[
            AdvisorDimension(key="news", label="News", score=0.1, direction="neu", summary=""),
            AdvisorDimension(key="chip", label="Chip", score=0.3, direction="up", summary=""),
            AdvisorDimension(key="fund", label="Fund", score=0.0, direction="neu", summary=""),
            AdvisorDimension(key="tech", label="Tech", score=0.6, direction="up", summary=""),
        ],
        recommendation="hold",
        source="heuristic",
        generated_at="2026-05-24T13:30:00+08:00",
    )


def test_snapshot_one_builds_record_from_advisor() -> None:
    builder = MagicMock(return_value=_fake_advisor(0.65))
    record = snapshot_one(
        stock_id="2330",
        snapshot_date=date(2026, 5, 24),
        closes=[100.0, 101.0, 102.0],
        advisor_builder=builder,
    )
    builder.assert_called_once()
    args, kwargs = builder.call_args
    assert kwargs.get("daily_closes") == [100.0, 101.0, 102.0]
    assert record.stock_id == "2330"
    assert record.snapshot_date == date(2026, 5, 24)
    assert record.overall_score == pytest.approx(0.65)
    assert record.confidence == pytest.approx(0.4)
    assert record.dim_news == pytest.approx(0.1)
    assert record.dim_chip == pytest.approx(0.3)
    assert record.dim_fund == pytest.approx(0.0)
    assert record.dim_tech == pytest.approx(0.6)
    assert record.source == "heuristic"


def test_snapshot_one_skips_when_no_closes() -> None:
    builder = MagicMock()
    record = snapshot_one(
        stock_id="2330",
        snapshot_date=date(2026, 5, 24),
        closes=[],
        advisor_builder=builder,
    )
    builder.assert_not_called()
    assert record is None


# ── write_snapshot_records / dedupe ────────────────────────────────────────


def test_write_snapshot_records_appends_jsonl_lines(tmp_path: Path) -> None:
    out_dir = tmp_path / "advisor_snapshots"
    records = [
        SnapshotRecord(
            snapshot_date=date(2026, 5, 24),
            stock_id="2330",
            overall_score=0.65,
            confidence=0.4,
            stance="bullish",
            source="heuristic",
            dim_news=0.1,
            dim_chip=0.3,
            dim_fund=0.0,
            dim_tech=0.6,
        ),
        SnapshotRecord(
            snapshot_date=date(2026, 5, 24),
            stock_id="0050",
            overall_score=0.50,
            confidence=0.5,
            stance="neutral",
            source="heuristic",
            dim_news=0.0,
            dim_chip=0.0,
            dim_fund=0.0,
            dim_tech=0.5,
        ),
    ]
    path = write_snapshot_records(out_dir, records, snapshot_date=date(2026, 5, 24))
    assert path.exists()
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert {p["stock_id"] for p in parsed} == {"2330", "0050"}
    assert parsed[0]["snapshot_date"] == "2026-05-24"


def test_is_already_snapshotted_detects_existing_file(tmp_path: Path) -> None:
    out_dir = tmp_path / "advisor_snapshots"
    out_dir.mkdir()
    (out_dir / "20260524.jsonl").write_text('{"stock_id":"2330"}\n')
    assert is_already_snapshotted(out_dir, date(2026, 5, 24)) is True
    assert is_already_snapshotted(out_dir, date(2026, 5, 25)) is False
