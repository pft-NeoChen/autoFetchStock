"""TASK-F03 — Feature Store schema + manifest (V2 §0.3, §0.6).

The store enforces point-in-time correctness: any provider that returns a
value whose ``available_at`` exceeds the row's signal timestamp raises
``LookAheadError``. Each ``build`` produces a manifest persisted to the
configured cache directory.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from src.features.corporate_actions import (
    ADJUSTED_COLUMNS,
    CorporateActionEvent,
    apply_backward_adjustment,
)
from src.features.manifest import (
    compute_dataframe_hash,
    compute_manifest_hash,
    raw_data_range,
    schema_version_hash,
)

__all__ = [
    "FeatureProvider",
    "FeatureStore",
    "FeatureValue",
    "LookAheadError",
]


class LookAheadError(RuntimeError):
    """Raised when a feature value would only be available after the signal timestamp."""


@dataclass(frozen=True)
class FeatureValue:
    value: float
    available_at: datetime


ProviderFn = Callable[[str, date, pd.DataFrame], Optional[FeatureValue]]


@dataclass(frozen=True)
class FeatureProvider:
    name: str
    schema_version: str
    compute: ProviderFn


class FeatureStore:
    def __init__(
        self,
        *,
        providers: Sequence[FeatureProvider],
        raw_daily: Mapping[str, pd.DataFrame],
        corporate_actions: Mapping[str, Iterable[CorporateActionEvent]] | None = None,
        universe_version: str,
        corp_action_version: str,
        git_commit: str,
        cache_dir: Path | None = None,
        signal_close_time: time = time(13, 30),
    ) -> None:
        self._providers = list(providers)
        self._raw_daily = {k: v.copy() for k, v in raw_daily.items()}
        self._corporate_actions = {
            k: list(v) for k, v in (corporate_actions or {}).items()
        }
        self._universe_version = universe_version
        self._corp_action_version = corp_action_version
        self._git_commit = git_commit
        self._cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._signal_close_time = signal_close_time
        self._manifest: dict[str, Any] | None = None
        self._adjusted_cache: dict[str, pd.DataFrame] = {}

    def build(
        self,
        stock_ids: Sequence[str],
        start: date,
        end: date,
    ) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        for stock_id in stock_ids:
            adjusted = self._adjusted_frame(stock_id)
            window = self._window(adjusted, start, end)
            for ts in window.index:
                ref_date = ts.date()
                signal_ts = datetime.combine(ref_date, self._signal_close_time)
                record: dict[str, Any] = {"date": ts, "stock_id": stock_id}
                for provider in self._providers:
                    fv = provider.compute(stock_id, ref_date, adjusted)
                    if fv is None:
                        record[provider.name] = float("nan")
                        continue
                    if fv.available_at > signal_ts:
                        raise LookAheadError(
                            f"feature '{provider.name}' for {stock_id}@{ref_date} "
                            f"available_at={fv.available_at.isoformat()} > "
                            f"signal_ts={signal_ts.isoformat()}"
                        )
                    record[provider.name] = fv.value
                rows.append(record)

        if not rows:
            columns = ["date", "stock_id", *(p.name for p in self._providers)]
            df = pd.DataFrame(columns=columns)
        else:
            df = pd.DataFrame(rows)
        df = df.set_index(["date", "stock_id"]).sort_index()
        self._manifest = self._build_manifest()
        self._persist_manifest(self._manifest)
        return df

    def manifest(self) -> dict[str, Any]:
        if self._manifest is None:
            raise RuntimeError("manifest() called before build()")
        return dict(self._manifest)

    def _adjusted_frame(self, stock_id: str) -> pd.DataFrame:
        if stock_id in self._adjusted_cache:
            return self._adjusted_cache[stock_id]
        if stock_id not in self._raw_daily:
            raise KeyError(f"raw_daily missing stock_id: {stock_id}")
        events = self._corporate_actions.get(stock_id, [])
        adjusted = apply_backward_adjustment(self._raw_daily[stock_id], events)
        # Promote adj_* to canonical columns so providers see backward-adjusted prices.
        for raw_col, adj_col in ADJUSTED_COLUMNS.items():
            adjusted[raw_col] = adjusted[adj_col]
        self._adjusted_cache[stock_id] = adjusted
        return adjusted

    @staticmethod
    def _window(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
        idx = pd.DatetimeIndex(pd.to_datetime(df.index)).normalize()
        mask = (idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))
        return df.loc[mask]

    def _build_manifest(self) -> dict[str, Any]:
        manifest: dict[str, Any] = {
            "raw_data_range": raw_data_range(self._raw_daily),
            "raw_data_hash": compute_dataframe_hash(self._raw_daily),
            "universe_version": self._universe_version,
            "feature_schema_version": schema_version_hash(
                (p.name, p.schema_version) for p in self._providers
            ),
            "corp_action_version": self._corp_action_version,
            "git_commit": self._git_commit,
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        manifest["manifest_hash"] = compute_manifest_hash(manifest)
        return manifest

    def _persist_manifest(self, manifest: Mapping[str, Any]) -> None:
        if self._cache_dir is None:
            return
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_dir / f"manifest_{manifest['manifest_hash']}.json"
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
