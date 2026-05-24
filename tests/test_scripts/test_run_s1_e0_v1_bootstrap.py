"""TASK-S1-E0 — V1 bootstrap sanity orchestrator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_s1_e0_v1_bootstrap import (
    load_v1_trades,
    run_v1_bootstrap_experiment,
)


pytestmark = pytest.mark.unit


def test_load_v1_trades_reads_oos_and_is_lists(tmp_path: Path) -> None:
    payload = {
        "oos_trades": [
            {"stock_id": "2330", "pnl_pct": 0.01, "reason": "ma"},
            {"stock_id": "2317", "pnl_pct": -0.02, "reason": "stop"},
        ],
        "is_trades": [
            {"stock_id": "2330", "pnl_pct": 0.005, "reason": "ma"},
        ],
    }
    src = tmp_path / "v1_trades.json"
    src.write_text(json.dumps(payload))

    oos, is_ = load_v1_trades(src)

    assert len(oos) == 2
    assert len(is_) == 1
    assert oos[0]["pnl_pct"] == pytest.approx(0.01)


def test_run_v1_bootstrap_missing_trades_file_writes_report(tmp_path: Path) -> None:
    missing = tmp_path / "no_such.json"
    out = tmp_path / "report.md"

    payload = run_v1_bootstrap_experiment(
        trades_path=missing, output_path=out, n_iter=10, seed=1
    )

    assert payload == {}
    text = out.read_text()
    assert "No V1 trades file" in text


def test_run_v1_bootstrap_writes_oos_and_is_sections(tmp_path: Path) -> None:
    payload = {
        "oos_trades": [
            {"stock_id": "2330", "pnl_pct": 0.01, "reason": "ma"},
            {"stock_id": "2317", "pnl_pct": -0.02, "reason": "stop"},
            {"stock_id": "2454", "pnl_pct": 0.005, "reason": "ma"},
            {"stock_id": "2330", "pnl_pct": -0.01, "reason": "stop"},
        ],
        "is_trades": [
            {"stock_id": "2330", "pnl_pct": 0.005, "reason": "ma"},
            {"stock_id": "2317", "pnl_pct": -0.01, "reason": "stop"},
            {"stock_id": "2454", "pnl_pct": 0.02, "reason": "ma"},
            {"stock_id": "2330", "pnl_pct": -0.005, "reason": "stop"},
        ],
    }
    src = tmp_path / "v1_trades.json"
    src.write_text(json.dumps(payload))
    out = tmp_path / "report.md"

    result = run_v1_bootstrap_experiment(
        trades_path=src, output_path=out, n_iter=50, seed=42
    )

    assert {"oos", "is"} <= set(result.keys())
    assert result["oos"]["expectancy_bp"].n_iter == 50
    text = out.read_text()
    assert "V1 Bootstrap Sanity" in text
    assert "OOS" in text and "IS" in text
    assert "expectancy_bp" in text
