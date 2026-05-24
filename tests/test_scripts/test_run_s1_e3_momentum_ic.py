"""TASK-S1-E3 — C2 cross-sectional momentum IC experiment."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.run_s1_e3_momentum_ic import run_momentum_ic_experiment


pytestmark = pytest.mark.unit


def _write_stock(stocks_dir: Path, stock_id: str, closes: list[float]) -> None:
    dates = pd.date_range("2023-01-02", periods=len(closes), freq="B")
    rows = []
    for ts, c in zip(dates, closes):
        rows.append(
            {
                "date": ts.date().isoformat(),
                "open": c - 0.5,
                "high": c + 0.5,
                "low": c - 1.0,
                "close": float(c),
                "volume": 1000,
            }
        )
    (stocks_dir / f"{stock_id}.json").write_text(
        json.dumps({"stock_id": stock_id, "daily_data": rows})
    )


def test_run_momentum_ic_empty_universe_writes_report(tmp_path: Path) -> None:
    out = tmp_path / "report.md"

    payload = run_momentum_ic_experiment(data_dir=tmp_path, output_path=out)

    assert payload == {}
    text = out.read_text()
    assert "No usable OHLC data" in text


def test_run_momentum_ic_smoke_writes_expected_sections(tmp_path: Path) -> None:
    stocks = tmp_path / "stocks"
    stocks.mkdir()
    n = 320
    for i, sid in enumerate(["1101", "1102", "2330", "2454"]):
        # Trend strength differs per stock to give a non-degenerate cross-section
        base = [100.0 + (i + 1) * 0.05 * t for t in range(n)]
        _write_stock(stocks, sid, base)
    out = tmp_path / "report.md"

    payload = run_momentum_ic_experiment(data_dir=tmp_path, output_path=out)

    assert {"raw", "sector_neutral"}.issubset(payload.keys())
    assert "ic_mean" in payload["raw"]
    text = out.read_text()
    assert "C2 Cross-sectional Momentum IC" in text
    assert "Sector-neutral" in text
    assert "Decile spread" in text
