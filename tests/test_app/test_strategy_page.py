"""TASK-UI01 — strategy page tests (V2 §7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.app.pages.strategy import (
    MANIFEST_LABELS,
    SUMMARY_LABELS,
    create_strategy_page_layout,
    format_manifest_value,
    format_summary_value,
    load_latest_experiment,
)


pytestmark = pytest.mark.unit


def _write_experiment(
    dir_: Path, eid: str, trade_count: int, recorded_at: float
) -> None:
    payload = {
        "experiment_id": eid,
        "recorded_at": recorded_at,
        "manifest": {"strategy": "long_entry_v1", "universe_size": 139},
        "summary": {"trade_count": trade_count, "n_windows": 11, "total_pnl": 1234.5},
    }
    (dir_ / f"{eid}.json").write_text(json.dumps(payload))


def test_load_latest_experiment_picks_most_recent(tmp_path: Path) -> None:
    _write_experiment(tmp_path, "older", trade_count=10, recorded_at=100.0)
    _write_experiment(tmp_path, "newer", trade_count=20, recorded_at=200.0)
    record = load_latest_experiment(tmp_path)
    assert record is not None
    assert record["experiment_id"] == "newer"
    assert record["summary"]["trade_count"] == 20


def test_load_latest_experiment_missing_dir_returns_none(tmp_path: Path) -> None:
    assert load_latest_experiment(tmp_path / "absent") is None


def test_load_latest_experiment_skips_invalid_json(tmp_path: Path) -> None:
    _write_experiment(tmp_path, "good", trade_count=5, recorded_at=300.0)
    (tmp_path / "bad.json").write_text("{not json")
    record = load_latest_experiment(tmp_path)
    assert record is not None
    assert record["experiment_id"] == "good"


def test_create_strategy_page_layout_has_root_id(tmp_path: Path) -> None:
    _write_experiment(tmp_path, "exp1", trade_count=42, recorded_at=400.0)
    page = create_strategy_page_layout(tmp_path, report_path=tmp_path / "no.md")
    assert page.id == "strategy-page"


def test_create_strategy_page_layout_renders_verdict_when_experiment_exists(
    tmp_path: Path,
) -> None:
    _write_experiment(tmp_path, "exp1", trade_count=42, recorded_at=400.0)
    page = create_strategy_page_layout(tmp_path, report_path=tmp_path / "no.md")
    # Walk the children tree and confirm 'strategy-page-verdict' id present.
    found_ids = _collect_ids(page)
    assert "strategy-page-verdict" in found_ids
    assert "strategy-page-metrics" in found_ids
    assert "strategy-page-manifest" in found_ids


def test_create_strategy_page_layout_shows_empty_state_when_no_experiment(
    tmp_path: Path,
) -> None:
    page = create_strategy_page_layout(tmp_path, report_path=tmp_path / "no.md")
    found_ids = _collect_ids(page)
    assert "strategy-page-empty" in found_ids


# ── UI 優化 — 中文 label / 單位 / 內嵌報告 ──────────────────────────────────


def test_format_summary_value_total_pnl_uses_thousand_separator_and_unit() -> None:
    assert format_summary_value("total_pnl", 105159.0109) == "105,159 元"


def test_format_summary_value_trade_count_has_unit() -> None:
    assert format_summary_value("trade_count", 59) == "59 筆"


def test_format_manifest_value_universe_size_has_unit() -> None:
    assert format_manifest_value("universe_size", 139) == "139 檔"


def test_format_manifest_value_months() -> None:
    assert format_manifest_value("is_months", 12) == "12 月"
    assert format_manifest_value("embargo_business_days", 15) == "15 交易日"


def test_format_manifest_value_initial_cash() -> None:
    assert format_manifest_value("initial_cash_per_stock", 1_000_000.0) == "1,000,000 元"


def test_summary_labels_cover_known_keys() -> None:
    expected = {
        "trade_count", "n_windows", "total_pnl",
        "is_trade_count", "is_total_pnl",
    }
    assert expected.issubset(set(SUMMARY_LABELS))


def test_manifest_labels_cover_known_keys() -> None:
    expected = {
        "strategy", "universe_size", "data_span_start", "data_span_end",
        "is_months", "oos_months", "embargo_business_days",
        "initial_cash_per_stock", "target_shares", "experiment_id",
    }
    assert expected.issubset(set(MANIFEST_LABELS))


def test_strategy_page_includes_overview_panel(tmp_path: Path) -> None:
    _write_experiment(tmp_path, "exp1", trade_count=10, recorded_at=100.0)
    page = create_strategy_page_layout(tmp_path, report_path=tmp_path / "no.md")
    ids = _collect_ids(page)
    assert "strategy-page-overview" in ids


def test_strategy_page_inline_report_when_md_exists(tmp_path: Path) -> None:
    _write_experiment(tmp_path, "exp1", trade_count=10, recorded_at=100.0)
    report_path = tmp_path / "report.md"
    report_path.write_text("# Inline report content")
    page = create_strategy_page_layout(tmp_path, report_path=report_path)
    ids = _collect_ids(page)
    assert "strategy-page-report" in ids


def test_strategy_page_inline_report_handles_missing_md(tmp_path: Path) -> None:
    _write_experiment(tmp_path, "exp1", trade_count=10, recorded_at=100.0)
    page = create_strategy_page_layout(tmp_path, report_path=tmp_path / "missing.md")
    ids = _collect_ids(page)
    # Still renders the report section (with empty-state message).
    assert "strategy-page-report" in ids


def _collect_ids(component) -> set[str]:
    """Walk a Dash component tree gathering element ``id`` values."""
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
