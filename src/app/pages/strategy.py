"""TASK-UI01 — Strategy page (V2 §7).

Shows the latest V1 backtest verdict in user-friendly Chinese layout:

* 中文欄位 + 單位（取代 raw key 名）
* 數值格式化（千分位、捨小數）
* 策略說明 panel（解釋 long_entry_v1 是什麼）
* 詳細報告**內嵌渲染**（取代「點開另開新分頁」）

Element IDs (kebab-case per project convention):
* ``strategy-page``                — root
* ``strategy-page-verdict``        — verdict banner
* ``strategy-page-overview``       — 策略說明區塊
* ``strategy-page-metrics``        — 績效指標表
* ``strategy-page-manifest``       — 回測設定表
* ``strategy-page-report``         — 內嵌詳細報告
* ``strategy-page-empty``          — 無實驗記錄時 empty-state
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from dash import dash_table, dcc, html

__all__ = [
    "MANIFEST_LABELS",
    "SUMMARY_LABELS",
    "create_strategy_page_layout",
    "format_manifest_value",
    "format_summary_value",
    "load_latest_experiment",
]


DEFAULT_REGISTRY_DIR = Path("analysis/experiment_registry")
DEFAULT_REPORT_PATH = Path("analysis/backtest_v1_report.md")
DEFAULT_STRATEGY_REVIEW_PATH = Path("specs/profitability/STRATEGY_REVIEW.md")


# ── 數值格式化 helpers ──────────────────────────────────────────────────────


def _fmt_money(value: Any) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{v:,.0f} 元"


def _fmt_int_with_unit(unit: str) -> Callable[[Any], str]:
    def fmt(value: Any) -> str:
        try:
            v = int(float(value))
        except (TypeError, ValueError):
            return str(value)
        return f"{v:,} {unit}"
    return fmt


def _fmt_months(value: Any) -> str:
    return _fmt_int_with_unit("月")(value)


def _fmt_business_days(value: Any) -> str:
    return _fmt_int_with_unit("交易日")(value)


def _fmt_str(value: Any) -> str:
    return str(value) if value not in (None, "") else "—"


# ── key → 中文 label + formatter mapping ────────────────────────────────────


SUMMARY_LABELS: Dict[str, Tuple[str, Callable[[Any], str]]] = {
    "trade_count": ("OOS 驗證期成交筆數", _fmt_int_with_unit("筆")),
    "n_windows": ("Walk-forward 窗數", _fmt_int_with_unit("窗")),
    "total_pnl": ("OOS 驗證期累計損益", _fmt_money),
    "is_trade_count": ("IS 訓練期成交筆數", _fmt_int_with_unit("筆")),
    "is_total_pnl": ("IS 訓練期累計損益", _fmt_money),
}


MANIFEST_LABELS: Dict[str, Tuple[str, Callable[[Any], str]]] = {
    "strategy": ("策略代號", _fmt_str),
    "universe_size": ("Universe 樣本檔數", _fmt_int_with_unit("檔")),
    "data_span_start": ("資料起始日", _fmt_str),
    "data_span_end": ("資料結束日", _fmt_str),
    "is_months": ("IS 訓練視窗長度", _fmt_months),
    "oos_months": ("OOS 驗證視窗長度", _fmt_months),
    "embargo_business_days": ("IS / OOS 之間 embargo", _fmt_business_days),
    "initial_cash_per_stock": ("單檔初始資金", _fmt_money),
    "target_shares": ("每筆目標部位", _fmt_int_with_unit("股")),
    "caveats": ("注意事項", _fmt_str),
    "n_trades": ("OOS 期總成交筆數", _fmt_int_with_unit("筆")),
    "experiment_id": ("實驗 ID", _fmt_str),
}


def format_summary_value(key: str, value: Any) -> str:
    label_fmt = SUMMARY_LABELS.get(key)
    if label_fmt is None:
        return str(value)
    return label_fmt[1](value)


def format_manifest_value(key: str, value: Any) -> str:
    label_fmt = MANIFEST_LABELS.get(key)
    if label_fmt is None:
        return str(value)
    return label_fmt[1](value)


# ── 表格列建構 ───────────────────────────────────────────────────────────────


_DARK_TABLE_STYLE = {
    "style_table": {"maxWidth": "720px", "marginBottom": "16px"},
    "style_header": {
        "backgroundColor": "#2a2a2a",
        "color": "#f5f5f5",
        "fontWeight": "bold",
        "border": "1px solid #444",
        "padding": "10px 12px",
    },
    "style_data": {
        "backgroundColor": "#1e1e1e",
        "color": "#e8e8e8",
        "border": "1px solid #333",
    },
    "style_cell": {
        "padding": "8px 12px",
        "fontFamily": "system-ui, -apple-system, 'Microsoft JhengHei', sans-serif",
        "textAlign": "left",
    },
}


def _summary_rows(summary: Dict[str, Any]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for key in SUMMARY_LABELS:
        if key not in summary:
            continue
        label, fmt = SUMMARY_LABELS[key]
        rows.append({"name": label, "value": fmt(summary[key])})
    # Surface any extra keys that aren't in the mapping (forward-compat).
    for key, value in summary.items():
        if key in SUMMARY_LABELS:
            continue
        rows.append({"name": key, "value": str(value)})
    return rows


def _manifest_rows(manifest: Dict[str, Any]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for key in MANIFEST_LABELS:
        if key not in manifest:
            continue
        label, fmt = MANIFEST_LABELS[key]
        rows.append({"name": label, "value": fmt(manifest[key])})
    for key, value in manifest.items():
        if key in MANIFEST_LABELS or key in ("universe", "windows"):
            continue
        rows.append({"name": key, "value": str(value)})
    return rows


# ── Layout 區塊 ──────────────────────────────────────────────────────────────


def _verdict_banner(experiment: Optional[Dict[str, Any]]) -> html.Div:
    if experiment is None:
        return html.Div(
            "尚無實驗記錄。請先執行 `python -m scripts.run_backtest_v1`。",
            id="strategy-page-empty",
            className="strategy-empty-state",
        )
    summary = experiment.get("summary") or {}
    trade_count = summary.get("trade_count")
    pnl = summary.get("total_pnl")
    pnl_text = format_summary_value("total_pnl", pnl) if pnl is not None else "—"
    trade_text = format_summary_value("trade_count", trade_count) if trade_count is not None else "—"
    return html.Div(
        [
            html.H2("V1 §6.1 最近回測判決", className="strategy-section-title"),
            html.Div(
                f"OOS 期成交 {trade_text}，累計損益 {pnl_text}。",
                className="strategy-verdict-summary",
            ),
            html.Div(
                f"實驗 ID: {experiment.get('experiment_id', '—')}",
                className="strategy-verdict-id",
                style={"color": "#999", "fontSize": "0.9em", "marginTop": "4px"},
            ),
        ],
        id="strategy-page-verdict",
        className="strategy-verdict-banner",
    )


def _strategy_overview() -> html.Div:
    """解釋當前策略 long_entry_v1 是什麼。"""
    return html.Div(
        id="strategy-page-overview",
        className="strategy-overview",
        style={
            "background": "#2a2a2a",
            "padding": "16px 20px",
            "borderRadius": "8px",
            "margin": "12px 0 24px 0",
            "borderLeft": "4px solid #6c8eff",
        },
        children=[
            html.H3("策略說明 — long_entry_v1（V2 §2 第一版）"),
            html.P(
                "屬「趨勢追蹤 + 量價突破 + 籌碼確認」混合型策略（類 CAN SLIM / SEPA / Turtle "
                "Trading / 台股本土籌碼派 family）。多方進場，平均持有 5-20 個交易日。",
                style={"marginBottom": "8px"},
            ),
            html.Ul(
                children=[
                    html.Li("進場條件（5 條同時滿足）：close>MA20 AND close>MA60、成交量爆發 ≥ MID、紅 K 或突破 20 日高、三大法人連 3 日 net buy 或融資 5 日減幅 < 0、非漲停板鎖死"),
                    html.Li("避免進場：上影線 > 實體 ×1.5、嚴重利空、daily loss limit"),
                    html.Li("出場（5 條任一觸發）：ATR 1.5× 停損、跌破 MA10、爆量長黑、ATR 1× 移動停利、持有 > 10 日"),
                    html.Li("Regime gate：每股自身 MA50/MA200 分類，允許 {BULL, RANGE}（BEAR 不交易）"),
                ],
                style={"marginBottom": "8px"},
            ),
            html.P(
                "完整 retrospective + 替代策略候選 C1-C5 見 specs/profitability/STRATEGY_REVIEW.md。",
                style={"color": "#aaa", "fontSize": "0.9em"},
            ),
        ],
    )


def _metrics_table(experiment: Optional[Dict[str, Any]]) -> html.Div:
    if experiment is None:
        return html.Div(id="strategy-page-metrics")
    summary = experiment.get("summary") or {}
    return html.Div(
        [
            html.H3("績效指標（從實驗記錄）"),
            dash_table.DataTable(
                id="strategy-page-metrics-table",
                columns=[
                    {"name": "指標", "id": "name"},
                    {"name": "數值", "id": "value"},
                ],
                data=_summary_rows(summary),
                **_DARK_TABLE_STYLE,
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
            html.H3("回測設定"),
            dash_table.DataTable(
                id="strategy-page-manifest-table",
                columns=[
                    {"name": "設定項", "id": "name"},
                    {"name": "內容", "id": "value"},
                ],
                data=_manifest_rows(manifest),
                **_DARK_TABLE_STYLE,
            ),
        ],
        id="strategy-page-manifest",
    )


def _inline_report(report_path: Path) -> html.Div:
    """把 backtest_v1_report.md 內嵌渲染（取代「點開另開分頁」）。"""
    if not report_path.exists():
        return html.Div(
            "（尚未產生詳細報告）",
            id="strategy-page-report",
            className="strategy-report-empty",
            style={"color": "#999", "marginTop": "24px"},
        )
    try:
        md_text = report_path.read_text()
    except OSError as exc:
        return html.Div(
            f"（讀取報告失敗：{exc}）",
            id="strategy-page-report",
            style={"color": "#c44", "marginTop": "24px"},
        )
    return html.Div(
        id="strategy-page-report",
        className="strategy-report-inline",
        style={"marginTop": "24px"},
        children=[
            html.H3("詳細回測報告"),
            html.Div(
                style={
                    "background": "#1a1a1a",
                    "padding": "16px 24px",
                    "borderRadius": "8px",
                    "border": "1px solid #333",
                    "maxHeight": "70vh",
                    "overflowY": "auto",
                },
                children=[
                    dcc.Markdown(
                        md_text,
                        link_target="_blank",
                        style={"color": "#e8e8e8"},
                    ),
                ],
            ),
            html.Div(
                children=[
                    html.A(
                        f"以原始檔案開啟：{report_path}",
                        href=f"/{report_path.as_posix()}",
                        target="_blank",
                        className="strategy-report-link",
                        style={"color": "#6c8eff", "fontSize": "0.9em"},
                    ),
                ],
                style={"marginTop": "8px"},
            ),
        ],
    )


def load_latest_experiment(
    registry_dir: Path = DEFAULT_REGISTRY_DIR,
) -> Optional[Dict[str, Any]]:
    if not registry_dir.exists():
        return None
    candidates: List[Tuple[float, Dict[str, Any]]] = []
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
            _strategy_overview(),
            _metrics_table(experiment),
            _manifest_table(experiment),
            _inline_report(report_path),
        ],
    )
