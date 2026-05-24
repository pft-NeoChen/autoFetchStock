"""TASK-UI01 — Strategy page (user-facing).

設計原則：
1. **結論優先**：第一屏即看到 verdict + 白話建議
2. **白話解讀**：所有數字配「這代表什麼意思」一句說明
3. **拒絕 jargon**：移除 V2 §X / experiment_id / 內部規格文件 reference
4. **進階摺疊**：manifest / 完整報告放 ``<details>``，預設收合
5. **單頁可滾動**：不在內層 div 設 max-height（讓 browser 接管 scroll）

Element IDs (kebab-case)：
* ``strategy-page``                — root
* ``strategy-page-verdict``        — 白話結論卡
* ``strategy-page-explainer``      — 「這個頁面在做什麼」說明
* ``strategy-page-what-we-tested`` — 「我們測試了什麼」
* ``strategy-page-metrics``        — 數字解讀區
* ``strategy-page-recommendation`` — 建議行動
* ``strategy-page-details``        — 進階詳情（manifest + 報告）
* ``strategy-page-empty``          — 無實驗 empty state
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from dash import dash_table, dcc, html

__all__ = [
    "MANIFEST_LABELS",
    "METRIC_INTERPRETATIONS",
    "SUMMARY_LABELS",
    "build_recommendation",
    "build_verdict_summary",
    "create_strategy_page_layout",
    "format_manifest_value",
    "format_summary_value",
    "load_latest_experiment",
]


DEFAULT_REGISTRY_DIR = Path("analysis/experiment_registry")
DEFAULT_REPORT_PATH = Path("analysis/backtest_v1_report.md")


# ── 數值格式 ────────────────────────────────────────────────────────────────


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


def _fmt_str(value: Any) -> str:
    return str(value) if value not in (None, "") else "—"


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
    "is_months": ("IS 訓練視窗長度", _fmt_int_with_unit("月")),
    "oos_months": ("OOS 驗證視窗長度", _fmt_int_with_unit("月")),
    "embargo_business_days": ("IS / OOS 之間 embargo", _fmt_int_with_unit("交易日")),
    "initial_cash_per_stock": ("單檔初始資金", _fmt_money),
    "target_shares": ("每筆目標部位", _fmt_int_with_unit("股")),
    "caveats": ("注意事項", _fmt_str),
    "n_trades": ("OOS 期總成交筆數", _fmt_int_with_unit("筆")),
    "experiment_id": ("實驗 ID", _fmt_str),
}


# 白話解讀 — 給每個關鍵指標一句說明
METRIC_INTERPRETATIONS: Dict[str, Callable[[Any], str]] = {
    "trade_count": lambda v: (
        f"在驗證期間共成交 {int(v)} 筆。"
        + ("樣本筆數足夠（≥50），結論較可信。" if int(v) >= 50
           else "樣本筆數偏少（<50），結論可能受運氣影響。")
    ),
    "total_pnl": lambda v: (
        f"在驗證期間累計賺賠約 {float(v):,.0f} 元。"
        + ("總體獲利。" if float(v) > 0 else "總體虧損或打平。")
    ),
    "is_trade_count": lambda v: f"訓練期間共成交 {int(v)} 筆，用於最佳化策略參數。",
    "is_total_pnl": lambda v: f"訓練期間累計賺賠約 {float(v):,.0f} 元。",
    "n_windows": lambda v: (
        f"把資料切成 {int(v)} 段，每段獨立訓練 + 驗證，避免只看單一時期的好運。"
    ),
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


# ── 白話結論建構 ───────────────────────────────────────────────────────────


def build_verdict_summary(experiment: Dict[str, Any]) -> Dict[str, str]:
    """Build a human-readable verdict from the experiment summary."""
    summary = experiment.get("summary") or {}
    trades = summary.get("trade_count", 0)
    pnl = float(summary.get("total_pnl") or 0)

    if trades <= 0:
        headline = "❓ 沒有產生任何交易"
        reason = "策略條件太嚴，整段測試期間都沒進場 — 無法評估表現。"
        action = "建議放寬進場條件或檢查資料完整性。"
    elif pnl > 0 and trades >= 50:
        headline = "✅ 策略表現正向"
        reason = (
            f"在 {int(trades)} 筆成交中，累計賺 {pnl:,.0f} 元，"
            "樣本筆數足以支持初步信心。"
        )
        action = "可考慮進入 Paper（紙上）交易階段做進一步驗證。"
    elif pnl > 0 and trades < 50:
        headline = "⚠️ 表面獲利，但樣本不足"
        reason = (
            f"在 {int(trades)} 筆成交中累計賺 {pnl:,.0f} 元，"
            "但樣本不到 50 筆，可能只是運氣。"
        )
        action = "需更多資料或不同股票池再驗證。"
    else:
        headline = "❌ 策略目前沒有穩定獲利能力"
        reason = (
            f"在 {int(trades)} 筆成交中累計約 {pnl:,.0f} 元，且品質指標未達標"
            "（如平均每筆期望值為負、去除少數爆賺後即虧損）。"
        )
        action = "不建議直接拿來下實單。可參考下方建議行動。"

    return {"headline": headline, "reason": reason, "action": action}


def build_recommendation(experiment: Dict[str, Any]) -> List[str]:
    summary = experiment.get("summary") or {}
    trades = summary.get("trade_count", 0)
    pnl = float(summary.get("total_pnl") or 0)
    items: List[str] = []
    if pnl <= 0 or trades < 50:
        items.append("⛔ 暫時不要用這個策略下實單。")
        items.append("🔁 嘗試替代策略類型（如：短線反轉、突破系統）。")
        items.append("📊 等待更多資料累積（advisor 評分需 3-6 個月）。")
    else:
        items.append("✅ 可進入 Paper（紙上）交易階段驗證。")
        items.append("⏱ 至少跑滿 60 個交易日 + 100 筆成交再評估升級。")
    return items


# ── 表格樣式（暗色主題） ────────────────────────────────────────────────────


_DARK_TABLE_STYLE = {
    "style_table": {"maxWidth": "720px", "marginBottom": "12px"},
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


def _manifest_rows(manifest: Dict[str, Any]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for key in MANIFEST_LABELS:
        if key not in manifest:
            continue
        label, fmt = MANIFEST_LABELS[key]
        rows.append({"name": label, "value": fmt(manifest[key])})
    return rows


# ── 區塊 builders ────────────────────────────────────────────────────────────


def _verdict_section(experiment: Dict[str, Any]) -> html.Div:
    verdict = build_verdict_summary(experiment)
    return html.Div(
        id="strategy-page-verdict",
        className="strategy-verdict",
        style={
            "background": "#252525",
            "padding": "24px 28px",
            "borderRadius": "10px",
            "borderLeft": "5px solid #6c8eff",
            "marginBottom": "20px",
        },
        children=[
            html.Div("回測結論", style={"color": "#aaa", "fontSize": "0.85em", "marginBottom": "8px"}),
            html.H2(
                verdict["headline"],
                style={"margin": "0 0 12px 0", "fontSize": "1.6em"},
            ),
            html.P(verdict["reason"], style={"color": "#ddd", "marginBottom": "8px", "lineHeight": "1.6"}),
            html.P(
                verdict["action"],
                style={"color": "#9ec1ff", "fontWeight": "500", "marginBottom": "0"},
            ),
        ],
    )


def _explainer_section() -> html.Div:
    return html.Div(
        id="strategy-page-explainer",
        className="strategy-explainer",
        style={
            "background": "#1f1f1f",
            "padding": "20px 24px",
            "borderRadius": "8px",
            "marginBottom": "20px",
        },
        children=[
            html.H3("📖 這個頁面在做什麼？", style={"marginTop": "0"}),
            html.P(
                "這裡顯示「策略回測」結果。我們把一套買賣規則套到歷史股價上，"
                "模擬「如果過去這樣交易，會賺/賠多少」，"
                "用來判斷策略是否值得拿到真實市場使用。",
                style={"color": "#ddd", "lineHeight": "1.7", "marginBottom": "0"},
            ),
        ],
    )


def _what_we_tested_section(experiment: Dict[str, Any]) -> html.Div:
    manifest = experiment.get("manifest") or {}
    universe = manifest.get("universe_size", "—")
    start = manifest.get("data_span_start", "—")
    end = manifest.get("data_span_end", "—")
    n_windows = (experiment.get("summary") or {}).get("n_windows", "—")
    return html.Div(
        id="strategy-page-what-we-tested",
        className="strategy-what-we-tested",
        style={
            "background": "#1f1f1f",
            "padding": "20px 24px",
            "borderRadius": "8px",
            "marginBottom": "20px",
        },
        children=[
            html.H3("🔬 我們測試了什麼？", style={"marginTop": "0"}),
            html.Div(
                style={"display": "grid", "gridTemplateColumns": "180px 1fr", "gap": "10px 16px"},
                children=[
                    html.Div("策略類型", style={"color": "#aaa"}),
                    html.Div("趨勢追蹤（趨勢起漲時跟進，跌破停損出場）"),
                    html.Div("進場判斷依據", style={"color": "#aaa"}),
                    html.Div("股價站上 20 / 60 日均線、出現爆量、法人連續買進"),
                    html.Div("出場判斷依據", style={"color": "#aaa"}),
                    html.Div("停損 1.5×ATR、跌破 10 日均線、爆量長黑、移動停利、持有 > 10 日"),
                    html.Div("測試的股票池", style={"color": "#aaa"}),
                    html.Div(f"{universe} 檔台股（含上市 + 上櫃部分樣本）"),
                    html.Div("測試的時間範圍", style={"color": "#aaa"}),
                    html.Div(f"{start} ~ {end}"),
                    html.Div("測試的方式", style={"color": "#aaa"}),
                    html.Div(
                        f"Walk-forward 滾動，共切 {n_windows} 段獨立訓練 + 驗證，"
                        "避免只看單一時期的好運。"
                    ),
                ],
            ),
        ],
    )


def _metrics_section(experiment: Dict[str, Any]) -> html.Div:
    summary = experiment.get("summary") or {}
    rows: List[html.Div] = []
    for key in ("total_pnl", "trade_count", "n_windows", "is_total_pnl", "is_trade_count"):
        if key not in summary:
            continue
        label = SUMMARY_LABELS[key][0]
        value_str = format_summary_value(key, summary[key])
        interp_fn = METRIC_INTERPRETATIONS.get(key)
        interp = interp_fn(summary[key]) if interp_fn else ""
        rows.append(
            html.Div(
                style={
                    "padding": "14px 16px",
                    "borderBottom": "1px solid #333",
                    "display": "grid",
                    "gridTemplateColumns": "240px 180px 1fr",
                    "gap": "16px",
                    "alignItems": "baseline",
                },
                children=[
                    html.Div(label, style={"color": "#aaa"}),
                    html.Div(
                        value_str,
                        style={
                            "fontFamily": "ui-monospace, SF Mono, Menlo, monospace",
                            "fontSize": "1.05em",
                            "color": "#f5f5f5",
                        },
                    ),
                    html.Div(interp, style={"color": "#bbb", "fontSize": "0.9em"}),
                ],
            )
        )

    return html.Div(
        id="strategy-page-metrics",
        className="strategy-metrics",
        style={
            "background": "#1f1f1f",
            "padding": "20px 24px",
            "borderRadius": "8px",
            "marginBottom": "20px",
        },
        children=[
            html.H3("📊 主要結果（含白話解讀）", style={"marginTop": "0"}),
            html.Div(rows) if rows else html.Div("（無資料）", style={"color": "#888"}),
        ],
    )


def _recommendation_section(experiment: Dict[str, Any]) -> html.Div:
    items = build_recommendation(experiment)
    return html.Div(
        id="strategy-page-recommendation",
        className="strategy-recommendation",
        style={
            "background": "#1f1f1f",
            "padding": "20px 24px",
            "borderRadius": "8px",
            "marginBottom": "20px",
        },
        children=[
            html.H3("👉 接下來該怎麼做？", style={"marginTop": "0"}),
            html.Ul(
                [html.Li(item, style={"marginBottom": "6px"}) for item in items],
                style={"color": "#ddd", "lineHeight": "1.7", "marginBottom": "0"},
            ),
        ],
    )


def _details_section(experiment: Dict[str, Any], report_path: Path) -> html.Div:
    manifest = experiment.get("manifest") or {}
    manifest_table = dash_table.DataTable(
        id="strategy-page-manifest-table",
        columns=[
            {"name": "設定項", "id": "name"},
            {"name": "內容", "id": "value"},
        ],
        data=_manifest_rows(manifest),
        **_DARK_TABLE_STYLE,
    )

    md_text: Optional[str] = None
    if report_path.exists():
        try:
            md_text = report_path.read_text()
        except OSError:
            md_text = None

    report_block = (
        dcc.Markdown(md_text, link_target="_blank", style={"color": "#e8e8e8"})
        if md_text
        else html.Div("（尚未產生詳細報告 — 請執行 python -m scripts.run_backtest_v1）",
                      style={"color": "#888"})
    )

    return html.Div(
        id="strategy-page-details",
        className="strategy-details",
        style={"marginBottom": "20px"},
        children=[
            html.Details(
                style={
                    "background": "#1a1a1a",
                    "padding": "12px 20px",
                    "borderRadius": "8px",
                    "marginBottom": "12px",
                },
                children=[
                    html.Summary(
                        "⚙️ 回測詳細設定",
                        style={"cursor": "pointer", "fontWeight": "500", "color": "#ccc"},
                    ),
                    html.Div(manifest_table, style={"marginTop": "12px"}),
                ],
            ),
            html.Details(
                style={
                    "background": "#1a1a1a",
                    "padding": "12px 20px",
                    "borderRadius": "8px",
                },
                children=[
                    html.Summary(
                        "📄 完整回測報告（markdown）",
                        style={"cursor": "pointer", "fontWeight": "500", "color": "#ccc"},
                    ),
                    html.Div(report_block, style={"marginTop": "12px"}),
                ],
            ),
        ],
    )


# ── 載入 + 組合 ──────────────────────────────────────────────────────────────


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


def _empty_state() -> html.Div:
    return html.Div(
        id="strategy-page-empty",
        className="strategy-empty-state",
        style={
            "padding": "40px",
            "textAlign": "center",
            "color": "#999",
        },
        children=[
            html.H2("📭 尚未有回測結果"),
            html.P("請先執行回測腳本以產生報告："),
            html.Pre(
                "python -m scripts.run_backtest_v1",
                style={
                    "background": "#1a1a1a",
                    "padding": "12px",
                    "borderRadius": "6px",
                    "display": "inline-block",
                    "color": "#9ec1ff",
                },
            ),
        ],
    )


def create_strategy_page_layout(
    registry_dir: Path = DEFAULT_REGISTRY_DIR,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> html.Div:
    experiment = load_latest_experiment(registry_dir)
    children: List[Any] = [
        html.H1(
            "策略績效",
            className="strategy-page-title",
            style={"marginBottom": "20px"},
        ),
    ]
    if experiment is None:
        children.append(_empty_state())
    else:
        children.extend([
            _verdict_section(experiment),
            _explainer_section(),
            _what_we_tested_section(experiment),
            _metrics_section(experiment),
            _recommendation_section(experiment),
            _details_section(experiment, report_path),
        ])

    # `.main-container` 在全域 CSS 設 `height: 100vh; overflow: hidden`，
    # 內頁需自帶 scroll 容器（複製 `.news-page` 既有 pattern）。
    return html.Div(
        id="strategy-page",
        className="strategy-page",
        style={
            "height": "calc(100vh - 100px)",
            "overflowY": "auto",
            "overflowX": "hidden",
            "padding": "24px 32px",
            "boxSizing": "border-box",
            "color": "#e8e8e8",
        },
        children=[
            html.Div(
                style={"maxWidth": "1100px", "margin": "0 auto"},
                children=children,
            ),
        ],
    )
