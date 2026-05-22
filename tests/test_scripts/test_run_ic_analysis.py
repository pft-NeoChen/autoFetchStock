"""TASK-S01 (orchestrator) — run_ic_analysis script."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.run_ic_analysis import (
    forward_returns,
    load_daily_frames,
    render_ic_report,
    run_ic_analysis,
)


def _write_stock_json(path: Path, stock_id: str, closes: list[float]) -> None:
    rows = []
    idx = pd.date_range("2025-01-02", periods=len(closes), freq="B")
    for ts, c in zip(idx, closes):
        rows.append(
            {
                "date": ts.date().isoformat(),
                "open": c, "high": c * 1.01, "low": c * 0.99,
                "close": c, "volume": 1_000_000, "turnover": 0.0,
                "timestamp": ts.isoformat(),
            }
        )
    payload = {
        "stock_id": stock_id,
        "stock_name": stock_id,
        "last_updated": idx[-1].isoformat(),
        "daily_data": rows,
    }
    (path / f"{stock_id}.json").write_text(json.dumps(payload))


@pytest.mark.unit
def test_load_daily_frames_returns_per_stock_dataframes(tmp_path: Path) -> None:
    stocks_dir = tmp_path / "stocks"
    stocks_dir.mkdir()
    _write_stock_json(stocks_dir, "2330", [100.0, 101.0, 102.0])
    _write_stock_json(stocks_dir, "2317", [50.0, 51.0])

    frames = load_daily_frames(tmp_path)
    assert set(frames.keys()) == {"2330", "2317"}
    assert "close" in frames["2330"].columns
    assert len(frames["2330"]) == 3


@pytest.mark.unit
def test_forward_returns_horizon_1() -> None:
    s = pd.Series([100.0, 110.0, 99.0, 121.0])
    fr = forward_returns(s, horizon=1)
    assert fr.iloc[0] == pytest.approx(0.10)
    assert fr.iloc[1] == pytest.approx(-0.10)
    assert pd.isna(fr.iloc[-1])


@pytest.mark.unit
def test_forward_returns_horizon_5() -> None:
    s = pd.Series([100.0] * 5 + [120.0])
    fr = forward_returns(s, horizon=5)
    assert fr.iloc[0] == pytest.approx(0.20)


@pytest.mark.unit
def test_render_ic_report_contains_feature_and_horizon() -> None:
    payload = {
        "ma_5": {
            1: {"ic_mean": 0.03, "ic_std": 0.1, "ic_ir": 0.3, "p_value": 0.01, "n_periods": 100},
            5: {"ic_mean": 0.05, "ic_std": 0.1, "ic_ir": 0.5, "p_value": 0.001, "n_periods": 100},
        },
    }
    md = render_ic_report(payload, n_stocks=38, start=date(2024, 5, 2), end=date(2026, 5, 22))
    assert "ma_5" in md
    assert "0.030" in md or "0.03" in md
    assert "Universe size" in md
    assert "PASS" in md or "FAIL" in md  # threshold marker


@pytest.mark.unit
def test_run_ic_analysis_end_to_end(tmp_path: Path) -> None:
    stocks_dir = tmp_path / "stocks"
    stocks_dir.mkdir()
    rng = np.random.default_rng(0)
    # 30 stocks, 60 days
    for i in range(30):
        closes = list(100 + np.cumsum(rng.normal(scale=1.0, size=60)))
        _write_stock_json(stocks_dir, f"S{i:02d}", closes)

    out_path = tmp_path / "ic_report.md"
    report = run_ic_analysis(
        data_dir=tmp_path,
        output_path=out_path,
        horizons=(1, 5),
        ma_windows=(5,),
    )

    assert out_path.exists()
    assert "ma_5" in report
    # ic_mean values are floats (not NaN since synthetic data has variance)
    assert not np.isnan(report["ma_5"][1]["ic_mean"])
