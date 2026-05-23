"""V1 §6.1 verdict-fix Plan A — real market-index + ETF benchmark wiring.

Uses 0050 daily OHLC as a proxy for both ``market_index`` and
``etf_total_return`` inputs to ``compute_benchmarks``. This is a transition
step before IR0003 (加權報酬指數含息) backfill lands.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.run_backtest_v1 import (
    benchmark_period_returns,
    load_market_proxy_from_disk,
)


pytestmark = pytest.mark.unit


def _write_stock_json(data_dir: Path, stock_id: str, daily: list[dict]) -> None:
    stocks = data_dir / "stocks"
    stocks.mkdir(parents=True, exist_ok=True)
    (stocks / f"{stock_id}.json").write_text(
        json.dumps({"stock_id": stock_id, "daily_data": daily})
    )


def _row(date_: str, close: float) -> dict:
    return {
        "date": date_,
        "open": close - 0.5,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 1_000_000,
    }


# ── load_market_proxy_from_disk ─────────────────────────────────────────────


def test_load_market_proxy_returns_ohlc_and_close_series(tmp_path: Path) -> None:
    _write_stock_json(
        tmp_path,
        "0050",
        [
            _row("2024-01-02", 130.0),
            _row("2024-01-03", 131.0),
            _row("2024-01-04", 132.0),
        ],
    )
    ohlc, close = load_market_proxy_from_disk(tmp_path, stock_id="0050")
    assert {"open", "high", "low", "close", "volume"}.issubset(ohlc.columns)
    assert len(ohlc) == 3
    assert close.iloc[-1] == pytest.approx(132.0)
    assert list(ohlc.index) == list(close.index)


def test_load_market_proxy_missing_file_returns_empty(tmp_path: Path) -> None:
    ohlc, close = load_market_proxy_from_disk(tmp_path, stock_id="0050")
    assert ohlc.empty
    assert close.empty


# ── benchmark_period_returns ────────────────────────────────────────────────


def test_benchmark_period_returns_extracts_window_returns() -> None:
    idx = pd.date_range("2025-01-01", periods=10, freq="B")
    curves = {
        "weighted_index": pd.Series([1.0 + i * 0.01 for i in range(10)], index=idx),
        "etf_total_return": pd.Series([1.0 + i * 0.02 for i in range(10)], index=idx),
        "cash": pd.Series(1.0, index=idx),
    }
    start = idx[2]
    end = idx[7]
    rets = benchmark_period_returns(curves, period=(start, end))
    # weighted_index: (1.07/1.02 - 1) ≈ 0.049
    assert rets["weighted_index"] == pytest.approx(0.049, abs=0.001)
    # etf: (1.14/1.04 - 1) ≈ 0.0962
    assert rets["etf_total_return"] == pytest.approx(0.0962, abs=0.001)
    assert rets["cash"] == pytest.approx(0.0)


def test_benchmark_period_returns_empty_curve_gives_zero() -> None:
    idx = pd.date_range("2025-01-01", periods=3, freq="B")
    curves = {"weighted_index": pd.Series(dtype=float)}
    rets = benchmark_period_returns(curves, period=(idx[0], idx[-1]))
    assert rets["weighted_index"] == 0.0
