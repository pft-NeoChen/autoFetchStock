"""TASK-J04 — Experiment registry (V2 §3.8)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.journal.experiment_registry import (
    ExperimentRecord,
    ExperimentRegistry,
)


def _manifest() -> dict:
    return {
        "universe_version": "u-2026-05-22",
        "feature_schema_version": "fs-v1",
        "corp_action_version": "ca-v1",
        "strategy_config": {"ma_window": 20},
        "git_commit": "deadbeef",
    }


def _summary() -> dict:
    return {
        "n_trades": 42,
        "total_return_pct": 15.2,
        "sharpe": 0.9,
        "max_drawdown_pct": -8.0,
    }


@pytest.mark.unit
def test_registry_init_empty(tmp_path: Path) -> None:
    reg = ExperimentRegistry(tmp_path)
    assert reg.list() == []


@pytest.mark.unit
def test_record_creates_disk_entry(tmp_path: Path) -> None:
    reg = ExperimentRegistry(tmp_path)
    rec = reg.record(manifest=_manifest(), summary=_summary())
    assert isinstance(rec, ExperimentRecord)
    path = tmp_path / f"{rec.experiment_id}.json"
    assert path.exists()
    payload = json.loads(path.read_text())
    assert payload["experiment_id"] == rec.experiment_id
    assert payload["status"] == "success"


@pytest.mark.unit
def test_record_same_manifest_dedupes(tmp_path: Path) -> None:
    reg = ExperimentRegistry(tmp_path)
    rec_a = reg.record(manifest=_manifest(), summary=_summary())
    rec_b = reg.record(manifest=_manifest(), summary=_summary())
    assert rec_a.experiment_id == rec_b.experiment_id
    assert len(reg.list()) == 1


@pytest.mark.unit
def test_record_failed_experiment(tmp_path: Path) -> None:
    reg = ExperimentRegistry(tmp_path)
    rec = reg.record(
        manifest=_manifest(),
        summary={"error": "ZeroDivisionError"},
        status="failed",
    )
    assert rec.status == "failed"
    payload = json.loads((tmp_path / f"{rec.experiment_id}.json").read_text())
    assert payload["status"] == "failed"


@pytest.mark.unit
def test_lookup_by_id_returns_record(tmp_path: Path) -> None:
    reg = ExperimentRegistry(tmp_path)
    rec = reg.record(manifest=_manifest(), summary=_summary())
    found = reg.lookup(rec.experiment_id)
    assert found is not None
    assert found.experiment_id == rec.experiment_id


@pytest.mark.unit
def test_lookup_missing_returns_none(tmp_path: Path) -> None:
    reg = ExperimentRegistry(tmp_path)
    assert reg.lookup("does_not_exist") is None


@pytest.mark.unit
def test_list_returns_all_records(tmp_path: Path) -> None:
    reg = ExperimentRegistry(tmp_path)
    m1 = _manifest()
    m2 = {**_manifest(), "strategy_config": {"ma_window": 60}}
    rec1 = reg.record(manifest=m1, summary=_summary())
    rec2 = reg.record(manifest=m2, summary=_summary())
    records = reg.list()
    assert {r.experiment_id for r in records} == {rec1.experiment_id, rec2.experiment_id}
