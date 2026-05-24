"""TASK-S1-E2 — C1-safe mean reversion experiment."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.run_s1_e2_mean_reversion import (
    classify_per_stock_regime,
    mean_reversion_oversold,
    run_mean_reversion_experiment,
)


pytestmark = pytest.mark.unit


def _trigger_panel(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index(["date", "stock_id"]).sort_index()


def _baseline_row(**overrides) -> dict:
    row = {
        "date": "2026-01-05",
        "stock_id": "2330",
        "close": 100.0,
        "ret_5d": -0.10,
        "vol_20d": 0.04,
        "rsi_14": 25.0,
        "regime": "bull",
        "news_severity": 0.0,
        "ret_1d": -0.02,
    }
    row.update(overrides)
    return row


def test_mean_reversion_passes_when_all_conditions_met() -> None:
    panel = _trigger_panel([_baseline_row()])

    mask = mean_reversion_oversold(panel)

    assert bool(mask.iloc[0]) is True


def test_mean_reversion_blocked_in_bear_regime() -> None:
    panel = _trigger_panel([_baseline_row(regime="bear")])

    mask = mean_reversion_oversold(panel)

    assert bool(mask.iloc[0]) is False


def test_mean_reversion_blocked_by_severe_news() -> None:
    panel = _trigger_panel([_baseline_row(news_severity=-6.0)])

    mask = mean_reversion_oversold(panel)

    assert bool(mask.iloc[0]) is False


def test_mean_reversion_blocked_when_limit_down_today() -> None:
    panel = _trigger_panel([_baseline_row(ret_1d=-0.10)])

    mask = mean_reversion_oversold(panel)

    assert bool(mask.iloc[0]) is False


def test_mean_reversion_blocked_when_rsi_above_threshold() -> None:
    panel = _trigger_panel([_baseline_row(rsi_14=45.0)])

    mask = mean_reversion_oversold(panel)

    assert bool(mask.iloc[0]) is False


def test_mean_reversion_blocked_when_5d_drop_not_extreme_enough() -> None:
    # ret_5d = -0.05, threshold = -1.5 * 0.04 = -0.06 → -0.05 > -0.06 → blocked
    panel = _trigger_panel([_baseline_row(ret_5d=-0.05)])

    mask = mean_reversion_oversold(panel)

    assert bool(mask.iloc[0]) is False


def test_classify_per_stock_regime_labels_bull_and_bear_separately() -> None:
    dates = pd.date_range("2024-01-01", periods=250, freq="B")
    rows: list[dict] = []
    for i, ts in enumerate(dates):
        rows.append({"date": ts, "stock_id": "AAA", "close": 1.0 + i})
        rows.append({"date": ts, "stock_id": "BBB", "close": 250.0 - i})
    ohlc = pd.DataFrame(rows).set_index(["date", "stock_id"]).sort_index()

    regime = classify_per_stock_regime(ohlc)

    assert regime.loc[(dates[-1], "AAA")] == "bull"
    assert regime.loc[(dates[-1], "BBB")] == "bear"


def test_run_mean_reversion_empty_universe_writes_report(tmp_path: Path) -> None:
    out = tmp_path / "report.md"

    payload = run_mean_reversion_experiment(data_dir=tmp_path, output_path=out)

    assert payload == {}
    text = out.read_text()
    assert "No usable OHLC data" in text


def test_run_mean_reversion_one_stock_smoke(tmp_path: Path) -> None:
    stocks_dir = tmp_path / "stocks"
    stocks_dir.mkdir()
    # 260 trending-up days then a 5-day sharp drop at the end
    base = list(range(50, 310))
    peak = base[-6]
    base[-5] = peak * 0.96
    base[-4] = peak * 0.93
    base[-3] = peak * 0.90
    base[-2] = peak * 0.87
    base[-1] = peak * 0.84
    dates = pd.date_range("2024-01-01", periods=len(base), freq="B")
    rows = []
    for ts, c in zip(dates, base):
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
    (stocks_dir / "2330.json").write_text(
        json.dumps({"stock_id": "2330", "daily_data": rows})
    )
    out = tmp_path / "s1_e2.md"

    payload = run_mean_reversion_experiment(data_dir=tmp_path, output_path=out)

    assert "mean_reversion_oversold" in payload
    text = out.read_text()
    assert "C1-safe Mean Reversion Experiment" in text
    assert "mean_reversion_oversold" in text
    # BEAR diagnostic table should be present (diagnostic-only counts)
    assert "BEAR skip diagnostic" in text
