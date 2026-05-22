"""TASK-J04 — Experiment registry (V2 §3.8).

Append-only, per-experiment JSON store under ``registry_dir/{id}.json``.
Same manifest → same id → dedupe. Failed runs are recorded with
``status="failed"`` so wins and losses are equally visible.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

__all__ = ["ExperimentRecord", "ExperimentRegistry"]


def _manifest_hash(manifest: Mapping[str, Any]) -> str:
    serialised = json.dumps(manifest, sort_keys=True, default=str)
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()[:16]


@dataclass
class ExperimentRecord:
    experiment_id: str
    manifest: Mapping[str, Any]
    summary: Mapping[str, Any]
    status: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "manifest": dict(self.manifest),
            "summary": dict(self.summary),
            "status": self.status,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExperimentRecord":
        return cls(
            experiment_id=data["experiment_id"],
            manifest=data.get("manifest", {}),
            summary=data.get("summary", {}),
            status=data.get("status", "success"),
            created_at=data.get("created_at", ""),
        )


class ExperimentRegistry:
    def __init__(self, registry_dir: Path) -> None:
        self._dir = Path(registry_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        manifest: Mapping[str, Any],
        summary: Mapping[str, Any],
        status: str = "success",
    ) -> ExperimentRecord:
        eid = _manifest_hash(manifest)
        path = self._dir / f"{eid}.json"
        if path.exists():
            return ExperimentRecord.from_dict(json.loads(path.read_text()))
        record = ExperimentRecord(
            experiment_id=eid,
            manifest=dict(manifest),
            summary=dict(summary),
            status=status,
            created_at=datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        )
        path.write_text(json.dumps(record.to_dict(), indent=2, sort_keys=True))
        return record

    def lookup(self, experiment_id: str) -> ExperimentRecord | None:
        path = self._dir / f"{experiment_id}.json"
        if not path.exists():
            return None
        return ExperimentRecord.from_dict(json.loads(path.read_text()))

    def list(self) -> list[ExperimentRecord]:
        records: list[ExperimentRecord] = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                records.append(ExperimentRecord.from_dict(json.loads(path.read_text())))
            except json.JSONDecodeError:
                continue
        return records
