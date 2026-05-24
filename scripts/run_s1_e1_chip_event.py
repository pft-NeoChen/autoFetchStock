"""TASK-S1-E1 - C0a chip event-driven research experiment.

Runs four chip/margin event triggers through the common S1 event-study gate:

- foreign_anomaly_buy
- invtrust_anomaly_buy
- foreign_reverse_to_buy
- margin_rapid_drop

Usage:
    python -m scripts.run_s1_e1_chip_event \
        --data-dir data \
        --out analysis/s1_e1_chip_event_report.md
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Collection, Mapping

import pandas as pd

from src.research.event_study import (
    EventStudyResult,
    GateVerdict,
    evaluate_event_study_gate,
    event_study,
)

logger = logging.getLogger("autofetchstock.scripts.s1_e1")


@dataclass
class TriggerExperiment:
    name: str
    result: EventStudyResult
    verdict: GateVerdict
    n_raw_triggers: int
    trigger_dates: int


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


def load_chip_frames(
    data_dir: Path,
    *,
    stock_ids: Collection[str] | None = None,
) -> dict[str, pd.DataFrame]:
    return _load_daily_snapshot_frames(
        data_dir / "chips",
        payload_key="t86",
        columns=("foreign_net", "trust_net", "dealer_net", "all_net"),
        stock_ids=stock_ids,
    )


def load_margin_frames(
    data_dir: Path,
    *,
    stock_ids: Collection[str] | None = None,
) -> dict[str, pd.DataFrame]:
    return _load_daily_snapshot_frames(
        data_dir / "margin",
        payload_key="margin",
        columns=("margin_balance", "short_balance"),
        stock_ids=stock_ids,
    )


def build_chip_event_panel(
    chip_frames: Mapping[str, pd.DataFrame],
    margin_frames: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    records: list[pd.DataFrame] = []
    stock_ids = sorted(set(chip_frames) | set(margin_frames))
    for stock_id in stock_ids:
        pieces: list[pd.DataFrame] = []
        if stock_id in chip_frames and not chip_frames[stock_id].empty:
            pieces.append(chip_frames[stock_id].copy())
        if stock_id in margin_frames and not margin_frames[stock_id].empty:
            pieces.append(margin_frames[stock_id].copy())
        if not pieces:
            continue
        merged = pd.concat(pieces, axis=1).sort_index()
        merged["stock_id"] = stock_id
        records.append(merged.reset_index(names="date"))

    if not records:
        idx = pd.MultiIndex.from_arrays([[], []], names=["date", "stock_id"])
        return pd.DataFrame(index=idx)

    panel = pd.concat(records, ignore_index=True)
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.set_index(["date", "stock_id"]).sort_index()
    return panel


# ── triggers ───────────────────────────────────────────────────────────────


def foreign_anomaly_buy(
    panel: pd.DataFrame,
    *,
    window: int = 60,
    sigma: float = 2.0,
) -> pd.Series:
    return _positive_anomaly(panel, "foreign_net", window=window, sigma=sigma)


def invtrust_anomaly_buy(
    panel: pd.DataFrame,
    *,
    window: int = 60,
    sigma: float = 2.0,
) -> pd.Series:
    return _positive_anomaly(panel, "trust_net", window=window, sigma=sigma)


def foreign_reverse_to_buy(
    panel: pd.DataFrame,
    *,
    lookback: int = 5,
) -> pd.Series:
    if "foreign_net" not in panel.columns:
        return _false_mask(panel)

    def per_stock(series: pd.Series) -> pd.Series:
        prev_all_negative = (
            series.astype(float)
            .shift(1)
            .rolling(window=lookback, min_periods=lookback)
            .apply(lambda values: bool((values < 0).all()), raw=False)
            .astype(bool)
        )
        return (series.astype(float) > 0) & prev_all_negative

    return _group_transform(panel["foreign_net"], per_stock)


def margin_rapid_drop(
    panel: pd.DataFrame,
    *,
    change_days: int = 5,
    window: int = 60,
    sigma: float = 2.0,
) -> pd.Series:
    if "margin_balance" not in panel.columns:
        return _false_mask(panel)

    def per_stock(series: pd.Series) -> pd.Series:
        change = series.astype(float) - series.astype(float).shift(change_days)
        mean = change.shift(1).rolling(window=window, min_periods=window).mean()
        std = change.shift(1).rolling(window=window, min_periods=window).std(ddof=0)
        return change < (mean - sigma * std)

    return _group_transform(panel["margin_balance"], per_stock)


# ── orchestration ──────────────────────────────────────────────────────────


def run_chip_event_experiment(
    *,
    data_dir: Path,
    output_path: Path,
    horizons: tuple[int, ...] = (1, 3, 5),
) -> dict[str, TriggerExperiment]:
    ohlc = load_daily_ohlc_panel(data_dir)
    stock_ids = set(ohlc.index.get_level_values("stock_id").unique()) if not ohlc.empty else set()
    chip_frames = load_chip_frames(data_dir, stock_ids=stock_ids)
    margin_frames = load_margin_frames(data_dir, stock_ids=stock_ids)
    panel = build_chip_event_panel(chip_frames, margin_frames)

    if ohlc.empty or panel.empty:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            "# C0a Chip Event-Driven Experiment\n\n"
            "No usable OHLC/chip data found.\n"
        )
        return {}

    common_index = ohlc.index.intersection(panel.index)
    if common_index.empty:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            "# C0a Chip Event-Driven Experiment\n\n"
            "No usable OHLC/chip data overlap found.\n"
        )
        return {}

    ohlc = ohlc.loc[common_index].sort_index()
    panel = panel.loc[common_index].sort_index()
    trigger_builders = {
        "foreign_anomaly_buy": foreign_anomaly_buy,
        "invtrust_anomaly_buy": invtrust_anomaly_buy,
        "foreign_reverse_to_buy": foreign_reverse_to_buy,
        "margin_rapid_drop": margin_rapid_drop,
    }

    payload: dict[str, TriggerExperiment] = {}
    for name, builder in trigger_builders.items():
        mask = builder(panel).reindex(ohlc.index, fill_value=False)
        result = event_study(mask, ohlc, horizons=horizons)
        verdict = evaluate_event_study_gate(result, horizon=5 if 5 in horizons else max(horizons))
        payload[name] = TriggerExperiment(
            name=name,
            result=result,
            verdict=verdict,
            n_raw_triggers=int(mask.sum()),
            trigger_dates=int(mask[mask].index.get_level_values("date").nunique()) if mask.any() else 0,
        )

    markdown = render_chip_event_report(
        payload,
        n_stocks=len(ohlc.index.get_level_values("stock_id").unique()),
        start=ohlc.index.get_level_values("date").min(),
        end=ohlc.index.get_level_values("date").max(),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown)
    return payload


def render_chip_event_report(
    payload: Mapping[str, TriggerExperiment],
    *,
    n_stocks: int,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> str:
    lines = [
        "# C0a Chip Event-Driven Experiment",
        "",
        f"- Universe size: **{n_stocks}** stocks",
        f"- Period: {start.date().isoformat()} ~ {end.date().isoformat()}",
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


def _load_daily_snapshot_frames(
    snapshot_dir: Path,
    *,
    payload_key: str,
    columns: tuple[str, ...],
    stock_ids: Collection[str] | None = None,
) -> dict[str, pd.DataFrame]:
    if not snapshot_dir.exists():
        return {}
    allowed = set(stock_ids) if stock_ids is not None else None
    rows_by_stock: dict[str, list[dict]] = {}
    for path in sorted(snapshot_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError:
            logger.warning("skip corrupt json: %s", path)
            continue
        day = _snapshot_date(payload, path)
        rows = payload.get(payload_key) or {}
        if not isinstance(rows, dict):
            continue
        for stock_id, raw in rows.items():
            stock_id = str(stock_id)
            if allowed is not None and stock_id not in allowed:
                continue
            if not isinstance(raw, dict):
                continue
            row = {"date": day}
            for col in columns:
                if col in raw:
                    row[col] = float(raw[col])
            rows_by_stock.setdefault(stock_id, []).append(row)

    frames: dict[str, pd.DataFrame] = {}
    for stock_id, rows in rows_by_stock.items():
        df = pd.DataFrame(rows)
        if df.empty:
            continue
        df["date"] = pd.to_datetime(df["date"])
        frames[stock_id] = df.set_index("date").sort_index()
    return frames


def _snapshot_date(payload: dict, path: Path) -> pd.Timestamp:
    raw = payload.get("date")
    if raw:
        return pd.Timestamp(raw)
    return pd.Timestamp(f"{path.stem[:4]}-{path.stem[4:6]}-{path.stem[6:8]}")


def _empty_ohlc_panel() -> pd.DataFrame:
    idx = pd.MultiIndex.from_arrays([[], []], names=["date", "stock_id"])
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"], index=idx)


def _positive_anomaly(
    panel: pd.DataFrame,
    column: str,
    *,
    window: int,
    sigma: float,
) -> pd.Series:
    if column not in panel.columns:
        return _false_mask(panel)

    def per_stock(series: pd.Series) -> pd.Series:
        base = series.astype(float)
        mean = base.shift(1).rolling(window=window, min_periods=window).mean()
        std = base.shift(1).rolling(window=window, min_periods=window).std(ddof=0)
        return base > (mean + sigma * std)

    return _group_transform(panel[column], per_stock)


def _group_transform(series: pd.Series, fn) -> pd.Series:
    result = (
        series.groupby(level="stock_id", group_keys=False)
        .apply(lambda s: fn(s.droplevel("stock_id")).astype(bool))
    )
    result.index = series.index
    return result.astype(bool)


def _false_mask(panel: pd.DataFrame) -> pd.Series:
    return pd.Series(False, index=panel.index)


def _fmt_bp(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.2f}"


def main() -> int:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Run S1-E1 chip event-study experiment.")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--out", type=Path, default=Path("analysis/s1_e1_chip_event_report.md"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    payload = run_chip_event_experiment(data_dir=args.data_dir, output_path=args.out)
    logger.info("done - triggers=%d report=%s", len(payload), args.out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
