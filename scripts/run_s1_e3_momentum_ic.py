"""TASK-S1-E3 — C2 cross-sectional momentum IC research experiment.

Computes IC and decile spread for the J–T 12-1m momentum feature against 1m
forward return, in both raw and sector-neutral form. Sector is inferred from
the TWSE stock-id 2-digit prefix.

Usage:
    python -m scripts.run_s1_e3_momentum_ic \
        --data-dir data \
        --out analysis/s1_e3_momentum_ic_report.md
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Mapping

import pandas as pd

from src.signals.ic_analysis import IC_THRESHOLDS, compute_ic, meets_ic_threshold
from src.signals.sector_neutral import (
    compute_12_1m_return,
    compute_forward_return,
    cost_adjusted_decile_spread,
    decile_spread,
    infer_sector,
    sector_neutralize,
)

logger = logging.getLogger("autofetchstock.scripts.s1_e3")

FORWARD_HORIZON = 21  # ~1 month
SKIP = 21
LOOKBACK = 252
DEFAULT_MONTHLY_COST = 0.006  # 60 bp per round-trip × 1 rebalance per month
IC_HORIZON_KEY = 20  # nearest entry in IC_THRESHOLDS for the 21-day horizon


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


# ── orchestration ──────────────────────────────────────────────────────────


def run_momentum_ic_experiment(
    *,
    data_dir: Path,
    output_path: Path,
    monthly_cost: float = DEFAULT_MONTHLY_COST,
) -> dict[str, dict[str, float]]:
    ohlc = load_daily_ohlc_panel(data_dir)
    if ohlc.empty:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            "# C2 Cross-sectional Momentum IC\n\n"
            "No usable OHLC data found.\n"
        )
        return {}

    closes = ohlc["close"].astype(float).sort_index()
    feature = compute_12_1m_return(closes, skip=SKIP, lookback=LOOKBACK)
    forward = compute_forward_return(closes, horizon=FORWARD_HORIZON)

    stock_ids = feature.index.get_level_values("stock_id")
    sectors = pd.Series(
        [infer_sector(sid) for sid in stock_ids],
        index=feature.index,
        name="sector",
    )

    raw_ic = compute_ic(feature, forward)
    raw_spread = decile_spread(feature, forward, n_buckets=10)
    raw_spread_cost = cost_adjusted_decile_spread(
        feature, forward, n_buckets=10, monthly_cost=monthly_cost
    )

    feat_neutral = sector_neutralize(feature, sectors)
    sn_ic = compute_ic(feat_neutral, forward)
    sn_spread = decile_spread(feat_neutral, forward, n_buckets=10)
    sn_spread_cost = cost_adjusted_decile_spread(
        feat_neutral, forward, n_buckets=10, monthly_cost=monthly_cost
    )

    raw_passes = _passes_gate(raw_ic["ic_mean"], raw_spread_cost)
    sn_passes = _passes_gate(sn_ic["ic_mean"], sn_spread_cost)

    payload: dict[str, dict[str, float]] = {
        "raw": {
            **raw_ic,
            "decile_spread": raw_spread,
            "decile_spread_cost_adj": raw_spread_cost,
            "passes_gate": float(raw_passes),
        },
        "sector_neutral": {
            **sn_ic,
            "decile_spread": sn_spread,
            "decile_spread_cost_adj": sn_spread_cost,
            "passes_gate": float(sn_passes),
        },
    }

    markdown = render_momentum_ic_report(
        payload,
        n_stocks=len(ohlc.index.get_level_values("stock_id").unique()),
        n_sectors=len(set(sectors.dropna())),
        start=ohlc.index.get_level_values("date").min(),
        end=ohlc.index.get_level_values("date").max(),
        monthly_cost=monthly_cost,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown)
    return payload


def render_momentum_ic_report(
    payload: Mapping[str, Mapping[str, float]],
    *,
    n_stocks: int,
    n_sectors: int,
    start: pd.Timestamp,
    end: pd.Timestamp,
    monthly_cost: float,
) -> str:
    ic_threshold = IC_THRESHOLDS[IC_HORIZON_KEY]
    lines = [
        "# C2 Cross-sectional Momentum IC",
        "",
        f"- Universe size: **{n_stocks}** stocks across **{n_sectors}** sector buckets "
        "(2-digit TWSE stock-id prefix)",
        f"- Period: {start.date().isoformat()} ~ {end.date().isoformat()}",
        f"- Feature: 12-1m return (skip={SKIP}, lookback={LOOKBACK} trading days)",
        f"- Forward return horizon: {FORWARD_HORIZON} trading days",
        f"- Gate: |ic_mean| >= {ic_threshold:.3f} (V2 §1 horizon 20) "
        f"AND cost-adjusted decile spread > 0",
        f"- Monthly turnover cost assumption: {monthly_cost*1e4:.0f} bp / rebalance",
        f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Results (IC + Decile spread)",
        "",
        "| variant | ic_mean | ic_ir | p_value | n_periods | "
        "decile_spread | decile_spread_cost_adj | passes_gate |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for variant in ("raw", "sector_neutral"):
        row = payload[variant]
        lines.append(
            f"| {variant} | "
            f"{_fmt(row['ic_mean'], 4)} | "
            f"{_fmt(row['ic_ir'], 3)} | "
            f"{_fmt(row['p_value'], 4)} | "
            f"{int(row['n_periods'])} | "
            f"{_fmt(row['decile_spread'], 4)} | "
            f"{_fmt(row['decile_spread_cost_adj'], 4)} | "
            f"{'PASS' if row['passes_gate'] >= 1.0 else 'FAIL'} |"
        )
    lines.extend(
        [
            "",
            "## Sector-neutral note",
            "",
            "Sector buckets are inferred from TWSE 4-digit stock-id prefix (first two",
            "digits). This is a coarse heuristic — accurate for the dominant industry",
            "groupings (11xx 水泥, 12xx 食品, 23-24xx 電子/半導體, 28xx 金融, etc.) but",
            "does not distinguish sub-industries. If raw IC passes and sector-neutral",
            "fails, the alpha is likely sector beta and should be rejected.",
            "",
        ]
    )
    return "\n".join(lines)


# ── internals ──────────────────────────────────────────────────────────────


def _passes_gate(ic_mean: float, spread_cost_adj: float) -> bool:
    if pd.isna(ic_mean) or pd.isna(spread_cost_adj):
        return False
    if not meets_ic_threshold(float(ic_mean), horizon_days=IC_HORIZON_KEY):
        return False
    return spread_cost_adj > 0.0


def _empty_ohlc_panel() -> pd.DataFrame:
    idx = pd.MultiIndex.from_arrays([[], []], names=["date", "stock_id"])
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"], index=idx)


def _fmt(value: float | None, digits: int) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.{digits}f}"


def main() -> int:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Run S1-E3 momentum IC experiment.")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("analysis/s1_e3_momentum_ic_report.md"),
    )
    parser.add_argument("--monthly-cost", type=float, default=DEFAULT_MONTHLY_COST)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    payload = run_momentum_ic_experiment(
        data_dir=args.data_dir,
        output_path=args.out,
        monthly_cost=args.monthly_cost,
    )
    logger.info("done - variants=%d report=%s", len(payload), args.out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
