"""TASK-UI01 — Strategy page (V2 §7).

Minimal first version: shows the latest V1 backtest verdict, key
performance metrics from the experiment registry, and pointers to the
markdown report. Future iterations can add interactive charts, live
signal feed, regime indicator, etc.

Element IDs (kebab-case per project convention):
* ``strategy-page``               — root
* ``strategy-page-verdict``       — verdict banner (PASS / FAIL)
* ``strategy-page-metrics``       — metrics table
* ``strategy-page-manifest``      — manifest table
* ``strategy-page-empty``         — empty-state when no experiment record
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from dash import dash_table, html

__all__ = [
    "create_strategy_page_layout",
    "load_latest_experiment",
]


DEFAULT_REGISTRY_DIR = Path("analysis/experiment_registry")
DEFAULT_REPORT_PATH = Path("analysis/backtest_v1_report.md")


def load_latest_experiment(registry_dir: Path = DEFAULT_REGISTRY_DIR) -> Optional[Dict[str, Any]]:
    """Return the experiment-record JSON with the most recent ``recorded_at``
    timestamp; falls back to file mtime when the field is missing.
    """
    if not registry_dir.exists():
        return None
    candidates: List[tuple[float, Dict[str, Any]]] = []
    for path in registry_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        ts_raw = payload.get("recorded_at")
        if isinstance(ts_raw, (int, float)):
            ts = float(ts_raw)
        elif isinstance(ts_raw, str) and ts_raw.isdigit():
            ts = float(ts_raw)
        else:
            ts = path.stat().st_mtime
        candidates.append((ts, payload))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _summary_rows(summary: Dict[str, Any]) -> List[Dict[str, str]]:
    """Flatten the ``summary`` block into rows for a dash_table."""
    rows: List[Dict[str, str]] = []
    for key, value in summary.items():
        if isinstance(value, float):
            rendered = f"{value:.4f}"
        else:
            rendered = str(value)
        rows.append({"metric": key, "value": rendered})
    return rows


def _manifest_rows(manifest: Dict[str, Any]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for key in sorted(manifest):
        if key in ("universe", "windows"):  # large arrays — summarize
            value = f"<{len(manifest[key])} items>" if hasattr(manifest[key], "__len__") else "—"
        else:
            value = manifest[key]
        rows.append({"key": key, "value": str(value)})
    return rows


def _verdict_banner(experiment: Optional[Dict[str, Any]]) -> html.Div:
    if experiment is None:
        return html.Div(
            "尚無實驗記錄。請先執行 `python -m scripts.run_backtest_v1`.",
            id="strategy-page-empty",
            className="strategy-empty-state",
        )
    summary = experiment.get("summary") or {}
    trade_count = summary.get("trade_count")
    pnl = summary.get("total_pnl")
    title = f"最近實驗：trades={trade_count}, total_pnl={pnl}"
    return html.Div(
        [
            html.H2("V1 §6.1 最近回測判決", className="strategy-section-title"),
            html.Div(title, className="strategy-verdict-summary"),
            html.Div(
                f"experiment_id: {experiment.get('experiment_id', '—')}",
                className="strategy-verdict-id",
            ),
        ],
        id="strategy-page-verdict",
        className="strategy-verdict-banner",
    )


def _metrics_table(experiment: Optional[Dict[str, Any]]) -> html.Div:
    if experiment is None:
        return html.Div(id="strategy-page-metrics")
    summary = experiment.get("summary") or {}
    return html.Div(
        [
            html.H3("Summary"),
            dash_table.DataTable(
                id="strategy-page-metrics-table",
                columns=[
                    {"name": "Metric", "id": "metric"},
                    {"name": "Value", "id": "value"},
                ],
                data=_summary_rows(summary),
                style_table={"maxWidth": "640px"},
            ),
        ],
        id="strategy-page-metrics",
    )


def _manifest_table(experiment: Optional[Dict[str, Any]]) -> html.Div:
    if experiment is None:
        return html.Div(id="strategy-page-manifest")
    manifest = experiment.get("manifest") or {}
    return html.Div(
        [
            html.H3("Manifest"),
            dash_table.DataTable(
                id="strategy-page-manifest-table",
                columns=[
                    {"name": "Key", "id": "key"},
                    {"name": "Value", "id": "value"},
                ],
                data=_manifest_rows(manifest),
                style_table={"maxWidth": "640px"},
            ),
        ],
        id="strategy-page-manifest",
    )


def _report_link(report_path: Path) -> html.Div:
    if not report_path.exists():
        return html.Div()
    return html.Div(
        [
            html.H3("詳細報告"),
            html.A(
                f"開啟 {report_path}",
                href=f"/{report_path.as_posix()}",
                target="_blank",
                className="strategy-report-link",
            ),
        ]
    )


def create_strategy_page_layout(
    registry_dir: Path = DEFAULT_REGISTRY_DIR,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> html.Div:
    experiment = load_latest_experiment(registry_dir)
    return html.Div(
        id="strategy-page",
        className="strategy-page",
        children=[
            html.H1("策略績效 (V2 §7)", className="strategy-page-title"),
            _verdict_banner(experiment),
            _metrics_table(experiment),
            _manifest_table(experiment),
            _report_link(report_path),
        ],
    )
