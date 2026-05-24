"""Strategy backtest result page (`/strategy`).

Hi-fi rewrite per ``design_handoff_strategy_backtest/`` design handoff.

Element IDs (kebab-case, contract for tests):
* ``strategy-page``                — root scroll container
* ``strategy-page-verdict``        — hero verdict card (blue 5px left border)
* ``strategy-page-explainer``      — what-is-this-page card
* ``strategy-page-what-we-tested`` — strategy spec card + walk-forward viz
* ``strategy-page-metrics``        — main metric list (status dot + meaning)
* ``strategy-page-recommendation`` — numbered action items
* ``strategy-page-details``        — collapsed ``<details>`` w/ manifest + md
* ``strategy-page-empty``          — empty state (display:none when data present)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

from dash import dcc, html

__all__ = [
    "BacktestResult",
    "MANIFEST_LABELS",
    "METRIC_INTERPRETATIONS",
    "Metric",
    "Reco",
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


# ── 數值格式化 ───────────────────────────────────────────────────────────────


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
    "trade_count": ("驗證期成交筆數", _fmt_int_with_unit("筆")),
    "n_windows": ("驗證段數", _fmt_int_with_unit("段")),
    "total_pnl": ("驗證期累計損益", _fmt_money),
    "is_trade_count": ("訓練期成交筆數", _fmt_int_with_unit("筆")),
    "is_total_pnl": ("訓練期累計損益", _fmt_money),
}


MANIFEST_LABELS: Dict[str, Tuple[str, Callable[[Any], str]]] = {
    "strategy": ("策略代號", _fmt_str),
    "universe_size": ("股票池樣本", _fmt_int_with_unit("檔")),
    "data_span_start": ("資料起始日", _fmt_str),
    "data_span_end": ("資料結束日", _fmt_str),
    "is_months": ("訓練視窗長度", _fmt_int_with_unit("月")),
    "oos_months": ("驗證視窗長度", _fmt_int_with_unit("月")),
    "embargo_business_days": ("訓練/驗證間隔", _fmt_int_with_unit("交易日")),
    "initial_cash_per_stock": ("單檔初始資金", _fmt_money),
    "target_shares": ("每筆目標部位", _fmt_int_with_unit("股")),
    "caveats": ("注意事項", _fmt_str),
    "n_trades": ("總成交筆數", _fmt_int_with_unit("筆")),
    "experiment_id": ("回測 ID", _fmt_str),
}


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


# ── Verdict / Recommendation 文案產生 ─────────────────────────────────────────


def build_verdict_summary(experiment: Dict[str, Any]) -> Dict[str, str]:
    """產生白話結論：headline / reason / action。"""
    summary = experiment.get("summary") or {}
    trades = int(summary.get("trade_count", 0) or 0)
    pnl = float(summary.get("total_pnl") or 0)

    if trades <= 0:
        headline = "❓ 沒有產生任何交易"
        reason = "策略條件太嚴，整段測試期間都沒進場 — 無法評估表現。"
        action = "建議放寬進場條件或檢查資料完整性。"
        status = "warn"
    elif pnl > 0 and trades >= 50:
        headline = "✅ 策略表現正向"
        reason = (
            f"在 {trades} 筆成交中，累計賺 {pnl:,.0f} 元，"
            "樣本筆數足以支持初步信心。"
        )
        action = "可考慮進入 Paper（紙上）交易階段做進一步驗證。"
        status = "pass"
    elif pnl > 0 and trades < 50:
        headline = "⚠️ 表面獲利，但樣本不足"
        reason = (
            f"在 {trades} 筆成交中累計賺 {pnl:,.0f} 元，"
            "但樣本不到 50 筆，可能只是運氣。"
        )
        action = "需更多資料或不同股票池再驗證。"
        status = "warn"
    else:
        headline = "❌ 策略目前沒有穩定獲利能力"
        reason = (
            f"在 {trades} 筆成交中累計約 {pnl:,.0f} 元，且品質指標未達標"
            "（如平均每筆期望值為負、去除少數爆賺後即虧損）。"
        )
        action = "不建議直接拿來下實單。可參考下方建議行動。"
        status = "fail"

    return {
        "headline": headline,
        "reason": reason,
        "action": action,
        "status": status,
    }


def build_recommendation(experiment: Dict[str, Any]) -> List[str]:
    summary = experiment.get("summary") or {}
    trades = int(summary.get("trade_count", 0) or 0)
    pnl = float(summary.get("total_pnl") or 0)
    items: List[str] = []
    if pnl <= 0 or trades < 50:
        items.append("⛔ 暫時不要用這個策略下實單。")
        items.append("🔁 嘗試替代策略類型（如：短線反轉、突破系統）。")
        items.append("📊 等待更多資料累積（advisor 評分需 3-6 個月）。")
        items.append("🛡️ 加入風控停損條件，降低極端回落風險。")
        items.append("📌 把這次的設定存成基準，下次比較。")
    else:
        items.append("✅ 可進入 Paper（紙上）交易階段驗證。")
        items.append("⏱ 至少跑滿 60 個交易日 + 100 筆成交再評估升級。")
        items.append("🛡️ 監控最大連續回落，超過 −15% 暫停。")
        items.append("📌 把這次的設定存成基準，下次比較。")
    return items


# ── 設計用 dataclass ────────────────────────────────────────────────────────


VerdictStatus = Literal["pass", "warn", "fail"]
MetricStatus = Literal["pass", "warn", "fail"]
MetricSign = Literal["pos", "neg", "neutral"]


@dataclass
class Metric:
    name: str
    hint: str
    value: str
    unit: str
    status: MetricStatus
    status_label: str
    meaning: str
    sign: MetricSign = "neutral"


@dataclass
class Reco:
    title: str
    desc: str


@dataclass
class BacktestResult:
    verdict_status: VerdictStatus
    verdict_headline: str
    verdict_reason: str
    verdict_action: str
    strategy_type: str
    universe_size: int
    universe_desc: str
    entry_rule: str
    exit_rule: str
    test_range_start: str
    test_range_end: str
    walk_forward_windows: int
    metrics: List[Metric] = field(default_factory=list)
    recommendations: List[Reco] = field(default_factory=list)
    manifest_rows: List[Tuple[str, str]] = field(default_factory=list)
    full_report_md: Optional[str] = None
    run_id: str = ""
    finished_at: str = ""


# ── 資料載入 + adapter ──────────────────────────────────────────────────────


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


def _metric_for_trade_count(v: Any) -> Metric:
    n = int(v or 0)
    status: MetricStatus = "pass" if n >= 50 else ("warn" if n >= 20 else "fail")
    label = {"pass": "PASS", "warn": "注意", "fail": "FAIL"}[status]
    meaning = (
        "樣本足夠（≥ 50 筆），結論有一定可信度。" if status == "pass"
        else "樣本筆數偏少，結論可能受運氣影響。"
    )
    return Metric(
        name="驗證期成交筆數",
        hint="策略在「沒看過」的時段裡實際成交了幾次",
        value=f"{n:,}",
        unit="筆",
        status=status,
        status_label=label,
        meaning=meaning,
    )


def _metric_for_total_pnl(v: Any) -> Metric:
    pnl = float(v or 0)
    if pnl > 0:
        status: MetricStatus = "pass"
        meaning = "整體獲利，但須搭配其他穩定度指標一起看。"
        sign: MetricSign = "pos"
        sign_str = "+"
    elif pnl == 0:
        status = "warn"
        meaning = "打平 — 沒虧但也沒賺，扣手續費後通常為負。"
        sign = "neutral"
        sign_str = ""
    else:
        status = "fail"
        meaning = "整體虧損，這套策略目前沒有獲利能力。"
        sign = "neg"
        sign_str = ""
    label = {"pass": "PASS", "warn": "注意", "fail": "FAIL"}[status]
    return Metric(
        name="驗證期累計損益",
        hint="所有交易加起來，到底賺還是賠",
        value=f"{sign_str}{pnl:,.0f}",
        unit="元",
        status=status,
        status_label=label,
        meaning=meaning,
        sign=sign,
    )


def _metric_for_n_windows(v: Any) -> Metric:
    n = int(v or 0)
    status: MetricStatus = "pass" if n >= 5 else "warn"
    label = {"pass": "PASS", "warn": "注意", "fail": "FAIL"}[status]
    meaning = (
        f"{n} 段獨立的「學 → 驗」流程，結論不是只靠某一段運氣。"
        if status == "pass"
        else f"只有 {n} 段獨立驗證，結論可能不夠穩。"
    )
    return Metric(
        name="驗證段數",
        hint="把時間切成幾段獨立來驗",
        value=str(n),
        unit="段",
        status=status,
        status_label=label,
        meaning=meaning,
    )


def _metric_for_is_trade_count(v: Any) -> Metric:
    n = int(v or 0)
    return Metric(
        name="訓練期成交筆數",
        hint="策略在「學習」期間實際成交了幾次",
        value=f"{n:,}",
        unit="筆",
        status="pass",
        status_label="參考",
        meaning="訓練期樣本，用來最佳化策略參數，本身不代表績效。",
    )


def _metric_for_is_total_pnl(v: Any) -> Metric:
    pnl = float(v or 0)
    sign: MetricSign = "pos" if pnl > 0 else ("neg" if pnl < 0 else "neutral")
    sign_str = "+" if pnl > 0 else ""
    return Metric(
        name="訓練期累計損益",
        hint="訓練期間策略累計賺賠",
        value=f"{sign_str}{pnl:,.0f}",
        unit="元",
        status="pass",
        status_label="參考",
        meaning="訓練期表現不能直接拿來預測未來，但可與驗證期比較看落差。",
        sign=sign,
    )


_METRIC_BUILDERS: Dict[str, Callable[[Any], Metric]] = {
    "trade_count": _metric_for_trade_count,
    "total_pnl": _metric_for_total_pnl,
    "n_windows": _metric_for_n_windows,
    "is_trade_count": _metric_for_is_trade_count,
    "is_total_pnl": _metric_for_is_total_pnl,
}


def _build_result(experiment: Dict[str, Any], report_md: Optional[str]) -> BacktestResult:
    summary = experiment.get("summary") or {}
    manifest = experiment.get("manifest") or {}

    verdict = build_verdict_summary(experiment)

    # metrics — 只渲染我們有資料的欄位，依固定順序
    metrics: List[Metric] = []
    for key in ("total_pnl", "trade_count", "n_windows", "is_total_pnl", "is_trade_count"):
        if key not in summary:
            continue
        builder = _METRIC_BUILDERS.get(key)
        if builder is None:
            continue
        metrics.append(builder(summary[key]))

    # recommendations — 從 build_recommendation 字串拆成 title/desc
    recos: List[Reco] = []
    for item in build_recommendation(experiment):
        recos.append(Reco(title=item, desc=""))

    # manifest_rows — 已格式化的 (label, value) tuple
    manifest_rows: List[Tuple[str, str]] = []
    for key in MANIFEST_LABELS:
        if key not in manifest:
            continue
        label = MANIFEST_LABELS[key][0]
        manifest_rows.append((label, format_manifest_value(key, manifest[key])))
    # 附加 summary 數字到 manifest（補齊資訊密度）
    for key in ("trade_count", "n_windows", "total_pnl", "is_trade_count", "is_total_pnl"):
        if key in summary:
            manifest_rows.append((SUMMARY_LABELS[key][0], format_summary_value(key, summary[key])))

    universe_size = int(manifest.get("universe_size", 0) or 0)
    n_windows = int(summary.get("n_windows", 0) or 0)
    start = str(manifest.get("data_span_start") or "—")
    end = str(manifest.get("data_span_end") or "—")
    run_id = str(experiment.get("experiment_id") or "")

    return BacktestResult(
        verdict_status=verdict["status"],  # type: ignore[arg-type]
        verdict_headline=verdict["headline"],
        verdict_reason=verdict["reason"],
        verdict_action=verdict["action"],
        strategy_type="趨勢追蹤",
        universe_size=universe_size,
        universe_desc=f"{universe_size} 檔台股（含上市 + 上櫃部分樣本）" if universe_size else "—",
        entry_rule="股價站上 20 / 60 日均線、出現爆量、法人連續買進。",
        exit_rule="停損 1.5×ATR、跌破 10 日均線、爆量長黑、移動停利、持有 > 10 日。",
        test_range_start=start,
        test_range_end=end,
        walk_forward_windows=n_windows,
        metrics=metrics,
        recommendations=recos,
        manifest_rows=manifest_rows,
        full_report_md=report_md,
        run_id=run_id,
        finished_at=str(experiment.get("recorded_at") or ""),
    )


# ── Section builders ────────────────────────────────────────────────────────


def _page_head() -> html.Div:
    return html.Div(
        className="strategy-page-head",
        children=[
            html.Span("backtest report", className="strategy-page-eyebrow"),
            html.H1("策略回測結果", className="strategy-page-title"),
            html.P(
                "用歷史資料模擬一套交易策略，幫你決定要不要拿它去下實單。",
                className="strategy-page-sub",
            ),
        ],
    )


_VERDICT_ICON = {"pass": "✅", "warn": "⚠️", "fail": "❌"}


def _verdict_section(result: BacktestResult) -> html.Section:
    status = result.verdict_status
    headline_text = result.verdict_headline
    # 移除文案開頭可能重複的 emoji（headline 已含），避免雙重 icon
    icon = _VERDICT_ICON.get(status, "●")
    return html.Section(
        id="strategy-page-verdict",
        className=f"strategy-verdict strategy-verdict-{status}",
        **{"aria-label": "回測結論"},
        children=[
            html.Span("● 回測結論", className="strategy-verdict-tag"),
            html.Div(
                className=f"strategy-verdict-headline strategy-v-{status}",
                children=[
                    html.Span(icon, className="strategy-v-icon"),
                    html.Span(_strip_leading_emoji(headline_text)),
                ],
            ),
            html.Div(
                className="strategy-verdict-grid",
                children=[
                    html.Div(
                        className="strategy-verdict-block strategy-verdict-reason",
                        children=[
                            html.H4(
                                [html.Span(className="strategy-dot"), "為什麼這樣判斷"]
                            ),
                            html.P(result.verdict_reason),
                        ],
                    ),
                    html.Div(
                        className="strategy-verdict-block strategy-verdict-action",
                        children=[
                            html.H4(
                                [html.Span(className="strategy-dot"), "建議下一步"]
                            ),
                            html.P(result.verdict_action),
                        ],
                    ),
                ],
            ),
        ],
    )


def _strip_leading_emoji(text: str) -> str:
    for ico in ("✅ ", "⚠️ ", "❌ ", "❓ "):
        if text.startswith(ico):
            return text[len(ico):]
    return text


def _explainer_section() -> html.Section:
    return html.Section(
        id="strategy-page-explainer",
        className="strategy-card",
        **{"aria-label": "這個頁面在做什麼"},
        children=[
            html.Div(
                className="strategy-card-head",
                children=[html.H2("這個頁面在做什麼？")],
            ),
            html.Div(
                className="strategy-card-body strategy-explainer-body",
                children=[
                    html.P(
                        [
                            html.Span("「策略回測」", className="strategy-em"),
                            "就是把一套買賣規則套到",
                            html.Span("過去的真實股價", className="strategy-em"),
                            "上，模擬「如果幾年前就這樣交易，到今天會賺多少、賠多少」。",
                        ]
                    ),
                    html.P(
                        [
                            "我們不是要證明策略「以前很賺」，而是要看它",
                            html.Span("獲利穩不穩", className="strategy-em"),
                            " — 是靠幾筆運氣好，還是有可重複的優勢。如果穩，才值得拿真錢去試。",
                        ]
                    ),
                ],
            ),
        ],
    )


def _walk_forward_diagram(rows: int) -> html.Div:
    """以 inline style 渲染 walk-forward sliding window 視覺（無需 JS）。"""
    TOTAL = 30
    TRAIN_LEN = 6
    TEST_LEN = 3
    n = max(1, min(rows or 11, 22))  # 最少 1、最多 22 段

    def pct(x: int) -> str:
        return f"{x / TOTAL * 100:.2f}%"

    bars: List[html.Div] = []
    for r in range(n):
        start = r
        test_end = start + TRAIN_LEN + TEST_LEN
        if test_end > TOTAL:
            break
        train_label = "學" if r == 0 else ""
        test_label = "驗" if r == 0 else ""
        bars.append(
            html.Div(
                className="strategy-wf-row",
                children=[
                    html.Span(f"第 {r + 1:>2} 段", className="strategy-wf-label"),
                    html.Div(
                        className="strategy-wf-bar",
                        children=[
                            html.Div(
                                className="strategy-wf-seg strategy-wf-empty",
                                style={"width": pct(start)},
                            ),
                            html.Div(
                                train_label,
                                className="strategy-wf-seg strategy-wf-train",
                                style={"width": pct(TRAIN_LEN)},
                            ),
                            html.Div(
                                test_label,
                                className="strategy-wf-seg strategy-wf-test",
                                style={"width": pct(TEST_LEN)},
                            ),
                            html.Div(
                                className="strategy-wf-seg strategy-wf-empty",
                                style={"width": pct(TOTAL - test_end)},
                            ),
                        ],
                    ),
                ],
            )
        )

    return html.Div(
        className="strategy-wf-explainer",
        children=[
            html.P(
                [
                    "把整段時間切成 ",
                    html.Strong(str(n), className="strategy-num"),
                    " 段。每一段都用",
                    html.Strong("前面一段時間"),
                    "「學」這套策略該怎麼調參數，再用",
                    html.Strong("接下來一段時間"),
                    "「驗收」 — 像考前複習、考試分開。然後整段時間軸往前推一格，再來一次。",
                ]
            ),
            html.P(
                "這樣模型只能看「過去的資料」、結果只能看「沒看過的資料」 — 比較不會自欺欺人。",
                className="strategy-wf-note",
            ),
            html.Div(bars, className="strategy-wf-diagram"),
            html.Div(
                className="strategy-wf-legend",
                children=[
                    html.Span(
                        [html.Span(className="strategy-sw strategy-sw-train"), "學習期（看過去）"]
                    ),
                    html.Span(
                        [html.Span(className="strategy-sw strategy-sw-test"), "驗證期（這段才算數）"]
                    ),
                ],
            ),
        ],
    )


def _spec_cell(label: str, value_children: Any, detail: Optional[str] = None, wide: bool = False) -> html.Div:
    cls = "strategy-spec strategy-spec-wide" if wide else "strategy-spec"
    children = [
        html.Div(
            [html.Span("◆", className="strategy-ic"), label],
            className="strategy-spec-label",
        ),
        html.Div(value_children, className="strategy-spec-value"),
    ]
    if detail:
        children.append(html.Div(detail, className="strategy-spec-detail"))
    return html.Div(className=cls, children=children)


def _what_we_tested_section(result: BacktestResult) -> html.Section:
    rules_block = html.Div(
        className="strategy-rule-list",
        children=[
            html.Div(
                className="strategy-rule-row",
                children=[
                    html.Span("進場", className="strategy-rule-tag"),
                    html.Span(result.entry_rule, className="strategy-rule-text"),
                ],
            ),
            html.Div(
                className="strategy-rule-row",
                children=[
                    html.Span("出場", className="strategy-rule-tag strategy-rule-exit"),
                    html.Span(result.exit_rule, className="strategy-rule-text"),
                ],
            ),
        ],
    )

    wf_block = html.Div(
        className="strategy-spec strategy-spec-wide",
        children=[
            html.Div(
                [html.Span("◆", className="strategy-ic"), "「滾動驗證」是什麼？用走路來比喻"],
                className="strategy-spec-label",
            ),
            _walk_forward_diagram(result.walk_forward_windows),
        ],
    )

    return html.Section(
        id="strategy-page-what-we-tested",
        className="strategy-card",
        **{"aria-label": "我們測試了什麼"},
        children=[
            html.Div(
                className="strategy-card-head",
                children=[
                    html.H2("我們測試了什麼"),
                    html.Span("這次回測使用的策略設定", className="strategy-h-sub"),
                ],
            ),
            html.Div(
                className="strategy-card-body",
                children=[
                    html.Div(
                        className="strategy-spec-grid",
                        children=[
                            _spec_cell(
                                "策略類型",
                                result.strategy_type,
                                "看到股價往上「衝出來」就跟著買、跌破就賣 — 屬於順勢操作。",
                            ),
                            _spec_cell(
                                "測試股票池",
                                [
                                    html.Span(f"{result.universe_size:,}", className="strategy-num"),
                                    " 檔上市櫃股票",
                                ],
                                result.universe_desc,
                            ),
                            html.Div(
                                className="strategy-spec strategy-spec-wide",
                                children=[
                                    html.Div(
                                        [html.Span("◆", className="strategy-ic"), "進場 / 出場規則"],
                                        className="strategy-spec-label",
                                    ),
                                    rules_block,
                                ],
                            ),
                            _spec_cell(
                                "測試時間範圍",
                                [
                                    html.Span(result.test_range_start, className="strategy-num"),
                                    " — ",
                                    html.Span(result.test_range_end, className="strategy-num"),
                                ],
                                "涵蓋多空交替的不同市場情境。",
                            ),
                            _spec_cell(
                                "測試方式",
                                "滾動式前向驗證",
                                "不是把所有資料拿來自己看自己，而是「用過去學、用之後驗收」反覆推進 — 比較接近真實交易環境。",
                            ),
                            wf_block,
                        ],
                    ),
                ],
            ),
        ],
    )


def _metric_row(m: Metric) -> html.Div:
    value_cls = f"strategy-metric-value strategy-{m.sign}" if m.sign != "neutral" else "strategy-metric-value"
    return html.Div(
        className="strategy-metric",
        children=[
            html.Span(className=f"strategy-metric-status strategy-status-{m.status}"),
            html.Div(
                className="strategy-metric-name",
                children=[
                    m.name,
                    html.Span(m.hint, className="strategy-metric-hint"),
                ],
            ),
            html.Div(
                className=value_cls,
                children=[
                    html.Span(m.value, className="strategy-metric-v"),
                    html.Span(m.unit, className="strategy-metric-u") if m.unit else None,
                ],
            ),
            html.Div(
                className="strategy-metric-meaning",
                children=[
                    html.Span(
                        m.status_label,
                        className=f"strategy-pill strategy-pill-{m.status}",
                    ),
                    m.meaning,
                ],
            ),
        ],
    )


def _metrics_section(result: BacktestResult) -> html.Section:
    body: Any
    if result.metrics:
        body = html.Div(
            [_metric_row(m) for m in result.metrics],
            className="strategy-metric-list",
        )
    else:
        body = html.Div("（無指標資料）", className="strategy-metric-empty")
    return html.Section(
        id="strategy-page-metrics",
        className="strategy-card",
        **{"aria-label": "主要結果"},
        children=[
            html.Div(
                className="strategy-card-head",
                children=[
                    html.H2("主要結果"),
                    html.Span("每個數字後面都附上白話解讀", className="strategy-h-sub"),
                ],
            ),
            html.Div(body, className="strategy-card-body"),
        ],
    )


def _recommendation_section(result: BacktestResult) -> html.Section:
    items: List[html.Div] = []
    for idx, reco in enumerate(result.recommendations, start=1):
        items.append(
            html.Div(
                className="strategy-reco",
                children=[
                    html.Div(str(idx), className="strategy-reco-num"),
                    html.Div(
                        className="strategy-reco-body",
                        children=[
                            html.Div(reco.title, className="strategy-reco-title"),
                            html.Div(reco.desc, className="strategy-reco-desc") if reco.desc else None,
                        ],
                    ),
                ],
            )
        )
    return html.Section(
        id="strategy-page-recommendation",
        className="strategy-card",
        **{"aria-label": "接下來該怎麼做"},
        children=[
            html.Div(
                className="strategy-card-head",
                children=[
                    html.H2("接下來該怎麼做"),
                    html.Span("依本次結論動態產生", className="strategy-h-sub"),
                ],
            ),
            html.Div(
                html.Div(items, className="strategy-reco-list"),
                className="strategy-card-body",
            ),
        ],
    )


def _details_section(result: BacktestResult) -> html.Details:
    manifest_table = html.Table(
        className="strategy-manifest",
        children=[
            html.Thead(html.Tr([html.Th("項目"), html.Th("值")])),
            html.Tbody(
                [
                    html.Tr(
                        [
                            html.Td(label, className="strategy-manifest-key"),
                            html.Td(value, className="strategy-manifest-val"),
                        ]
                    )
                    for label, value in result.manifest_rows
                ]
            ),
        ],
    )

    if result.full_report_md:
        report_block = html.Div(
            dcc.Markdown(result.full_report_md, link_target="_blank"),
            className="strategy-report",
        )
    else:
        report_block = html.Div(
            "（尚未產生詳細報告 — 請執行 python -m scripts.run_backtest_v1）",
            className="strategy-report strategy-report-empty",
        )

    return html.Details(
        id="strategy-page-details",
        className="strategy-details",
        children=[
            html.Summary(
                children=[
                    html.Span("▶", className="strategy-caret"),
                    html.Span("進階詳情", className="strategy-details-lbl"),
                    html.Span("回測設定 · 完整報告", className="strategy-details-sub"),
                    html.Span(className="strategy-details-spacer"),
                    html.Span("點擊展開", className="strategy-details-hint"),
                ]
            ),
            html.Div(
                className="strategy-details-body",
                children=[
                    html.Div(
                        className="strategy-details-section",
                        children=[
                            html.H3("回測設定"),
                            manifest_table,
                        ],
                    ),
                    html.Div(
                        className="strategy-details-section",
                        children=[
                            html.H3("完整回測報告"),
                            report_block,
                        ],
                    ),
                ],
            ),
        ],
    )


def _empty_state() -> html.Div:
    return html.Div(
        id="strategy-page-empty",
        className="strategy-empty",
        role="status",
        children=[
            html.H3("還沒有回測結果"),
            html.P("選擇一套策略並按「執行回測」之後，這裡就會出現結論與建議。"),
            html.Pre(
                "python -m scripts.run_backtest_v1",
                className="strategy-empty-cmd",
            ),
        ],
    )


# ── 載入 + 組合 ──────────────────────────────────────────────────────────────


def _load_report(report_path: Path) -> Optional[str]:
    if not report_path.exists():
        return None
    try:
        return report_path.read_text()
    except OSError:
        return None


def create_strategy_page_layout(
    registry_dir: Path = DEFAULT_REGISTRY_DIR,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> html.Div:
    experiment = load_latest_experiment(registry_dir)
    report_md = _load_report(report_path)

    inner_children: List[Any] = [_page_head()]
    empty = _empty_state()

    if experiment is None:
        # 無資料 — 顯示 empty state
        empty.style = {"display": "block"}
        inner_children.append(empty)
    else:
        result = _build_result(experiment, report_md)
        empty.style = {"display": "none"}
        inner_children.extend(
            [
                _verdict_section(result),
                _explainer_section(),
                _what_we_tested_section(result),
                _metrics_section(result),
                _recommendation_section(result),
                _details_section(result),
                empty,
            ]
        )

    # 根容器：自帶 scroll（`.main-container` 設了 overflow:hidden + height:100vh）
    return html.Div(
        id="strategy-page",
        className="strategy-page",
        style={
            "height": "calc(100vh - 100px)",
            "overflowY": "auto",
            "overflowX": "hidden",
            "boxSizing": "border-box",
        },
        children=[
            html.Div(
                className="strategy-page-inner",
                children=inner_children,
            ),
        ],
    )
