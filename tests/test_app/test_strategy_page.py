"""TASK-UI01 — strategy page tests (user-facing rewrite)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.app.pages.strategy import (
    MANIFEST_LABELS,
    METRIC_INTERPRETATIONS,
    SUMMARY_LABELS,
    build_recommendation,
    build_verdict_summary,
    create_strategy_page_layout,
    format_manifest_value,
    format_summary_value,
    load_latest_experiment,
)


pytestmark = pytest.mark.unit


def _write_experiment(
    dir_: Path,
    eid: str,
    *,
    trade_count: int,
    total_pnl: float = 0.0,
    recorded_at: float,
) -> None:
    payload = {
        "experiment_id": eid,
        "recorded_at": recorded_at,
        "manifest": {
            "strategy": "long_entry_v1",
            "universe_size": 139,
            "data_span_start": "2022-07-26",
            "data_span_end": "2026-05-22",
        },
        "summary": {
            "trade_count": trade_count,
            "n_windows": 11,
            "total_pnl": total_pnl,
        },
    }
    (dir_ / f"{eid}.json").write_text(json.dumps(payload))


# ── load_latest_experiment ─────────────────────────────────────────────────


def test_load_latest_experiment_picks_most_recent(tmp_path: Path) -> None:
    _write_experiment(tmp_path, "older", trade_count=10, recorded_at=100.0)
    _write_experiment(tmp_path, "newer", trade_count=20, recorded_at=200.0)
    record = load_latest_experiment(tmp_path)
    assert record is not None
    assert record["experiment_id"] == "newer"


def test_load_latest_experiment_missing_dir_returns_none(tmp_path: Path) -> None:
    assert load_latest_experiment(tmp_path / "absent") is None


# ── 中文 label + 單位 format ─────────────────────────────────────────────────


def test_format_summary_value_total_pnl() -> None:
    assert format_summary_value("total_pnl", 105159.0109) == "105,159 元"


def test_format_summary_value_trade_count() -> None:
    assert format_summary_value("trade_count", 59) == "59 筆"


def test_format_manifest_value_universe_size() -> None:
    assert format_manifest_value("universe_size", 139) == "139 檔"


def test_format_manifest_value_initial_cash() -> None:
    assert format_manifest_value("initial_cash_per_stock", 1_000_000.0) == "1,000,000 元"


def test_summary_labels_cover_known_keys() -> None:
    assert {"trade_count", "n_windows", "total_pnl",
            "is_trade_count", "is_total_pnl"}.issubset(set(SUMMARY_LABELS))


def test_manifest_labels_cover_known_keys() -> None:
    assert {"strategy", "universe_size", "data_span_start",
            "data_span_end", "is_months", "oos_months"}.issubset(set(MANIFEST_LABELS))


# ── 白話結論 ──────────────────────────────────────────────────────────────


def test_build_verdict_summary_negative_pnl_flags_no_edge() -> None:
    exp = {"summary": {"trade_count": 59, "total_pnl": -300}}
    v = build_verdict_summary(exp)
    assert "❌" in v["headline"]
    assert "穩定" in v["headline"] or "穩定" in v["reason"]
    assert "不建議" in v["action"] or "下實單" in v["action"]


def test_build_verdict_summary_zero_trades_says_no_signal() -> None:
    exp = {"summary": {"trade_count": 0, "total_pnl": 0}}
    v = build_verdict_summary(exp)
    assert "沒有產生" in v["headline"] or "❓" in v["headline"]


def test_build_verdict_summary_positive_with_sample() -> None:
    exp = {"summary": {"trade_count": 60, "total_pnl": 50_000}}
    v = build_verdict_summary(exp)
    assert "✅" in v["headline"] or "正向" in v["headline"]


def test_build_verdict_summary_positive_low_sample_flags_luck() -> None:
    exp = {"summary": {"trade_count": 10, "total_pnl": 50_000}}
    v = build_verdict_summary(exp)
    assert "樣本不足" in v["headline"] or "⚠️" in v["headline"]


def test_build_recommendation_negative_pnl_lists_actions() -> None:
    exp = {"summary": {"trade_count": 59, "total_pnl": -300}}
    items = build_recommendation(exp)
    assert any("不要" in it or "⛔" in it for it in items)
    assert any("替代" in it or "🔁" in it for it in items)


def test_metric_interpretations_describe_trade_count() -> None:
    text = METRIC_INTERPRETATIONS["trade_count"](59)
    assert "59" in text
    assert "樣本" in text


# ── 頁面結構 ─────────────────────────────────────────────────────────────


def _collect_ids(component) -> set[str]:
    ids: set[str] = set()
    if getattr(component, "id", None):
        ids.add(component.id)
    children = getattr(component, "children", None)
    if children is None:
        return ids
    if isinstance(children, (list, tuple)):
        for c in children:
            ids.update(_collect_ids(c))
    else:
        ids.update(_collect_ids(children))
    return ids


def test_strategy_page_renders_six_user_sections(tmp_path: Path) -> None:
    _write_experiment(tmp_path, "exp1", trade_count=59, total_pnl=-300, recorded_at=400.0)
    page = create_strategy_page_layout(tmp_path, report_path=tmp_path / "no.md")
    ids = _collect_ids(page)
    expected = {
        "strategy-page",
        "strategy-page-verdict",
        "strategy-page-explainer",
        "strategy-page-what-we-tested",
        "strategy-page-metrics",
        "strategy-page-recommendation",
        "strategy-page-details",
    }
    assert expected.issubset(ids)


def test_strategy_page_empty_state_when_no_experiment(tmp_path: Path) -> None:
    page = create_strategy_page_layout(tmp_path, report_path=tmp_path / "no.md")
    ids = _collect_ids(page)
    assert "strategy-page-empty" in ids


def test_strategy_page_root_has_no_max_height(tmp_path: Path) -> None:
    """Layout 根節點不該設 maxHeight，否則內容會被裁切無法 scroll。"""
    _write_experiment(tmp_path, "exp1", trade_count=10, recorded_at=100.0)
    page = create_strategy_page_layout(tmp_path, report_path=tmp_path / "no.md")
    style = page.style or {}
    assert "maxHeight" not in style
    assert "max-height" not in style


def test_strategy_page_does_not_leak_spec_jargon(tmp_path: Path) -> None:
    """Page 不該出現內部 spec reference（V2 §X / experiment_id raw / .md path）。"""
    _write_experiment(tmp_path, "exp1", trade_count=10, recorded_at=100.0)
    page = create_strategy_page_layout(tmp_path, report_path=tmp_path / "no.md")

    def collect_text(component) -> str:
        out = ""
        if isinstance(component, str):
            return component
        children = getattr(component, "children", None)
        if children is None:
            return ""
        if isinstance(children, (list, tuple)):
            for c in children:
                out += collect_text(c) + " "
        else:
            out += collect_text(children)
        return out

    text = collect_text(page)
    assert "STRATEGY_REVIEW.md" not in text
    assert "V2 §" not in text  # spec reference must not appear in user-facing copy
