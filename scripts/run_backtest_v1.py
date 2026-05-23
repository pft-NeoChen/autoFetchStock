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
from src.backtest.benchmark import compute_benchmarks
from src.backtest.regime_classifier import count_regime_coverage
from src.backtest.walk_forward import walk_forward_windows
from src.backtest.walk_orchestrator import (
    compute_oos_is_ratio_from_result,
    run_walk_forward_backtest,
)
from src.features.chip_features import foreign_net_streak, margin_n_day_change
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
from src.signals.rules.regime_gate import evaluate_regime_for_signal

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


# ── chip / margin loaders ───────────────────────────────────────────────────


def _parse_yyyymmdd(stem: str) -> pd.Timestamp | None:
    try:
        return pd.Timestamp(f"{stem[:4]}-{stem[4:6]}-{stem[6:8]}")
    except ValueError:
        return None


def load_market_proxy_from_disk(
    data_dir: Path, *, stock_id: str = "0050"
) -> tuple[pd.DataFrame, pd.Series]:
    """Load a single stock's OHLC as market-index proxy.

    Until IR0003 (加權報酬指數含息) backfill lands, 0050 raw price serves as
    both ``market_index`` and ``etf_total_return`` proxies for
    :func:`compute_benchmarks`. Returns ``(ohlc_df, close_series)``;
    missing file → ``(empty df, empty series)``.
    """
    path = data_dir / "stocks" / f"{stock_id}.json"
    empty_cols = ["open", "high", "low", "close", "volume"]
    if not path.exists():
        return pd.DataFrame(columns=empty_cols), pd.Series(dtype=float)
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return pd.DataFrame(columns=empty_cols), pd.Series(dtype=float)
    rows = payload.get("daily_data", [])
    if not rows:
        return pd.DataFrame(columns=empty_cols), pd.Series(dtype=float)
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    for col in empty_cols:
        if col not in df.columns:
            df[col] = float("nan")
    df = df[empty_cols].astype(float)
    return df, df["close"].copy()


def benchmark_period_returns(
    curves: Mapping[str, pd.Series],
    *,
    period: tuple[pd.Timestamp, pd.Timestamp],
) -> dict[str, float]:
    """Slice each cumulative curve to ``[start, end]`` and compute period
    return = end / start - 1. Empty / single-point curves → 0.0.
    """
    start, end = period
    out: dict[str, float] = {}
    for name, curve in curves.items():
        if curve is None or curve.empty:
            out[name] = 0.0
            continue
        sliced = curve.loc[pd.Timestamp(start) : pd.Timestamp(end)]
        if len(sliced) < 2:
            out[name] = 0.0
            continue
        first = float(sliced.iloc[0])
        last = float(sliced.iloc[-1])
        out[name] = (last / first - 1.0) if first != 0 else 0.0
    return out


def load_chip_frames(data_dir: Path) -> dict[str, pd.DataFrame]:
    """Walk ``data_dir/chips/*.json`` and assemble a per-stock time series.

    Returns ``{stock_id: DataFrame[date, foreign_net|trust_net|dealer_net|all_net]}``.
    Missing/invalid files are skipped silently.
    """
    chips_dir = data_dir / "chips"
    if not chips_dir.exists():
        return {}
    rows_by_stock: dict[str, list[dict]] = {}
    for path in sorted(chips_dir.glob("*.json")):
        ts = _parse_yyyymmdd(path.stem)
        if ts is None:
            continue
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        t86 = payload.get("t86") or {}
        if not isinstance(t86, dict):
            continue
        for stock_id, entry in t86.items():
            if not isinstance(entry, dict):
                continue
            row = {"date": ts}
            for key in ("foreign_net", "trust_net", "dealer_net", "all_net"):
                if key in entry:
                    row[key] = entry[key]
            rows_by_stock.setdefault(stock_id, []).append(row)

    frames: dict[str, pd.DataFrame] = {}
    for stock_id, rows in rows_by_stock.items():
        df = pd.DataFrame(rows).set_index("date").sort_index()
        frames[stock_id] = df
    return frames


def load_margin_frames(data_dir: Path) -> dict[str, pd.DataFrame]:
    """Walk ``data_dir/margin/*.json`` and assemble per-stock margin time series."""
    margin_dir = data_dir / "margin"
    if not margin_dir.exists():
        return {}
    rows_by_stock: dict[str, list[dict]] = {}
    for path in sorted(margin_dir.glob("*.json")):
        ts = _parse_yyyymmdd(path.stem)
        if ts is None:
            continue
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        margin = payload.get("margin") or {}
        if not isinstance(margin, dict):
            continue
        for stock_id, entry in margin.items():
            if not isinstance(entry, dict):
                continue
            row = {"date": ts}
            for key in ("margin_balance", "short_balance"):
                if key in entry:
                    row[key] = entry[key]
            rows_by_stock.setdefault(stock_id, []).append(row)

    frames: dict[str, pd.DataFrame] = {}
    for stock_id, rows in rows_by_stock.items():
        df = pd.DataFrame(rows).set_index("date").sort_index()
        frames[stock_id] = df
    return frames


# ── feature engineering ─────────────────────────────────────────────────────


def build_feature_frame(
    ohlc: pd.DataFrame,
    *,
    chip_df: pd.DataFrame | None = None,
    margin_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
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

    # Chip-derived features: real data when available, neutral fallback otherwise.
    if chip_df is not None and not chip_df.empty and "foreign_net" in chip_df.columns:
        streak = foreign_net_streak(chip_df["foreign_net"].astype(float))
        df["foreign_net_streak"] = streak.reindex(df.index, method="ffill").fillna(0).astype(int)
    else:
        df["foreign_net_streak"] = 0

    if (
        margin_df is not None
        and not margin_df.empty
        and "margin_balance" in margin_df.columns
    ):
        change = margin_n_day_change(margin_df["margin_balance"].astype(float), n=5)
        df["margin_balance_5d_change"] = change.reindex(df.index, method="ffill")
    else:
        df["margin_balance_5d_change"] = 0.0

    # News / limit-up still defaulted (news backfill = TASK-D01d, not in this prep).
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


def build_market_ohlc_proxy(
    feature_frames: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    """Cross-section mean of universe OHLC → proxy market index.

    Used by regime classifier (needs full OHLC, not just close) when no
    real weighted_index series is loaded.
    """
    if not feature_frames:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    parts: dict[str, list[pd.Series]] = {c: [] for c in
                                          ("open", "high", "low", "close", "volume")}
    for f in feature_frames.values():
        for col in parts:
            if col in f.columns:
                parts[col].append(f[col])
    proxy = pd.DataFrame(
        {col: pd.concat(parts[col], axis=1).mean(axis=1) for col in parts}
    )
    return proxy.sort_index()


# ── regime-gated entry ──────────────────────────────────────────────────────


def make_regime_gated_entry_factory(
    *,
    inner_factory: callable,
    market_ohlc: pd.DataFrame,
):
    """Wrap an entry-decider factory so each decision first checks regime.

    BEAR / RANGE / unknown → short-circuit return (no signal) without
    invoking the inner decider. BULL → delegate to inner.
    """
    def factory(stock_id: str, frame: pd.DataFrame):
        inner = inner_factory(stock_id, frame)

        def decider(today, row, has_position):
            passes, _reason = evaluate_regime_for_signal(market_ohlc, today)
            if not passes:
                return None
            return inner(today, row, has_position)

        return decider

    return factory


# ── benchmarks (lightweight) ────────────────────────────────────────────────


def equal_weight_total_return(
    feature_frames: Mapping[str, pd.DataFrame],
    *,
    oos_dates: tuple[pd.Timestamp, pd.Timestamp] | None = None,
) -> float:
    """Universe equal-weight buy-and-hold return.

    If ``oos_dates`` is provided, restrict each stock's window to
    ``[start, end]`` so the benchmark spans the same period as the
    strategy's OOS trading window — otherwise comparison is apples-to-
    oranges (e.g., 2-year benchmark vs. 9-month strategy).
    """
    rets: list[float] = []
    for f in feature_frames.values():
        df = f
        if oos_dates is not None:
            start, end = oos_dates
            df = f.loc[pd.Timestamp(start) : pd.Timestamp(end)]
        if len(df) < 2:
            continue
        start_close = float(df["close"].iloc[0])
        end_close = float(df["close"].iloc[-1])
        if start_close == 0:
            continue
        rets.append(end_close / start_close - 1.0)
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
    chip_frames = load_chip_frames(data_dir)
    margin_frames = load_margin_frames(data_dir)
    logger.info(
        "loaded chips for %d stocks, margin for %d stocks",
        len(chip_frames), len(margin_frames),
    )
    feature_frames = {
        sid: build_feature_frame(
            f, chip_df=chip_frames.get(sid), margin_df=margin_frames.get(sid)
        )
        for sid, f in ohlc_frames.items()
    }
    feature_frames = {sid: f for sid, f in feature_frames.items() if not f.empty}
    market_state = build_market_state(feature_frames)

    # 0050 OHLC as proxy for market_index AND etf_total_return (price-only;
    # IR0003 含息 backfill not yet done — see caveats).
    market_proxy_ohlc, etf_close = load_market_proxy_from_disk(data_dir, stock_id="0050")
    if not market_proxy_ohlc.empty:
        market_ohlc = market_proxy_ohlc
        logger.info("using 0050 as market_index / regime proxy (%d rows)",
                    len(market_proxy_ohlc))
    else:
        # Fallback to universe-mean proxy if 0050 unavailable.
        market_ohlc = build_market_ohlc_proxy(feature_frames)
        logger.warning("0050 unavailable — falling back to universe-mean market proxy")

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

    def base_entry_factory(stock_id: str, frame: pd.DataFrame):
        return make_entry_decider(
            feature_df=frame,
            market_state=market_state,
            target_shares=target_shares,
        )

    entry_factory = make_regime_gated_entry_factory(
        inner_factory=base_entry_factory,
        market_ohlc=market_ohlc,
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
        include_is=True,
    )
    logger.info(
        "backtest done: OOS trades=%d, IS trades=%d",
        len(result.all_trades), len(result.is_all_trades),
    )

    initial_capital = initial_cash_per_stock * len(feature_frames)
    metrics = summarize_performance(
        trades=result.all_trades,
        equity=result.combined_equity if not result.combined_equity.empty
        else pd.Series([initial_capital, initial_capital]),
        initial_capital=initial_capital,
    )

    oos_span_start = pd.Timestamp(min(w.oos_start for w in windows))
    oos_span_end = pd.Timestamp(max(w.oos_end for w in windows))

    # Real benchmark curves via compute_benchmarks (when market proxy present).
    benchmark_curves: dict[str, pd.Series] = {}
    bench_returns: dict[str, float] = {
        "weighted_index": 0.0,
        "etf_total_return": 0.0,
        "equal_weight_universe": 0.0,
        "ma_strategy": 0.0,
        "cash": 0.0,
    }
    if not market_proxy_ohlc.empty and not etf_close.empty:
        try:
            benchmark_curves = compute_benchmarks(
                market_index=market_proxy_ohlc,
                etf_total_return=etf_close,
                universe_daily=ohlc_frames,
            )
            bench_returns = benchmark_period_returns(
                benchmark_curves, period=(oos_span_start, oos_span_end)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("compute_benchmarks failed: %s — using fallbacks", exc)

    # Equal-weight fallback (in case compute_benchmarks 不可用).
    if bench_returns["equal_weight_universe"] == 0.0:
        bench_returns["equal_weight_universe"] = equal_weight_total_return(
            feature_frames, oos_dates=(oos_span_start, oos_span_end)
        )

    weighted_idx_ret = bench_returns["weighted_index"]
    etf_ret = bench_returns["etf_total_return"]

    # OOS/IS ratio via D03e helper (returns 0.0 when IS curve empty).
    oos_is = compute_oos_is_ratio_from_result(result)

    # Regime coverage across all OOS windows.
    oos_ranges = [(w.oos_start, w.oos_end) for w in windows]
    coverage = count_regime_coverage(oos_ranges, market_ohlc)

    decision_input = DecisionInput(
        metrics=metrics,
        oos_is_ratio=oos_is,
        top5_excluded_return=metrics.total_return,  # naive — pending top-N exclusion
        beats_weighted_index=metrics.total_return > weighted_idx_ret,
        beats_etf_0050=metrics.total_return > etf_ret,
        oos_alpha=metrics.total_return - weighted_idx_ret,
        regime_coverage_bull=coverage.bull,
        regime_coverage_bear=coverage.bear,
        regime_coverage_range=coverage.range,
    )
    decision = evaluate_v2_thresholds(decision_input)

    md = render_backtest_report(
        metrics=metrics,
        benchmarks_table={
            "weighted_index (0050 proxy)": bench_returns["weighted_index"],
            "etf_total_return (0050 proxy)": bench_returns["etf_total_return"],
            "equal_weight_universe": bench_returns["equal_weight_universe"],
            "ma_strategy (on 0050)": bench_returns["ma_strategy"],
            "cash": bench_returns["cash"],
        },
        decision=decision,
        manifest={**manifest, "n_trades": metrics.n_trades,
                  "n_windows": len(result.window_results),
                  "experiment_id": result.experiment_id or "(none)"},
    )

    # Caveats block prepended — updated for V1 重判決 (post-backfill, post-IS).
    caveats = [
        "## ⚠️ 報告限制",
        "",
        f"- **Chip 資料覆蓋**: {len(chip_frames)} 檔；**Margin 資料覆蓋**: {len(margin_frames)} 檔。",
        "- **Universe vs market 脫鉤**: 39 檔小型股 OOS 9mo mean ≈ +233%；同期 0050 兩年 -38% 後 OOS 反彈 +67%。",
        "  → universe 大幅 outperform 0050 → equal_weight 166% vs 0050 67%。survivorship bias + 大小盤脫鉤雙重影響。",
        "  → 真正解法：接 TWSE 完整 listed + delisted 名單做 universe（V2 §0.2 全規則）。",
        "- **Regime gate 過嚴**: 改用 0050 OHLC 作 regime classifier 後，OOS 期間 0050 close<MA200 → 全 3 個 OOS window labeled BEAR → gate 擋下 18/19 訊號，剩 1 trade。",
        "  → 當策略 universe 與 regime proxy 脫鉤時，gate 變成「禁止交易」開關。需重思 gate 設計（per-stock regime?或放寬 allowed regime?）。",
        "- **News features 仍 neutral default**（TASK-D01d news cron 未實作，RSS 無歷史）→ news_severity / is_limit_up 永遠 0/False。",
        "- **Benchmarks**: weighted_index / etf_total_return 兩槽位皆用 **0050 raw OHLC 作 proxy**（含息 IR0003 backfill 未做；0050 也未做 dividend adjustment）→ price-only 近似。",
        "- **Top-N excluded return** 採 naive 等同 total_return（未做真實 top-5 排除）。",
        "- **本報告 V1 重判決（post-D01c backfill / IS-extended / regime-gated / equity-fix / real-benchmark）**；屬 V2 §6.1 第二次量化判決。FAIL 主因為 universe-regime 脫鉤導致 n_trades=1，需重設計 regime gate 或 universe 選擇。",
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
