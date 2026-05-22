"""TASK-F03 — Feature Store manifest (V2 §0.6)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

__all__ = [
    "compute_dataframe_hash",
    "compute_manifest_hash",
    "raw_data_range",
    "schema_version_hash",
]


def compute_dataframe_hash(frames: Mapping[str, pd.DataFrame]) -> str:
    hasher = hashlib.sha256()
    for key in sorted(frames):
        df = frames[key]
        hasher.update(key.encode("utf-8"))
        hasher.update(b"|")
        hasher.update(pd.util.hash_pandas_object(df, index=True).values.tobytes())
    return hasher.hexdigest()


def raw_data_range(frames: Mapping[str, pd.DataFrame]) -> dict[str, list[str]]:
    ranges: dict[str, list[str]] = {}
    for key in sorted(frames):
        df = frames[key]
        if df.empty:
            ranges[key] = []
            continue
        idx = pd.DatetimeIndex(pd.to_datetime(df.index))
        ranges[key] = [idx.min().isoformat(), idx.max().isoformat()]
    return ranges


def schema_version_hash(providers: Iterable[tuple[str, str]]) -> str:
    parts = sorted(f"{name}:{version}" for name, version in providers)
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def compute_manifest_hash(manifest: Mapping[str, Any]) -> str:
    payload = {k: v for k, v in manifest.items() if k not in {"manifest_hash", "generated_at"}}
    serialised = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()
