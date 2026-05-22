"""TASK-D03c — Markdown backtest report renderer (V2 §6.1 結案文件)."""

from __future__ import annotations

from typing import Any, Mapping

from src.journal.decision import DecisionResult
from src.journal.performance import PerformanceMetrics

__all__ = ["render_backtest_report"]


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def _fmt_num(x: float, ndigits: int = 2) -> str:
    if x == float("inf"):
        return "∞"
    if x == float("-inf"):
        return "-∞"
    return f"{x:.{ndigits}f}"


def render_backtest_report(
    *,
    metrics: PerformanceMetrics,
    benchmarks_table: Mapping[str, float],
    decision: DecisionResult,
    manifest: Mapping[str, Any],
) -> str:
    verdict = "✅ PASS" if decision.passed else "❌ FAIL"
    lines: list[str] = []

    lines.append("# Backtest Report")
    lines.append("")
    lines.append(f"**Verdict**: {verdict}")
    lines.append("")

    # Manifest
    if manifest:
        lines.append("## Manifest")
        lines.append("")
        for k, v in manifest.items():
            lines.append(f"- **{k}**: {v}")
        lines.append("")

    # Performance metrics
    lines.append("## Performance Metrics")
    lines.append("")
    lines.append("| 指標 | 值 |")
    lines.append("|------|----|")
    lines.append(f"| 交易次數 | {metrics.n_trades} |")
    lines.append(f"| 總報酬 | {_fmt_pct(metrics.total_return)} |")
    lines.append(f"| Sharpe (年化) | {_fmt_num(metrics.sharpe)} |")
    lines.append(f"| Sortino (年化) | {_fmt_num(metrics.sortino)} |")
    lines.append(f"| Max Drawdown | {_fmt_pct(metrics.max_drawdown)} |")
    lines.append(f"| 勝率 | {_fmt_pct(metrics.win_rate)} |")
    lines.append(f"| Profit Factor | {_fmt_num(metrics.profit_factor)} |")
    lines.append(f"| 每筆期望值 (bp) | {_fmt_num(metrics.expectancy_bp)} |")
    lines.append(f"| Turnover | {_fmt_num(metrics.turnover)} |")
    lines.append("")

    # Benchmarks
    lines.append("## Benchmark 對照")
    lines.append("")
    lines.append("| Benchmark | 期間報酬 |")
    lines.append("|-----------|---------|")
    for name, ret in benchmarks_table.items():
        lines.append(f"| {name} | {_fmt_pct(ret)} |")
    lines.append("")

    # Decision
    lines.append("## V2 §6.1 量化門檻")
    lines.append("")
    lines.append("| Check | Pass |")
    lines.append("|-------|------|")
    for name, ok in decision.checks.items():
        lines.append(f"| {name} | {'✅' if ok else '❌'} |")
    lines.append("")

    if decision.reasons:
        lines.append("### 失敗原因")
        lines.append("")
        for r in decision.reasons:
            lines.append(f"- {r}")
        lines.append("")

    lines.append(f"**結論**: {verdict}")
    lines.append("")

    return "\n".join(lines)
