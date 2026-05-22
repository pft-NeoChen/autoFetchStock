"""TASK-D03c (實跑) — V1 backtest orchestrator end-to-end.

Loads local daily OHLC for the 39-stock universe, builds price + volume
features, runs the walk-forward orchestrator with the long-entry/exit signal
rules, computes performance metrics, evaluates V2 §6.1 thresholds, and writes
the markdown report.

Caveats (documented in the rendered report):
- Chip / news / margin features default to neutral values because local
  data is too sparse (≤ 15 days vs. 2 years OHLC). Entry rule's chip filter
  (foreign_net_streak ≥ 3 OR margin_5d_change < 0) therefore fails for most
  bars → expect very few or zero signals.
- Benchmarks use universe equal-weight buy-and-hold as a proxy; weighted
  index / 0050 series are placeholders.
- OOS / IS ratio, alpha, regime coverage are placeholders pending §6.1
  follow-up runs.

Usage:
    python -m scripts.run_backtest_v1 [--data-dir data] \
        [--out analysis/backtest_v1_report.md]
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from src.backtest.adapters.signal_adapter import (
    make_entry_decider,
    make_exit_decider,
)
from src.backtest.walk_forward import walk_forward_windows
from src.backtest.walk_orchestrator import run_walk_forward_backtest
from src.features.price_features import atr, moving_average, rolling_volatility
from src.features.volume_features import (
    classify_volume_severity,
    daily_volume_baseline,
    daily_volume_ratio,
)
from src.journal.backtest_report import render_backtest_report
from src.journal.decision import DecisionInput, evaluate_v2_thresholds
from src.journal.experiment_registry import ExperimentRegistry
from src.journal.performance import summarize_performance

logger = logging.getLogger("autofetchstock.scripts.backtest_v1")


# ── data loading ────────────────────────────────────────────────────────────


def load_daily_ohlc_frames(data_dir: Path) -> dict[str, pd.DataFrame]:
    stocks_dir = data_dir / "stocks"
    frames: dict[str, pd.DataFrame] = {}
    if not stocks_dir.exists():
        return frames
    for path in sorted(stocks_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        rows = payload.get("daily_data", [])
        if not rows:
            continue
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        for col in ("open", "high", "low", "close", "volume"):
            if col not in df.columns:
                df[col] = float("nan")
        df = df[["open", "high", "low", "close", "volume"]].astype(float)
        df["previous_close"] = df["close"].shift(1).fillna(df["close"])
        frames[payload.get("stock_id", path.stem)] = df
    return frames


# ── feature engineering ─────────────────────────────────────────────────────


def build_feature_frame(ohlc: pd.DataFrame) -> pd.DataFrame:
    df = ohlc.copy()
    df["ma_5"] = moving_average(df["close"], window=5)
    df["ma_10"] = moving_average(df["close"], window=10)
    df["ma_20"] = moving_average(df["close"], window=20)
    df["ma_60"] = moving_average(df["close"], window=60)
    df["atr_14"] = atr(df, window=14)
    df["vol_20"] = rolling_volatility(df["close"], window=20)
    df["high_20d"] = df["high"].rolling(window=20, min_periods=5).max().shift(1)

    baseline, low_conf = daily_volume_baseline(df["volume"], window=20, min_periods=10)
    df["volume_baseline"] = baseline
    df["baseline_low_confidence"] = low_conf
    ratio = daily_volume_ratio(df["volume"], window=20, min_periods=10)
    df["volume_ratio"] = ratio
    df["spike_severity"] = ratio.apply(
        lambda r: classify_volume_severity(r).value if pd.notna(r) else "normal"
    )

    # Safe defaults (sparse data → neutral)
    df["foreign_net_streak"] = 0
    df["margin_balance_5d_change"] = 0.0
    df["news_severity"] = 0.0
    df["is_limit_up"] = False
    return df.dropna(subset=["ma_60", "atr_14"])


def build_market_state(
    feature_frames: Mapping[str, pd.DataFrame],
) -> dict[pd.Timestamp, dict[str, float]]:
    closes = pd.DataFrame({sid: f["close"] for sid, f in feature_frames.items()})
    proxy = closes.mean(axis=1)
    ma_60 = proxy.rolling(window=60, min_periods=20).mean()
    state: dict[pd.Timestamp, dict[str, float]] = {}
    for ts in proxy.index:
        state[ts] = {
            "market_close": float(proxy.loc[ts]),
            "market_ma_60": float(ma_60.loc[ts]) if pd.notna(ma_60.loc[ts]) else 0.0,
        }
    return state


# ── benchmarks (lightweight) ────────────────────────────────────────────────


def equal_weight_total_return(feature_frames: Mapping[str, pd.DataFrame]) -> float:
    rets = []
    for f in feature_frames.values():
        if len(f) < 2:
            continue
        rets.append(float(f["close"].iloc[-1] / f["close"].iloc[0] - 1.0))
    return float(np.mean(rets)) if rets else 0.0


# ── orchestration ───────────────────────────────────────────────────────────


def run(
    *,
    data_dir: Path,
    out_path: Path,
    initial_cash_per_stock: float = 1_000_000.0,
    target_shares: int = 1000,
    registry_dir: Path | None = None,
) -> None:
    logger.info("loading OHLC from %s", data_dir)
    ohlc_frames = load_daily_ohlc_frames(data_dir)
    if not ohlc_frames:
        raise RuntimeError(f"no OHLC frames under {data_dir}/stocks")

    logger.info("loaded %d stocks", len(ohlc_frames))
    feature_frames = {sid: build_feature_frame(f) for sid, f in ohlc_frames.items()}
    feature_frames = {sid: f for sid, f in feature_frames.items() if not f.empty}
    market_state = build_market_state(feature_frames)

    all_idx = sorted({ts for f in feature_frames.values() for ts in f.index})
    if not all_idx:
        raise RuntimeError("no usable dates after feature build")
    start_date: date = all_idx[0].date()
    end_date: date = all_idx[-1].date()
    logger.info("date range %s ~ %s", start_date, end_date)

    # Local data ~2 years → use IS=12mo / OOS=3mo if span allows, else shrink.
    span_days = (end_date - start_date).days
    is_months = 12 if span_days >= 540 else max(3, span_days // 60)
    oos_months = 3 if span_days >= 540 else max(1, span_days // 180)
    windows = walk_forward_windows(
        start=start_date,
        end=end_date,
        is_months=is_months,
        oos_months=oos_months,
        embargo_business_days=15,
    )
    logger.info("generated %d walk-forward windows (IS=%dmo OOS=%dmo)",
                len(windows), is_months, oos_months)

    def entry_factory(stock_id: str, frame: pd.DataFrame):
        return make_entry_decider(
            feature_df=frame,
            market_state=market_state,
            target_shares=target_shares,
        )

    def exit_factory(stock_id: str, frame: pd.DataFrame):
        return make_exit_decider(feature_df=frame)

    registry = ExperimentRegistry(registry_dir) if registry_dir else None
    manifest = {
        "strategy": "long_entry_v1",
        "universe_size": len(feature_frames),
        "data_span_start": start_date.isoformat(),
        "data_span_end": end_date.isoformat(),
        "is_months": is_months,
        "oos_months": oos_months,
        "embargo_business_days": 15,
        "initial_cash_per_stock": initial_cash_per_stock,
        "target_shares": target_shares,
        "caveats": "chip/news/margin features defaulted (local data sparse)",
    }

    result = run_walk_forward_backtest(
        universe=list(feature_frames),
        feature_frames=feature_frames,
        windows=windows,
        initial_cash_per_stock=initial_cash_per_stock,
        entry_decider_factory=entry_factory,
        exit_decider_factory=exit_factory,
        registry=registry,
        manifest=manifest,
    )
    logger.info("backtest done: trades=%d", len(result.all_trades))

    initial_capital = initial_cash_per_stock * len(feature_frames)
    metrics = summarize_performance(
        trades=result.all_trades,
        equity=result.combined_equity if not result.combined_equity.empty
        else pd.Series([initial_capital, initial_capital]),
        initial_capital=initial_capital,
    )

    # Benchmark proxy
    bench_total = equal_weight_total_return(feature_frames)

    decision_input = DecisionInput(
        metrics=metrics,
        oos_is_ratio=0.0,  # placeholder — needs IS run pass
        top5_excluded_return=metrics.total_return,  # naive
        beats_weighted_index=metrics.total_return > bench_total,
        beats_etf_0050=metrics.total_return > bench_total,
        oos_alpha=metrics.total_return - bench_total,
        regime_coverage_bull=0,
        regime_coverage_bear=0,
        regime_coverage_range=0,
    )
    decision = evaluate_v2_thresholds(decision_input)

    md = render_backtest_report(
        metrics=metrics,
        benchmarks_table={
            "weighted_index (placeholder)": 0.0,
            "etf_0050 (placeholder)": 0.0,
            "equal_weight_universe": bench_total,
            "ma_strategy (placeholder)": 0.0,
            "cash": 0.0,
        },
        decision=decision,
        manifest={**manifest, "n_trades": metrics.n_trades,
                  "n_windows": len(result.window_results),
                  "experiment_id": result.experiment_id or "(none)"},
    )

    # Caveats block prepended
    caveats = [
        "## ⚠️ 報告限制",
        "",
        "- **Chip / news / margin features 沿用 neutral defaults**（local data ≤ 15 天 vs. 2 年 OHLC）",
        "  → entry chip filter (foreign_net_streak ≥ 3 OR margin_5d_change < 0) 幾乎全失敗",
        "  → 預期極少甚至零訊號。**這是已知資料缺口,非策略本身失敗**.",
        "- **Benchmarks**: weighted_index / 0050 / ma_strategy 為 placeholder（0.0），equal_weight 為 universe 平均報酬",
        "- **OOS/IS ratio / regime coverage / alpha**: 均為 placeholder（0），需 V2 §6.1 二輪實跑（含 IS 評估、regime 標記、含息 benchmark 接入）才能 fairly 評估",
        "- **本報告為 D03c gating logic 端對端 smoke + Phase 3 結案artifact**,非 V2 §6.1 正式判決",
        "",
        "---",
        "",
    ]
    md = md.replace("# Backtest Report\n", "# Backtest Report\n\n" + "\n".join(caveats), 1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md)
    logger.info("report written to %s", out_path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", type=Path, default=Path("data"))
    p.add_argument("--out", type=Path, default=Path("analysis/backtest_v1_report.md"))
    p.add_argument("--initial-cash-per-stock", type=float, default=1_000_000.0)
    p.add_argument("--target-shares", type=int, default=1000)
    p.add_argument("--registry-dir", type=Path,
                   default=Path("analysis/experiment_registry"))
    return p.parse_args(argv)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = parse_args()
    run(
        data_dir=args.data_dir,
        out_path=args.out,
        initial_cash_per_stock=args.initial_cash_per_stock,
        target_shares=args.target_shares,
        registry_dir=args.registry_dir,
    )


if __name__ == "__main__":
    main()
