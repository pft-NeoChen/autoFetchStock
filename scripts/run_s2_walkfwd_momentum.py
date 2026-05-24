"""TASK-S2-WALKFWD — E3 momentum walk-forward IC + real sector-neutral.

Slices the universe into IS 12mo / OOS 3mo / 15bd-embargo windows (same recipe
as V1), computes the J–T 12-1m momentum feature and 21d forward return, and
calculates IC separately within each window's OOS slice. Sector neutralisation
uses the real TWSE industry mapping produced by TASK-S2-SECTOR.

Final ``verdict`` follows STRATEGY_REVIEW.md §E.3:
    - ic_mean (sector-neutral, OOS mean across windows) ≥ 0.04 → UNLOCK
    - 0.02 ≤ ic_mean < 0.04                                   → UNCERTAIN
    - ic_mean < 0.02                                          → DEAD

Usage:
    python -m scripts.run_s2_walkfwd_momentum \
        --data-dir data \
        --sector-map analysis/sector_map.json \
        --out analysis/s2_walkfwd_momentum_report.md
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from datetime import date, datetime
from pathlib import Path
from typing import Mapping

import pandas as pd

from src.backtest.walk_forward import WalkForwardWindow, walk_forward_windows
from src.signals.ic_analysis import compute_ic
from src.signals.sector_neutral import (
    compute_12_1m_return,
    compute_forward_return,
    sector_neutralize,
)
from src.universe.sector_mapping import get_sector, load_sector_mapping

logger = logging.getLogger("autofetchstock.scripts.s2_walkfwd")

FORWARD_HORIZON = 21
SKIP = 21
LOOKBACK = 252
UNLOCK_THRESHOLD = 0.04
DEAD_THRESHOLD = 0.02


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


# ── per-window IC ──────────────────────────────────────────────────────────


def compute_window_ic(
    *,
    feature: pd.Series,
    forward: pd.Series,
    oos_start: date,
    oos_end: date,
) -> dict[str, float]:
    """Restrict feature/forward to ``[oos_start, oos_end]`` and compute IC."""
    start_ts = pd.Timestamp(oos_start)
    end_ts = pd.Timestamp(oos_end)

    dates = feature.index.get_level_values("date")
    mask = (dates >= start_ts) & (dates <= end_ts)
    f_slice = feature[mask]
    r_slice = forward.reindex(f_slice.index)
    return compute_ic(f_slice, r_slice)


def classify_walkfwd_verdict(ic_mean: float) -> str:
    """Apply §E.3 sprint 2 gate thresholds."""
    if ic_mean is None or (isinstance(ic_mean, float) and math.isnan(ic_mean)):
        return "DEAD"
    if ic_mean >= UNLOCK_THRESHOLD:
        return "UNLOCK"
    if ic_mean >= DEAD_THRESHOLD:
        return "UNCERTAIN"
    return "DEAD"


# ── orchestration ──────────────────────────────────────────────────────────


def run_walkfwd_momentum(
    *,
    data_dir: Path,
    sector_map_path: Path,
    output_path: Path,
    is_months: int = 12,
    oos_months: int = 3,
    embargo_business_days: int = 15,
) -> dict[str, object]:
    ohlc = load_daily_ohlc_panel(data_dir)
    if ohlc.empty:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            "# E3 Momentum Walk-Forward IC\n\n"
            "No usable OHLC data found.\n"
        )
        return {}

    closes = ohlc["close"].astype(float).sort_index()
    feature = compute_12_1m_return(closes, skip=SKIP, lookback=LOOKBACK)
    forward = compute_forward_return(closes, horizon=FORWARD_HORIZON)

    mapping = load_sector_mapping(sector_map_path)
    stock_ids = feature.index.get_level_values("stock_id")
    sectors = pd.Series(
        [get_sector(sid, mapping) for sid in stock_ids],
        index=feature.index,
        name="sector",
    )
    sn_feature = sector_neutralize(feature, sectors)

    dates = ohlc.index.get_level_values("date")
    windows = walk_forward_windows(
        start=dates.min().date(),
        end=dates.max().date(),
        is_months=is_months,
        oos_months=oos_months,
        embargo_business_days=embargo_business_days,
    )

    window_records: list[dict] = []
    raw_oos_ics: list[float] = []
    sn_oos_ics: list[float] = []
    for w in windows:
        raw_oos = compute_window_ic(
            feature=feature, forward=forward,
            oos_start=w.oos_start, oos_end=w.oos_end,
        )
        sn_oos = compute_window_ic(
            feature=sn_feature, forward=forward,
            oos_start=w.oos_start, oos_end=w.oos_end,
        )
        record = {
            "oos_start": w.oos_start.isoformat(),
            "oos_end": w.oos_end.isoformat(),
            "raw_ic_mean": raw_oos["ic_mean"],
            "sector_neutral_ic_mean": sn_oos["ic_mean"],
            "n_periods": raw_oos["n_periods"],
        }
        window_records.append(record)
        if not math.isnan(raw_oos["ic_mean"]):
            raw_oos_ics.append(raw_oos["ic_mean"])
        if not math.isnan(sn_oos["ic_mean"]):
            sn_oos_ics.append(sn_oos["ic_mean"])

    raw_mean = _mean(raw_oos_ics)
    sn_mean = _mean(sn_oos_ics)
    raw_std = _std(raw_oos_ics)
    sn_std = _std(sn_oos_ics)
    verdict = classify_walkfwd_verdict(sn_mean)

    payload: dict[str, object] = {
        "windows": window_records,
        "raw_oos_ic_mean": raw_mean,
        "raw_oos_ic_std": raw_std,
        "sector_neutral_oos_ic_mean": sn_mean,
        "sector_neutral_oos_ic_std": sn_std,
        "verdict": verdict,
        "n_windows": len(windows),
        "n_stocks": int(stock_ids.unique().size),
    }

    markdown = render_walkfwd_report(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown)
    return payload


def render_walkfwd_report(payload: Mapping[str, object]) -> str:
    sn_mean = payload["sector_neutral_oos_ic_mean"]
    raw_mean = payload["raw_oos_ic_mean"]
    lines = [
        "# E3 Momentum Walk-Forward IC",
        "",
        f"- Universe size: **{payload['n_stocks']}** stocks",
        f"- Windows: {payload['n_windows']} (IS 12mo / OOS 3mo / embargo 15 business days)",
        f"- Feature: 12-1m return (skip={SKIP}, lookback={LOOKBACK})",
        f"- Forward return horizon: {FORWARD_HORIZON} trading days",
        f"- Gate (§E.3): UNLOCK ≥ {UNLOCK_THRESHOLD:.2f}; "
        f"UNCERTAIN {DEAD_THRESHOLD:.2f}–{UNLOCK_THRESHOLD:.2f}; "
        f"DEAD < {DEAD_THRESHOLD:.2f}",
        f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Aggregate OOS IC (cross-window)",
        "",
        "| variant | ic_mean | ic_std |",
        "|---|---:|---:|",
        f"| Raw | {_fmt(raw_mean)} | {_fmt(payload['raw_oos_ic_std'])} |",
        f"| Sector-neutral (real TWSE mapping) | {_fmt(sn_mean)} | {_fmt(payload['sector_neutral_oos_ic_std'])} |",
        "",
        f"## Verdict: **{payload['verdict']}**",
        "",
    ]
    if payload["verdict"] == "UNLOCK":
        lines.append(
            "Sector-neutral OOS ic_mean clears the §E.3 0.04 threshold — sprint 2 "
            "follow-up tasks (UNIVERSE / PORTFOLIO / RANK-SE / BACKTEST) are now in scope."
        )
    elif payload["verdict"] == "UNCERTAIN":
        lines.append(
            "Sector-neutral OOS ic_mean lands in the 0.02–0.04 grey zone — do NOT commit "
            "to PORTFOLIO/RANK-SE infrastructure; consider C4 advisor accumulation or "
            "wider universe before re-attempting."
        )
    else:
        lines.append(
            "Sector-neutral OOS ic_mean < 0.02 — E3 is treated as an in-sample artifact. "
            "Sprint 2 closes. Sprint 3 candidates per §D.5: C4 advisor IC / C0b corporate "
            "actions / C3 volatility breakout / 補 infra (P02/X02/D04)."
        )
    lines.extend(
        [
            "",
            "## Per-window OOS IC",
            "",
            "| # | oos_start | oos_end | raw ic_mean | sector-neutral ic_mean | n_periods |",
            "|---:|---|---|---:|---:|---:|",
        ]
    )
    for i, rec in enumerate(payload["windows"], 1):
        lines.append(
            f"| {i} | {rec['oos_start']} | {rec['oos_end']} | "
            f"{_fmt(rec['raw_ic_mean'])} | {_fmt(rec['sector_neutral_ic_mean'])} | "
            f"{rec['n_periods']} |"
        )
    lines.append("")
    return "\n".join(lines)


# ── internals ──────────────────────────────────────────────────────────────


def _mean(values: list[float]) -> float:
    if not values:
        return float("nan")
    return sum(values) / len(values)


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return float("nan")
    m = _mean(values)
    var = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)


def _empty_ohlc_panel() -> pd.DataFrame:
    idx = pd.MultiIndex.from_arrays([[], []], names=["date", "stock_id"])
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"], index=idx)


def _fmt(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.4f}"


def main() -> int:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Run S2-WALKFWD momentum IC experiment.")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--sector-map", type=Path, default=Path("analysis/sector_map.json")
    )
    parser.add_argument(
        "--out", type=Path,
        default=Path("analysis/s2_walkfwd_momentum_report.md"),
    )
    parser.add_argument("--is-months", type=int, default=12)
    parser.add_argument("--oos-months", type=int, default=3)
    parser.add_argument("--embargo-business-days", type=int, default=15)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    payload = run_walkfwd_momentum(
        data_dir=args.data_dir,
        sector_map_path=args.sector_map,
        output_path=args.out,
        is_months=args.is_months,
        oos_months=args.oos_months,
        embargo_business_days=args.embargo_business_days,
    )
    logger.info("done - verdict=%s report=%s", payload.get("verdict"), args.out)
    return 0


# Silence unused-import lint for re-exports we still need to keep at top level
_ = WalkForwardWindow


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
