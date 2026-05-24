"""TASK-UI01 — strategy page tests (V2 §7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.app.pages.strategy import (
    create_strategy_page_layout,
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
