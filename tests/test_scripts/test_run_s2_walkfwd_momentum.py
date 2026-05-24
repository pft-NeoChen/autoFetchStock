"""TASK-S2-WALKFWD — E3 momentum walk-forward IC + real sector-neutral."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.run_s2_walkfwd_momentum import (
    classify_walkfwd_verdict,
    compute_window_ic,
    run_walkfwd_momentum,
)


pytestmark = pytest.mark.unit


def _write_stock(stocks_dir: Path, stock_id: str, closes: list[float], start: str = "2023-01-02") -> None:
    dates = pd.date_range(start, periods=len(closes), freq="B")
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


def test_compute_window_ic_restricts_feature_and_forward_to_oos_range() -> None:
    dates = pd.date_range("2024-01-01", periods=50, freq="B")
    stocks = ["A", "B", "C", "D"]
    idx = pd.MultiIndex.from_product([dates, stocks], names=["date", "stock_id"])
    # Feature perfectly correlated with forward return → IC ≈ 1
    feature = pd.Series(range(len(idx)), index=idx, dtype=float)
    forward = feature.copy() * 2.0

    ic = compute_window_ic(
        feature=feature,
        forward=forward,
        oos_start=dates[10].date(),
        oos_end=dates[40].date(),
    )

    assert ic["ic_mean"] == pytest.approx(1.0, abs=1e-9)
    assert ic["n_periods"] > 0


def test_classify_walkfwd_verdict_uses_E3_gate_thresholds() -> None:
    assert classify_walkfwd_verdict(0.06) == "UNLOCK"
    assert classify_walkfwd_verdict(0.04) == "UNLOCK"
    assert classify_walkfwd_verdict(0.03) == "UNCERTAIN"
    assert classify_walkfwd_verdict(0.025) == "UNCERTAIN"
    assert classify_walkfwd_verdict(0.019) == "DEAD"
    assert classify_walkfwd_verdict(-0.05) == "DEAD"


def test_run_walkfwd_momentum_empty_universe_writes_report(tmp_path: Path) -> None:
    out = tmp_path / "report.md"
    sector_map = tmp_path / "sector_map.json"
    sector_map.write_text(json.dumps({}))

    payload = run_walkfwd_momentum(
        data_dir=tmp_path,
        sector_map_path=sector_map,
        output_path=out,
    )

    assert payload == {}
    text = out.read_text()
    assert "No usable OHLC data" in text


def test_run_walkfwd_momentum_smoke_produces_required_sections(tmp_path: Path) -> None:
    stocks_dir = tmp_path / "stocks"
    stocks_dir.mkdir()
    sector_map_path = tmp_path / "sector_map.json"
    sector_map_path.write_text(
        json.dumps({"1101": "水泥工業", "1102": "水泥工業", "2330": "半導體業", "2454": "半導體業"})
    )
    # Need ≥ 252 + 21 + walk-forward window length of business days.
    n = 600
    sids = ["1101", "1102", "2330", "2454"]
    for i, sid in enumerate(sids):
        # gentle trends differ per stock
        base = [100.0 + (i + 1) * 0.04 * t for t in range(n)]
        _write_stock(stocks_dir, sid, base, start="2022-01-03")
    out = tmp_path / "report.md"

    payload = run_walkfwd_momentum(
        data_dir=tmp_path,
        sector_map_path=sector_map_path,
        output_path=out,
        is_months=12,
        oos_months=3,
        embargo_business_days=15,
    )

    assert "windows" in payload
    assert "raw_oos_ic_mean" in payload
    assert "sector_neutral_oos_ic_mean" in payload
    assert "verdict" in payload
    assert payload["verdict"] in {"UNLOCK", "UNCERTAIN", "DEAD"}
    text = out.read_text()
    assert "E3 Momentum Walk-Forward IC" in text
    assert "Verdict" in text
    assert "Raw" in text and "Sector-neutral" in text
