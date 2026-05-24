"""TASK-S1-E0 — V1 bootstrap sanity orchestrator.

Reads a V1 trades JSON file produced by ``scripts/run_backtest_v1.py
--dump-trades`` and runs a trade-level resample bootstrap (with replacement)
to produce 95% CIs for expectancy_bp / sharpe / profit_factor / n_trades on
both the IS and OOS trade lists.

Decision per `STRATEGY_REVIEW.md §D.4`:
- CI low > 0 → V1 has edge (extremely unlikely)
- CI contains 0 → uncertain (V1 baseline only, main effort on new strategies)
- CI high < 0 → truly dead (downgrade V1 to historical reference)

Usage:
    python -m scripts.run_s1_e0_v1_bootstrap \
        --trades data/v1_trades.json \
        --out analysis/s1_e0_v1_bootstrap_report.md
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

from src.research.trade_bootstrap import (
    BootstrapStat,
    bootstrap_trade_metrics,
)

logger = logging.getLogger("autofetchstock.scripts.s1_e0")


# ── loading ────────────────────────────────────────────────────────────────


def load_v1_trades(path: Path) -> tuple[list[dict], list[dict]]:
    """Return (oos_trades, is_trades) from a V1 dump produced by run_backtest_v1."""
    payload = json.loads(path.read_text())
    oos = payload.get("oos_trades") or []
    is_trades = payload.get("is_trades") or []
    if not isinstance(oos, list) or not isinstance(is_trades, list):
        raise ValueError(f"unexpected trades payload structure in {path}")
    return oos, is_trades


# ── orchestration ──────────────────────────────────────────────────────────


def run_v1_bootstrap_experiment(
    *,
    trades_path: Path,
    output_path: Path,
    n_iter: int = 100,
    seed: int = 42,
) -> dict[str, dict[str, BootstrapStat]]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not trades_path.exists():
        output_path.write_text(
            "# V1 Bootstrap Sanity\n\n"
            f"No V1 trades file at `{trades_path}`. "
            "Run `python -m scripts.run_backtest_v1 --dump-trades data/v1_trades.json` "
            "first.\n"
        )
        return {}

    oos, is_trades = load_v1_trades(trades_path)
    payload = {
        "oos": bootstrap_trade_metrics(oos, n_iter=n_iter, seed=seed),
        "is": bootstrap_trade_metrics(is_trades, n_iter=n_iter, seed=seed),
    }

    markdown = render_v1_bootstrap_report(
        payload,
        trades_path=trades_path,
        n_iter=n_iter,
        seed=seed,
    )
    output_path.write_text(markdown)
    return payload


def render_v1_bootstrap_report(
    payload: Mapping[str, Mapping[str, BootstrapStat]],
    *,
    trades_path: Path,
    n_iter: int,
    seed: int,
) -> str:
    lines = [
        "# V1 Bootstrap Sanity",
        "",
        f"- Trades source: `{trades_path}`",
        f"- Resample bootstrap (with replacement), n_iter={n_iter}, seed={seed}",
        "- 95% CI = (2.5%, 97.5%) quantile of bootstrap distribution",
        "- Decision: CI low > 0 → V1 edge; CI contains 0 → uncertain; CI high < 0 → dead",
        f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Results",
        "",
        "| segment | metric | point | ci_low | ci_high | verdict |",
        "|---|---|---:|---:|---:|---|",
    ]
    for segment in ("oos", "is"):
        stats = payload[segment]
        for metric in ("expectancy_bp", "sharpe", "profit_factor", "n_trades"):
            stat = stats[metric]
            verdict = _classify(metric, stat)
            lines.append(
                f"| {segment.upper()} | {metric} | "
                f"{_fmt(stat.point)} | {_fmt(stat.ci_low)} | {_fmt(stat.ci_high)} | "
                f"{verdict} |"
            )
    lines.append("")
    return "\n".join(lines)


# ── internals ──────────────────────────────────────────────────────────────


def _classify(metric: str, stat: BootstrapStat) -> str:
    if metric == "n_trades":
        return "-"
    if metric == "profit_factor":
        # neutral point is 1.0
        if stat.ci_low > 1.0:
            return "EDGE"
        if stat.ci_high < 1.0:
            return "DEAD"
        return "UNCERTAIN"
    # expectancy_bp, sharpe: neutral 0
    if stat.ci_low > 0:
        return "EDGE"
    if stat.ci_high < 0:
        return "DEAD"
    return "UNCERTAIN"


def _fmt(value: float) -> str:
    if value is None:
        return "-"
    try:
        fv = float(value)
    except (TypeError, ValueError):
        return "-"
    if fv != fv:  # NaN
        return "-"
    if fv == float("inf"):
        return "∞"
    if fv == float("-inf"):
        return "-∞"
    return f"{fv:.4f}"


def main() -> int:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Run S1-E0 V1 bootstrap sanity.")
    parser.add_argument("--trades", type=Path, default=Path("data/v1_trades.json"))
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("analysis/s1_e0_v1_bootstrap_report.md"),
    )
    parser.add_argument("--n-iter", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    payload = run_v1_bootstrap_experiment(
        trades_path=args.trades,
        output_path=args.out,
        n_iter=args.n_iter,
        seed=args.seed,
    )
    logger.info("done - segments=%d report=%s", len(payload), args.out)
    return 0


# Silence unused-import lint while keeping dataclasses helper exported.
_ = (asdict, is_dataclass)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
