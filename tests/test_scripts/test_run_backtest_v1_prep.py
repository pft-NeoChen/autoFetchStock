"""V1 plumbing prep — tests for chip/margin loaders, market-ohlc proxy,
regime gate wrapper, and feature builder fallbacks.

This sits between TASK-D01c (chip backfill) and the V1 §6.1 重判決 run.
Once `scripts/backfill_historical_chips.py` completes, `run_backtest_v1.py`
will use these helpers to replace the neutral chip/margin defaults that
made the smoke run produce 0 trades.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from scripts.run_backtest_v1 import (
    build_feature_frame,
    build_market_ohlc_proxy,
    load_chip_frames,
    load_margin_frames,
    make_regime_gated_entry_factory,
)


pytestmark = pytest.mark.unit


# ── chip / margin loaders ───────────────────────────────────────────────────


def _write_chip_file(dir_: Path, day: str, rows: dict) -> None:
    payload = {"date": day, "t86": rows}
    (dir_ / f"{day}.json").write_text(json.dumps(payload))


def _write_margin_file(dir_: Path, day: str, rows: dict) -> None:
    payload = {"date": day, "margin": rows}
    (dir_ / f"{day}.json").write_text(json.dumps(payload))


def test_load_chip_frames_assembles_per_stock_series(tmp_path: Path) -> None:
    chips_dir = tmp_path / "chips"
    chips_dir.mkdir()
    _write_chip_file(
        chips_dir,
        "20260101",
        {
            "2330": {"foreign_net": 1000, "trust_net": 50, "dealer_net": 10, "all_net": 1060},
            "2317": {"foreign_net": -500, "trust_net": 0, "dealer_net": 5, "all_net": -495},
        },
    )
    _write_chip_file(
        chips_dir,
        "20260102",
        {
            "2330": {"foreign_net": 2000, "trust_net": 100, "dealer_net": 20, "all_net": 2120},
        },
    )

    frames = load_chip_frames(tmp_path)
    assert set(frames.keys()) == {"2330", "2317"}
    f2330 = frames["2330"]
    assert list(f2330.index) == [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02")]
    assert f2330.loc[pd.Timestamp("2026-01-02"), "foreign_net"] == 2000
    # Stock only present on one day still appears (single-row frame).
    assert len(frames["2317"]) == 1


def test_load_chip_frames_missing_dir_returns_empty(tmp_path: Path) -> None:
    assert load_chip_frames(tmp_path) == {}


def test_load_chip_frames_skips_invalid_json(tmp_path: Path) -> None:
    chips_dir = tmp_path / "chips"
    chips_dir.mkdir()
    (chips_dir / "20260101.json").write_text("{not json")
    _write_chip_file(chips_dir, "20260102", {"2330": {"foreign_net": 1}})
    frames = load_chip_frames(tmp_path)
    assert "2330" in frames
    assert len(frames["2330"]) == 1


def test_load_margin_frames_assembles_per_stock_series(tmp_path: Path) -> None:
    margin_dir = tmp_path / "margin"
    margin_dir.mkdir()
    _write_margin_file(
        margin_dir,
        "20260101",
        {
            "2330": {
                "margin_balance": 5000,
                "margin_prev": 4800,
                "short_balance": 100,
                "short_prev": 95,
            }
        },
    )
    _write_margin_file(
        margin_dir,
        "20260102",
        {"2330": {"margin_balance": 5200, "short_balance": 110}},
    )

    frames = load_margin_frames(tmp_path)
    assert "2330" in frames
    f = frames["2330"]
    assert f.loc[pd.Timestamp("2026-01-02"), "margin_balance"] == 5200
    assert f.loc[pd.Timestamp("2026-01-02"), "short_balance"] == 110


# ── market-ohlc proxy ──────────────────────────────────────────────────────


def _mkframe(closes: list[float], dates: list[str]) -> pd.DataFrame:
    idx = pd.to_datetime(dates)
    df = pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1000] * len(closes),
        },
        index=idx,
    )
    return df


def test_build_market_ohlc_proxy_uses_cross_section_mean() -> None:
    f1 = _mkframe([100, 102, 104], ["2026-01-01", "2026-01-02", "2026-01-03"])
    f2 = _mkframe([200, 198, 196], ["2026-01-01", "2026-01-02", "2026-01-03"])
    proxy = build_market_ohlc_proxy({"A": f1, "B": f2})
    assert set(["open", "high", "low", "close"]).issubset(proxy.columns)
    assert proxy.loc[pd.Timestamp("2026-01-01"), "close"] == pytest.approx(150.0)
    assert proxy.loc[pd.Timestamp("2026-01-02"), "close"] == pytest.approx(150.0)


def test_build_market_ohlc_proxy_handles_misaligned_dates() -> None:
    f1 = _mkframe([100, 102], ["2026-01-01", "2026-01-02"])
    f2 = _mkframe([200, 196], ["2026-01-02", "2026-01-03"])
    proxy = build_market_ohlc_proxy({"A": f1, "B": f2})
    # union of dates → 3 rows; per-row mean over available stocks.
    assert len(proxy) == 3
    assert proxy.loc[pd.Timestamp("2026-01-01"), "close"] == pytest.approx(100.0)


# ── feature frame chip integration ──────────────────────────────────────────


def _mk_ohlc(n: int = 80) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "open": [100.0 + i * 0.1 for i in range(n)],
            "high": [101.0 + i * 0.1 for i in range(n)],
            "low": [99.0 + i * 0.1 for i in range(n)],
            "close": [100.5 + i * 0.1 for i in range(n)],
            "volume": [1_000_000] * n,
            "previous_close": [100.4 + i * 0.1 for i in range(n)],
        },
        index=idx,
    )


def test_build_feature_frame_uses_real_chip_data_when_provided() -> None:
    ohlc = _mk_ohlc()
    chip_idx = ohlc.index
    chip_df = pd.DataFrame(
        {"foreign_net": [100] * len(chip_idx)},  # 全買 → streak 應 > 0
        index=chip_idx,
    )
    feat = build_feature_frame(ohlc, chip_df=chip_df, margin_df=None)
    # latest row should have positive streak (not 0)
    assert feat["foreign_net_streak"].iloc[-1] > 0


def test_build_feature_frame_no_chip_falls_back_to_neutral_default() -> None:
    feat = build_feature_frame(_mk_ohlc(), chip_df=None, margin_df=None)
    assert (feat["foreign_net_streak"] == 0).all()
    assert (feat["margin_balance_5d_change"] == 0.0).all()


def test_build_feature_frame_margin_change_computed_when_data_present() -> None:
    ohlc = _mk_ohlc()
    idx = ohlc.index
    # Steadily rising balance → positive 5d change.
    margin_df = pd.DataFrame(
        {"margin_balance": [1000.0 + i * 10 for i in range(len(idx))]},
        index=idx,
    )
    feat = build_feature_frame(ohlc, chip_df=None, margin_df=margin_df)
    # After warm-up (>= 5 rows) 5d change should equal +50 each row.
    later = feat["margin_balance_5d_change"].dropna().iloc[-5:]
    assert list(later) == pytest.approx([50.0] * 5)


# ── regime-gated entry factory ─────────────────────────────────────────────


def test_make_regime_gated_entry_factory_blocks_when_bear_regime() -> None:
    """Bear market_ohlc → wrapped entry decider always returns no-signal."""
    n = 260  # > slow_window=200 so MAs valid
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    # Strictly declining → BEAR
    closes = [200.0 - i * 0.5 for i in range(n)]
    market_ohlc = pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes,
         "volume": [1000] * n}, index=idx,
    )

    feat = build_feature_frame(_mk_ohlc(), chip_df=None, margin_df=None)
    market_state = {ts: {"market_close": float(c), "market_ma_60": float(c)}
                    for ts, c in zip(idx, closes)}

    inner_calls: list[date] = []

    def inner_factory(stock_id: str, frame: pd.DataFrame):
        def decider(stock_id_, ref_date, position, ohlc_row):
            inner_calls.append(ref_date)
            return None
        return decider

    gated_factory = make_regime_gated_entry_factory(
        inner_factory=inner_factory,
        market_ohlc=market_ohlc,
    )
    decider = gated_factory("2330", feat)

    # Pick a ref_date that has MA history (after slow_window).
    ref = idx[250].date()
    result = decider("2330", ref, None, feat.iloc[-1] if not feat.empty else None)
    assert result is None
    # Bear → wrapper short-circuits, inner not called.
    assert inner_calls == []
