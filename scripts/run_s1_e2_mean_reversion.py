"""TASK-S1-E2 — C1-safe mean reversion research experiment.

Runs the oversold-pullback trigger through the common S1 event-study gate:

- 5d return < −1.5 × 20d daily-return volatility
- RSI(14) < 30
- per-stock regime ∈ {BULL, RANGE} (BEAR hard skip)
- not limit-down today (|ret_1d| < 9.9%)
- news_severity > −5 (optional column; missing → treated as 0)

Usage:
    python -m scripts.run_s1_e2_mean_reversion \
        --data-dir data \
        --out analysis/s1_e2_mean_reversion_report.md
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from src.backtest.regime_classifier import (
    DEFAULT_FAST_WINDOW,
    DEFAULT_SLOW_WINDOW,
    Regime,
    _label_from_row,
)
from src.features.rsi import rsi
from src.research.event_study import (
    EventStudyResult,
    GateVerdict,
    evaluate_event_study_gate,
    event_study,
)

logger = logging.getLogger("autofetchstock.scripts.s1_e2")


# Spec §D.4: 5d return < −1.5 × 20d vol
DEFAULT_VOL_MULTIPLIER = 1.5
DEFAULT_RSI_THRESHOLD = 30.0
DEFAULT_NEWS_FLOOR = -5.0
LIMIT_DOWN_THRESHOLD = -0.099  # close to TWSE −10% daily limit
RSI_WINDOW = 14
VOL_WINDOW = 20
RETURN_WINDOW = 5


@dataclass
class TriggerExperiment:
    name: str
    result: EventStudyResult
    verdict: GateVerdict
    n_raw_triggers: int
    trigger_dates: int
    bear_skipped: int


# ── loading ────────────────────────────────────────────────────────────────


def load_daily_ohlc_panel(data_dir: Path) -> pd.DataFrame:
    stocks_dir = data_dir / "stocks"
    rows: list[dict] = []
    if not stocks_dir.exists():
        return _empty_ohlc_panel()

    for path in sorted(stocks_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError:
            logger.warning("skip corrupt stock json: %s", path)
            continue
        stock_id = str(payload.get("stock_id") or path.stem)
        for row in payload.get("daily_data", []):
            if not isinstance(row, dict) or "date" not in row:
                continue
            out = {"date": pd.Timestamp(row["date"]), "stock_id": stock_id}
            for col in ("open", "high", "low", "close", "volume"):
                out[col] = float(row.get(col, float("nan")))
            rows.append(out)

    if not rows:
        return _empty_ohlc_panel()
    panel = pd.DataFrame(rows).set_index(["date", "stock_id"]).sort_index()
    return panel[["open", "high", "low", "close", "volume"]]


def load_news_severity_panel(data_dir: Path) -> pd.Series:
    """Optional news severity index keyed by (date, stock_id).

    Returns an empty Series if the corpus does not exist; the orchestrator
    treats missing values as 0 (neutral).
    """
    news_dir = data_dir / "news"
    if not news_dir.exists():
        return pd.Series(dtype=float)

    rows: list[dict] = []
    for path in sorted(news_dir.glob("**/*.json")):
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        date_raw = payload.get("date") or path.stem[:8]
        try:
            date = pd.Timestamp(date_raw)
        except (ValueError, TypeError):
            continue
        entries = payload.get("by_stock") or payload.get("news_severity") or {}
        if not isinstance(entries, dict):
            continue
        for stock_id, sev in entries.items():
            try:
                rows.append({"date": date, "stock_id": str(stock_id), "news_severity": float(sev)})
            except (ValueError, TypeError):
                continue
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows).set_index(["date", "stock_id"]).sort_index()
    return df["news_severity"]


# ── regime + feature construction ──────────────────────────────────────────


def classify_per_stock_regime(
    ohlc: pd.DataFrame,
    *,
    fast_window: int = DEFAULT_FAST_WINDOW,
    slow_window: int = DEFAULT_SLOW_WINDOW,
) -> pd.Series:
    """Per-stock regime labels using MA50/MA200 on each stock's own close."""
    close_wide = ohlc["close"].astype(float).unstack("stock_id").sort_index()
    ma_fast = close_wide.rolling(window=fast_window, min_periods=fast_window).mean()
    ma_slow = close_wide.rolling(window=slow_window, min_periods=slow_window).mean()

    bull = (close_wide > ma_slow) & (ma_fast > ma_slow)
    bear = (close_wide < ma_slow) & (ma_fast < ma_slow)
    labels = pd.DataFrame(
        Regime.RANGE.value,
        index=close_wide.index,
        columns=close_wide.columns,
        dtype=object,
    )
    labels = labels.where(~bull, Regime.BULL.value)
    labels = labels.where(~bear, Regime.BEAR.value)
    invalid = ma_fast.isna() | ma_slow.isna() | close_wide.isna()
    labels = labels.where(~invalid, None)

    out = labels.stack(dropna=False)
    out.index = out.index.set_names(["date", "stock_id"])
    out.name = "regime"
    return out.sort_index()


def _per_stock_transform(
    series: pd.Series,
    fn,
) -> pd.Series:
    wide = series.unstack("stock_id").sort_index()
    out_wide = fn(wide)
    out = out_wide.stack(dropna=False)
    out.index = out.index.set_names(["date", "stock_id"])
    return out.sort_index()


def build_mean_reversion_panel(
    ohlc: pd.DataFrame,
    *,
    news_severity: pd.Series | None = None,
) -> pd.DataFrame:
    """Compute per-(date, stock_id) inputs the trigger needs."""
    closes = ohlc["close"].astype(float).sort_index()
    log_close = np.log(closes)

    log_ret = _per_stock_transform(log_close, lambda w: w.diff())
    ret_1d = _per_stock_transform(closes, lambda w: w.pct_change(1))
    ret_5d = _per_stock_transform(closes, lambda w: w.pct_change(RETURN_WINDOW))
    vol_20d = _per_stock_transform(
        log_ret,
        lambda w: w.rolling(window=VOL_WINDOW, min_periods=VOL_WINDOW).std(ddof=0),
    )
    rsi_14 = _per_stock_transform(closes, lambda w: w.apply(lambda c: rsi(c, window=RSI_WINDOW)))
    regime = classify_per_stock_regime(ohlc)

    panel = pd.DataFrame(
        {
            "close": closes,
            "ret_1d": ret_1d,
            "ret_5d": ret_5d,
            "vol_20d": vol_20d,
            "rsi_14": rsi_14,
            "regime": regime,
        }
    )
    if news_severity is not None and not news_severity.empty:
        panel = panel.join(news_severity.rename("news_severity"), how="left")
    if "news_severity" not in panel.columns:
        panel["news_severity"] = 0.0
    panel["news_severity"] = panel["news_severity"].fillna(0.0)
    return panel


# ── trigger ────────────────────────────────────────────────────────────────


def mean_reversion_oversold(
    panel: pd.DataFrame,
    *,
    rsi_threshold: float = DEFAULT_RSI_THRESHOLD,
    vol_multiplier: float = DEFAULT_VOL_MULTIPLIER,
    news_floor: float = DEFAULT_NEWS_FLOOR,
    limit_down_threshold: float = LIMIT_DOWN_THRESHOLD,
) -> pd.Series:
    """Mask of (date, stock_id) where every C1-safe condition holds."""
    required = {"ret_5d", "vol_20d", "rsi_14", "regime", "ret_1d"}
    missing = required - set(panel.columns)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")

    ret_5d = panel["ret_5d"].astype(float)
    vol_20d = panel["vol_20d"].astype(float)
    rsi_14 = panel["rsi_14"].astype(float)
    ret_1d = panel["ret_1d"].astype(float)
    regime = panel["regime"].astype(object)
    news = panel.get("news_severity", pd.Series(0.0, index=panel.index)).astype(float).fillna(0.0)

    drop_extreme = ret_5d < -(vol_multiplier * vol_20d)
    oversold = rsi_14 < rsi_threshold
    allowed_regime = regime.isin({Regime.BULL.value, Regime.RANGE.value})
    not_limit_down = ret_1d > limit_down_threshold
    news_ok = news > news_floor

    mask = drop_extreme & oversold & allowed_regime & not_limit_down & news_ok
    return mask.fillna(False).astype(bool)


# ── orchestration ──────────────────────────────────────────────────────────


def run_mean_reversion_experiment(
    *,
    data_dir: Path,
    output_path: Path,
    horizons: tuple[int, ...] = (1, 3, 5),
) -> dict[str, TriggerExperiment]:
    ohlc = load_daily_ohlc_panel(data_dir)
    if ohlc.empty:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            "# C1-safe Mean Reversion Experiment\n\n"
            "No usable OHLC data found.\n"
        )
        return {}

    news_severity = load_news_severity_panel(data_dir)
    panel = build_mean_reversion_panel(ohlc, news_severity=news_severity)

    mask = mean_reversion_oversold(panel).reindex(ohlc.index, fill_value=False)

    # Diagnostic: how many trigger candidates were dropped solely by BEAR gate?
    bear_skipped = _count_bear_skips(panel)

    result = event_study(mask, ohlc, horizons=horizons)
    verdict = evaluate_event_study_gate(
        result, horizon=5 if 5 in horizons else max(horizons)
    )

    payload = {
        "mean_reversion_oversold": TriggerExperiment(
            name="mean_reversion_oversold",
            result=result,
            verdict=verdict,
            n_raw_triggers=int(mask.sum()),
            trigger_dates=int(mask[mask].index.get_level_values("date").nunique())
            if mask.any()
            else 0,
            bear_skipped=bear_skipped,
        )
    }

    markdown = render_mean_reversion_report(
        payload,
        n_stocks=len(ohlc.index.get_level_values("stock_id").unique()),
        start=ohlc.index.get_level_values("date").min(),
        end=ohlc.index.get_level_values("date").max(),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown)
    return payload


def render_mean_reversion_report(
    payload: Mapping[str, TriggerExperiment],
    *,
    n_stocks: int,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> str:
    lines = [
        "# C1-safe Mean Reversion Experiment",
        "",
        f"- Universe size: **{n_stocks}** stocks",
        f"- Period: {start.date().isoformat()} ~ {end.date().isoformat()}",
        "- Trigger: 5d return < −1.5 × 20d vol AND RSI(14) < 30 AND "
        "regime ∈ {BULL, RANGE} AND not limit-down AND news_severity > −5",
        "- Gate: n_events >= 100, cost-adjusted 5d mean >= 50bp, "
        "cost-adjusted 5d median > 0bp, hit-rate spread >= 5pp, "
        "top5% excluded mean > 0bp",
        f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Trigger Frequency",
        "",
        "| trigger | raw_triggers | trigger_dates |",
        "|---|---:|---:|",
    ]
    for exp in payload.values():
        lines.append(f"| {exp.name} | {exp.n_raw_triggers} | {exp.trigger_dates} |")

    lines.extend(
        [
            "",
            "## BEAR skip diagnostic",
            "",
            "Count of would-be triggers (every non-regime condition met) dropped solely",
            "because per-stock regime was BEAR. C1-safe spec hard-skips BEAR; this row is",
            "informational only and is **not** a gate input.",
            "",
            "| trigger | bear_skipped |",
            "|---|---:|",
        ]
    )
    for exp in payload.values():
        lines.append(f"| {exp.name} | {exp.bear_skipped} |")

    lines.extend(
        [
            "",
            "## Event Study Gate",
            "",
            "| trigger | pass | n_events | hit_rate | base_rate | "
            "mean_5d_bp | median_5d_bp | cost_adj_mean_5d_bp | "
            "cost_adj_median_5d_bp | top5_excluded_5d_bp | reasons |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for exp in payload.values():
        result = exp.result
        reasons = "; ".join(exp.verdict.reasons) if exp.verdict.reasons else ""
        lines.append(
            f"| {exp.name} | {'PASS' if exp.verdict.passed else 'FAIL'} | "
            f"{result.n_events} | {result.hit_rate:.3f} | {result.base_rate:.3f} | "
            f"{_fmt_bp(result.mean_return_bp.get(5))} | "
            f"{_fmt_bp(result.median_return_bp.get(5))} | "
            f"{_fmt_bp(result.cost_adjusted_mean_bp.get(5))} | "
            f"{_fmt_bp(result.cost_adjusted_median_bp.get(5))} | "
            f"{_fmt_bp(result.top5pct_excluded_mean_bp.get(5))} | {reasons} |"
        )
    lines.append("")
    return "\n".join(lines)


# ── internals ──────────────────────────────────────────────────────────────


def _count_bear_skips(panel: pd.DataFrame) -> int:
    """Count rows where every condition except regime would have fired and regime is BEAR."""
    try:
        ret_5d = panel["ret_5d"].astype(float)
        vol_20d = panel["vol_20d"].astype(float)
        rsi_14 = panel["rsi_14"].astype(float)
        ret_1d = panel["ret_1d"].astype(float)
        news = panel.get("news_severity", pd.Series(0.0, index=panel.index)).astype(float).fillna(0.0)
    except KeyError:
        return 0
    non_regime = (
        (ret_5d < -(DEFAULT_VOL_MULTIPLIER * vol_20d))
        & (rsi_14 < DEFAULT_RSI_THRESHOLD)
        & (ret_1d > LIMIT_DOWN_THRESHOLD)
        & (news > DEFAULT_NEWS_FLOOR)
    )
    bear = panel["regime"].astype(object) == Regime.BEAR.value
    return int((non_regime & bear).fillna(False).sum())


def _empty_ohlc_panel() -> pd.DataFrame:
    idx = pd.MultiIndex.from_arrays([[], []], names=["date", "stock_id"])
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"], index=idx)


def _fmt_bp(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.2f}"


def main() -> int:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Run S1-E2 mean-reversion event study.")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("analysis/s1_e2_mean_reversion_report.md"),
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    payload = run_mean_reversion_experiment(data_dir=args.data_dir, output_path=args.out)
    logger.info("done - triggers=%d report=%s", len(payload), args.out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
