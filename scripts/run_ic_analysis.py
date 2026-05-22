"""TASK-S01 (orchestrator) — Run IC analysis over the local universe.

Loads `data/stocks/*.json`, applies the FeatureStore + price/volume providers,
computes forward returns at 1d/5d/20d horizons, and renders an IC report to
``analysis/ic_report.md``.

Usage:
    python -m scripts.run_ic_analysis [--data-dir data] [--out analysis/ic_report.md]
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Mapping

import pandas as pd

from src.features.price_features import price_feature_providers
from src.features.store import FeatureStore
from src.features.volume_features import volume_feature_providers
from src.signals.ic_analysis import (
    IC_THRESHOLDS,
    compute_ic,
    meets_ic_threshold,
)

logger = logging.getLogger("autofetchstock.scripts.ic")


# ── data loading ────────────────────────────────────────────────────────────


def load_daily_frames(data_dir: Path) -> dict[str, pd.DataFrame]:
    stocks_dir = data_dir / "stocks"
    if not stocks_dir.exists():
        return {}
    frames: dict[str, pd.DataFrame] = {}
    for path in sorted(stocks_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError:
            logger.warning("skip corrupt json: %s", path)
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
        frames[payload.get("stock_id", path.stem)] = df[
            ["open", "high", "low", "close", "volume"]
        ].astype(float)
    return frames


def forward_returns(close: pd.Series, *, horizon: int) -> pd.Series:
    if horizon <= 0:
        raise ValueError("horizon must be positive")
    c = close.astype(float)
    return c.shift(-horizon) / c - 1.0


# ── report rendering ────────────────────────────────────────────────────────


def render_ic_report(
    payload: Mapping[str, Mapping[int, Mapping[str, float]]],
    *,
    n_stocks: int,
    start: date,
    end: date,
) -> str:
    horizons = sorted({h for stats in payload.values() for h in stats})
    lines = [
        "# IC Report (TASK-S01)",
        "",
        f"- Universe size: **{n_stocks}** stocks",
        f"- Period: {start.isoformat()} ~ {end.isoformat()}",
        f"- IC thresholds (V2 §1 修訂): {IC_THRESHOLDS}",
        "",
        "## Per-feature IC (Spearman, cross-sectional)",
        "",
    ]
    header = ["feature"]
    for h in horizons:
        header.extend([f"{h}d_ic_mean", f"{h}d_ic_ir", f"{h}d_p", f"{h}d_n", f"{h}d_pass"])
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")

    for feat, stats_by_h in sorted(payload.items()):
        row: list[str] = [feat]
        for h in horizons:
            s = stats_by_h.get(h, {})
            ic_mean = s.get("ic_mean", float("nan"))
            ic_ir = s.get("ic_ir", float("nan"))
            p = s.get("p_value", float("nan"))
            n = int(s.get("n_periods", 0))
            try:
                passes = meets_ic_threshold(ic_mean, horizon_days=h) and p < 0.05
            except ValueError:
                passes = False
            row.extend(
                [
                    f"{ic_mean:.3f}" if pd.notna(ic_mean) else "—",
                    f"{ic_ir:.2f}" if pd.notna(ic_ir) else "—",
                    f"{p:.3f}" if pd.notna(p) else "—",
                    f"{n}",
                    "PASS" if passes else "FAIL",
                ]
            )
        lines.append("| " + " | ".join(row) + " |")

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- IC is computed cross-sectionally per date, then summarised over the period.",
            "- PASS = abs(ic_mean) ≥ horizon threshold AND p-value < 0.05.",
            "- IC alone is not sufficient — check decay + monotonicity before trusting a feature.",
            f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
            "",
        ]
    )
    return "\n".join(lines)


# ── orchestrator ────────────────────────────────────────────────────────────


def run_ic_analysis(
    *,
    data_dir: Path,
    output_path: Path,
    horizons: Iterable[int] = (1, 5, 20),
    ma_windows: Iterable[int] = (5, 10, 20, 60),
    atr_window: int = 14,
    vol_window: int = 20,
) -> dict[str, dict[int, dict[str, float]]]:
    raw = load_daily_frames(data_dir)
    if not raw:
        raise RuntimeError(f"no daily data under {data_dir}/stocks")

    horizons_list = list(horizons)
    stock_ids = sorted(raw.keys())

    all_starts = [df.index.min() for df in raw.values() if not df.empty]
    all_ends = [df.index.max() for df in raw.values() if not df.empty]
    start = min(all_starts).date()
    end = max(all_ends).date()

    providers = price_feature_providers(
        ma_windows=tuple(ma_windows),
        atr_window=atr_window,
        vol_window=vol_window,
    ) + volume_feature_providers(window=vol_window, min_periods=max(2, vol_window // 2))

    store = FeatureStore(
        providers=providers,
        raw_daily=raw,
        universe_version="d01b-v1",
        corp_action_version="raw",
        git_commit="local",
        cache_dir=output_path.parent / "feature_store_cache",
    )
    df = store.build(stock_ids, start, end)

    # Forward returns per horizon — build a Series indexed by (date, stock_id).
    forward_by_h: dict[int, pd.Series] = {}
    fr_records: dict[int, list[tuple[pd.Timestamp, str, float]]] = {h: [] for h in horizons_list}
    for sid, frame in raw.items():
        for h in horizons_list:
            fr = forward_returns(frame["close"], horizon=h)
            for ts, val in fr.items():
                fr_records[h].append((ts, sid, val))
    for h, rec in fr_records.items():
        idx = pd.MultiIndex.from_tuples(
            [(t, s) for t, s, _ in rec], names=["date", "stock_id"]
        )
        forward_by_h[h] = pd.Series([v for _, _, v in rec], index=idx, dtype=float)

    # Compute IC per feature × horizon.
    payload: dict[str, dict[int, dict[str, float]]] = {}
    skip_cols = {"spike_severity"}  # categorical
    for col in df.columns:
        if col in skip_cols:
            continue
        feat = df[col].astype(float, errors="ignore")
        if not pd.api.types.is_numeric_dtype(feat):
            continue
        payload[col] = {}
        for h in horizons_list:
            payload[col][h] = compute_ic(feat, forward_by_h[h])

    markdown = render_ic_report(payload, n_stocks=len(stock_ids), start=start, end=end)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown)
    return payload


# ── CLI ─────────────────────────────────────────────────────────────────────


def main() -> int:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Run IC analysis over local universe.")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--out", type=Path, default=Path("analysis/ic_report.md"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    payload = run_ic_analysis(data_dir=args.data_dir, output_path=args.out)
    n_pass = sum(
        1
        for stats in payload.values()
        for h, s in stats.items()
        if (lambda v: not pd.isna(v) and abs(v) >= IC_THRESHOLDS.get(h, 1e9))(s.get("ic_mean"))
    )
    logger.info("done — features=%d, threshold-passing cells=%d, report=%s",
                len(payload), n_pass, args.out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
