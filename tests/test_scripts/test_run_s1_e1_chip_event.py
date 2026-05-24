"""TASK-S1-E1 - C0a chip event-driven experiment."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.run_s1_e1_chip_event import (
    build_chip_event_panel,
    foreign_anomaly_buy,
    foreign_reverse_to_buy,
    invtrust_anomaly_buy,
    margin_rapid_drop,
    run_chip_event_experiment,
)


pytestmark = pytest.mark.unit


def _stock_panel(values: list[float], *, column: str = "foreign_net") -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=len(values), freq="B")
    idx = pd.MultiIndex.from_product([dates, ["2330"]], names=["date", "stock_id"])
    return pd.DataFrame({column: values}, index=idx)


def _write_stock(path: Path, stock_id: str, closes: list[float]) -> None:
    rows = []
    dates = pd.date_range("2026-01-01", periods=len(closes), freq="B")
    for ts, close in zip(dates, closes):
        rows.append(
            {
                "date": ts.date().isoformat(),
                "open": close - 1.0,
                "high": close + 1.0,
                "low": close - 2.0,
                "close": close,
                "volume": 1000,
            }
        )
    (path / f"{stock_id}.json").write_text(
        json.dumps({"stock_id": stock_id, "daily_data": rows})
    )


def _write_chip(path: Path, day: str, rows: dict) -> None:
    (path / f"{day}.json").write_text(json.dumps({"date": day, "t86": rows}))


def _write_margin(path: Path, day: str, rows: dict) -> None:
    (path / f"{day}.json").write_text(json.dumps({"date": day, "margin": rows}))


def test_foreign_anomaly_buy_uses_prior_rolling_mean_and_std() -> None:
    panel = _stock_panel([100.0] * 60 + [500.0])

    mask = foreign_anomaly_buy(panel, window=60, sigma=2.0)

    assert mask.iloc[:-1].sum() == 0
    assert bool(mask.iloc[-1]) is True


def test_invtrust_anomaly_buy_uses_trust_net_column() -> None:
    panel = _stock_panel([50.0] * 60 + [200.0], column="trust_net")

    mask = invtrust_anomaly_buy(panel, window=60, sigma=2.0)

    assert bool(mask.iloc[-1]) is True


def test_foreign_reverse_to_buy_requires_previous_five_days_negative() -> None:
    panel = _stock_panel([-5.0, -4.0, -3.0, -2.0, -1.0, 10.0, 8.0])

    mask = foreign_reverse_to_buy(panel, lookback=5)

    assert bool(mask.iloc[5]) is True
    assert bool(mask.iloc[6]) is False


def test_margin_rapid_drop_triggers_when_5d_change_is_below_prior_minus_2sigma() -> None:
    # First 65 points create stable +10 5d changes, final point creates a -90 change.
    values = [1000.0 + i * 2 for i in range(65)]
    values.append(values[-5] - 90.0)
    panel = _stock_panel(values, column="margin_balance")

    mask = margin_rapid_drop(panel, change_days=5, window=60, sigma=2.0)

    assert bool(mask.iloc[-1]) is True


def test_build_chip_event_panel_merges_chip_and_margin_frames() -> None:
    dates = pd.date_range("2026-01-01", periods=2, freq="B")
    chip_frames = {
        "2330": pd.DataFrame(
            {"foreign_net": [1, 2], "trust_net": [3, 4]},
            index=dates,
        )
    }
    margin_frames = {
        "2330": pd.DataFrame({"margin_balance": [10, 12]}, index=dates)
    }

    panel = build_chip_event_panel(chip_frames, margin_frames)

    assert panel.index.names == ["date", "stock_id"]
    assert panel.loc[(dates[-1], "2330"), "foreign_net"] == 2
    assert panel.loc[(dates[-1], "2330"), "margin_balance"] == 12


def test_run_chip_event_experiment_empty_universe_writes_report(tmp_path: Path) -> None:
    out = tmp_path / "report.md"

    payload = run_chip_event_experiment(data_dir=tmp_path, output_path=out)

    assert payload == {}
    text = out.read_text()
    assert "No usable OHLC/chip data" in text


def test_run_chip_event_experiment_one_stock_smoke(tmp_path: Path) -> None:
    stocks = tmp_path / "stocks"
    chips = tmp_path / "chips"
    margin = tmp_path / "margin"
    stocks.mkdir()
    chips.mkdir()
    margin.mkdir()
    closes = [100.0 + i for i in range(80)]
    _write_stock(stocks, "2330", closes)
    dates = pd.date_range("2026-01-01", periods=80, freq="B")
    for i, ts in enumerate(dates):
        day = ts.strftime("%Y%m%d")
        foreign = 100.0 if i < 60 else (500.0 if i == 60 else 90.0)
        trust = 50.0 if i < 60 else (200.0 if i == 61 else 40.0)
        _write_chip(
            chips,
            day,
            {"2330": {"foreign_net": foreign, "trust_net": trust, "dealer_net": 0}},
        )
        _write_margin(
            margin,
            day,
            {"2330": {"margin_balance": 1000.0 + i}},
        )
    out = tmp_path / "s1_e1.md"

    payload = run_chip_event_experiment(data_dir=tmp_path, output_path=out)

    assert set(payload.keys()) == {
        "foreign_anomaly_buy",
        "invtrust_anomaly_buy",
        "foreign_reverse_to_buy",
        "margin_rapid_drop",
    }
    assert payload["foreign_anomaly_buy"].result.n_events >= 1
    text = out.read_text()
    assert "C0a Chip Event-Driven Experiment" in text
    assert "foreign_anomaly_buy" in text
