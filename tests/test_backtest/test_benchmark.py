"""TASK-B03 — Benchmark engine (V2 §3.5)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.backtest.benchmark import (
    BenchmarkInputError,
    compute_benchmarks,
)


def _series(values: list[float], start: str = "2025-01-02") -> pd.Series:
    idx = pd.date_range(start, periods=len(values), freq="B")
    return pd.Series(values, index=idx, dtype=float)


def _frame_from_series(series_by_id: dict[str, pd.Series]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for sid, s in series_by_id.items():
        out[sid] = pd.DataFrame({"close": s, "volume": [1_000_000] * len(s)}, index=s.index)
    return out


@pytest.fixture
def trading_idx() -> pd.DatetimeIndex:
    return pd.date_range("2025-01-02", periods=20, freq="B")


@pytest.fixture
def market_index(trading_idx: pd.DatetimeIndex) -> pd.DataFrame:
    closes = np.linspace(10000, 11000, len(trading_idx))
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes * 1.005,
            "low": closes * 0.995,
            "close": closes,
            "volume": [1_000_000] * len(trading_idx),
        },
        index=trading_idx,
    )


@pytest.fixture
def etf_total_return(trading_idx: pd.DatetimeIndex) -> pd.Series:
    # Total return: 12% over period (vs 10% price-only for market index)
    return pd.Series(np.linspace(100, 112, len(trading_idx)), index=trading_idx, dtype=float)


@pytest.fixture
def universe_daily(trading_idx: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    # Three stocks with different return profiles
    a = pd.Series(np.linspace(100, 120, len(trading_idx)), index=trading_idx)
    b = pd.Series(np.linspace(50, 55, len(trading_idx)), index=trading_idx)
    c = pd.Series(np.linspace(200, 180, len(trading_idx)), index=trading_idx)
    return _frame_from_series({"A": a, "B": b, "C": c})


# ---- core requirements ----

@pytest.mark.unit
def test_benchmark_keys_present(market_index, etf_total_return, universe_daily, trading_idx):
    res = compute_benchmarks(
        market_index=market_index,
        etf_total_return=etf_total_return,
        universe_daily=universe_daily,
        ma_short_window=3,
        ma_long_window=5,
    )
    assert {"weighted_index", "etf_total_return", "equal_weight_universe",
            "ma_strategy", "cash"} <= set(res.keys())


@pytest.mark.unit
def test_benchmark_series_lengths_match(market_index, etf_total_return, universe_daily, trading_idx):
    res = compute_benchmarks(
        market_index=market_index,
        etf_total_return=etf_total_return,
        universe_daily=universe_daily,
        ma_short_window=3,
        ma_long_window=5,
    )
    for key, series in res.items():
        assert len(series) == len(trading_idx), key


@pytest.mark.unit
def test_buy_and_hold_starts_at_one(market_index, etf_total_return, universe_daily):
    res = compute_benchmarks(
        market_index=market_index,
        etf_total_return=etf_total_return,
        universe_daily=universe_daily,
        ma_short_window=3,
        ma_long_window=5,
    )
    for key in ("weighted_index", "etf_total_return", "equal_weight_universe", "cash"):
        assert res[key].iloc[0] == pytest.approx(1.0)


@pytest.mark.unit
def test_cash_benchmark_constant_one(market_index, etf_total_return, universe_daily):
    res = compute_benchmarks(
        market_index=market_index,
        etf_total_return=etf_total_return,
        universe_daily=universe_daily,
        ma_short_window=3,
        ma_long_window=5,
    )
    assert (res["cash"] == 1.0).all()


@pytest.mark.unit
def test_equal_weight_differs_from_cap_weight(market_index, etf_total_return, universe_daily):
    res = compute_benchmarks(
        market_index=market_index,
        etf_total_return=etf_total_return,
        universe_daily=universe_daily,
        ma_short_window=3,
        ma_long_window=5,
    )
    assert res["equal_weight_universe"].iloc[-1] != pytest.approx(
        res["weighted_index"].iloc[-1]
    )


@pytest.mark.unit
def test_total_return_higher_than_price_only(market_index, etf_total_return, universe_daily):
    res = compute_benchmarks(
        market_index=market_index,
        etf_total_return=etf_total_return,
        universe_daily=universe_daily,
        ma_short_window=3,
        ma_long_window=5,
    )
    assert res["etf_total_return"].iloc[-1] > res["weighted_index"].iloc[-1]


@pytest.mark.unit
def test_ma_strategy_matches_market_in_clean_uptrend(market_index, etf_total_return, universe_daily):
    res = compute_benchmarks(
        market_index=market_index,
        etf_total_return=etf_total_return,
        universe_daily=universe_daily,
        ma_short_window=3,
        ma_long_window=5,
    )
    # Pure uptrend: MA strategy should be invested most of the period,
    # ending near the market.
    assert res["ma_strategy"].iloc[-1] >= 1.0


@pytest.mark.unit
def test_missing_market_index_raises():
    with pytest.raises(BenchmarkInputError):
        compute_benchmarks(
            market_index=pd.DataFrame(),
            etf_total_return=_series([100.0, 101.0]),
            universe_daily={},
        )
