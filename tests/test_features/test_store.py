"""TASK-F03 — Feature Store schema + manifest (V2 §0.3, §0.6)."""

from __future__ import annotations

import json
from datetime import date, datetime, time
from pathlib import Path

import pandas as pd
import pytest

from src.features.corporate_actions import CorporateActionEvent
from src.features.store import (
    FeatureProvider,
    FeatureStore,
    FeatureValue,
    LookAheadError,
)


MARKET_CLOSE = time(13, 30)


def _daily_df(prices: list[float], start: str = "2025-01-02") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(prices), freq="B")
    return pd.DataFrame(
        {
            "open": prices,
            "high": [p * 1.01 for p in prices],
            "low": [p * 0.99 for p in prices],
            "close": prices,
            "volume": [1_000_000] * len(prices),
        },
        index=idx,
    )


def _close_provider() -> FeatureProvider:
    def compute(stock_id: str, ref_date: date, ohlc: pd.DataFrame) -> FeatureValue:
        ts = pd.Timestamp(ref_date)
        row = ohlc.loc[ts]
        return FeatureValue(
            value=float(row["adj_close"]),
            available_at=datetime.combine(ref_date, MARKET_CLOSE),
        )

    return FeatureProvider(name="close_adj", schema_version="v1", compute=compute)


def _future_provider() -> FeatureProvider:
    def compute(stock_id: str, ref_date: date, ohlc: pd.DataFrame) -> FeatureValue:
        return FeatureValue(
            value=1.0,
            available_at=datetime.combine(ref_date, time(23, 59)),
        )

    return FeatureProvider(name="leaky", schema_version="v1", compute=compute)


def _make_store(
    *,
    providers,
    raw_daily,
    corporate_actions=None,
    cache_dir: Path,
) -> FeatureStore:
    return FeatureStore(
        providers=providers,
        raw_daily=raw_daily,
        corporate_actions=corporate_actions or {},
        universe_version="u-2026-05-22",
        corp_action_version="ca-v1",
        git_commit="deadbeef",
        cache_dir=cache_dir,
        signal_close_time=MARKET_CLOSE,
    )


@pytest.mark.unit
def test_build_returns_multi_index_dataframe(tmp_path: Path) -> None:
    raw = {"2330": _daily_df([100, 101, 102]), "2317": _daily_df([50, 51, 52])}
    store = _make_store(providers=[_close_provider()], raw_daily=raw, cache_dir=tmp_path)

    df = store.build(
        stock_ids=["2330", "2317"],
        start=date(2025, 1, 2),
        end=date(2025, 1, 6),
    )

    assert isinstance(df.index, pd.MultiIndex)
    assert df.index.names == ["date", "stock_id"]
    assert {"2330", "2317"} == set(df.index.get_level_values("stock_id"))


@pytest.mark.unit
def test_build_includes_provider_columns(tmp_path: Path) -> None:
    raw = {"2330": _daily_df([100, 101, 102])}
    store = _make_store(providers=[_close_provider()], raw_daily=raw, cache_dir=tmp_path)

    df = store.build(["2330"], date(2025, 1, 2), date(2025, 1, 6))

    assert "close_adj" in df.columns
    expected_last = 102.0
    last_row = df.xs("2330", level="stock_id").iloc[-1]
    assert last_row["close_adj"] == pytest.approx(expected_last)


@pytest.mark.unit
def test_build_uses_backward_adjusted_ohlc(tmp_path: Path) -> None:
    raw = {"2330": _daily_df([100, 100, 100, 100])}
    events = {
        "2330": [
            CorporateActionEvent.from_factor(
                ex_date=date(2025, 1, 6),
                adjustment_factor=0.5,
                event_type="stock_split",
            )
        ]
    }
    store = _make_store(
        providers=[_close_provider()],
        raw_daily=raw,
        corporate_actions=events,
        cache_dir=tmp_path,
    )

    df = store.build(["2330"], date(2025, 1, 2), date(2025, 1, 7))
    series = df.xs("2330", level="stock_id")["close_adj"]

    assert series.loc[pd.Timestamp("2025-01-02")] == pytest.approx(50.0)
    assert series.loc[pd.Timestamp("2025-01-03")] == pytest.approx(50.0)
    assert series.loc[pd.Timestamp("2025-01-06")] == pytest.approx(100.0)


@pytest.mark.unit
def test_build_raises_lookahead_error_for_future_feature(tmp_path: Path) -> None:
    raw = {"2330": _daily_df([100, 101, 102])}
    store = _make_store(providers=[_future_provider()], raw_daily=raw, cache_dir=tmp_path)

    with pytest.raises(LookAheadError):
        store.build(["2330"], date(2025, 1, 2), date(2025, 1, 6))


@pytest.mark.unit
def test_build_is_deterministic(tmp_path: Path) -> None:
    raw = {"2330": _daily_df([100, 101, 102])}
    store_a = _make_store(providers=[_close_provider()], raw_daily=raw, cache_dir=tmp_path)
    store_b = _make_store(providers=[_close_provider()], raw_daily=raw, cache_dir=tmp_path)

    df_a = store_a.build(["2330"], date(2025, 1, 2), date(2025, 1, 6))
    df_b = store_b.build(["2330"], date(2025, 1, 2), date(2025, 1, 6))

    pd.testing.assert_frame_equal(df_a, df_b)


@pytest.mark.unit
def test_manifest_contains_required_fields(tmp_path: Path) -> None:
    raw = {"2330": _daily_df([100, 101, 102])}
    store = _make_store(providers=[_close_provider()], raw_daily=raw, cache_dir=tmp_path)
    store.build(["2330"], date(2025, 1, 2), date(2025, 1, 6))

    manifest = store.manifest()

    required = {
        "raw_data_range",
        "raw_data_hash",
        "universe_version",
        "feature_schema_version",
        "corp_action_version",
        "git_commit",
        "generated_at",
        "manifest_hash",
    }
    assert required.issubset(manifest.keys())
    assert manifest["universe_version"] == "u-2026-05-22"
    assert manifest["corp_action_version"] == "ca-v1"
    assert manifest["git_commit"] == "deadbeef"
    assert "2330" in manifest["raw_data_range"]


@pytest.mark.unit
def test_manifest_persisted_to_cache_dir(tmp_path: Path) -> None:
    raw = {"2330": _daily_df([100, 101, 102])}
    store = _make_store(providers=[_close_provider()], raw_daily=raw, cache_dir=tmp_path)
    store.build(["2330"], date(2025, 1, 2), date(2025, 1, 6))

    manifest = store.manifest()
    expected = tmp_path / f"manifest_{manifest['manifest_hash']}.json"
    assert expected.exists()

    payload = json.loads(expected.read_text())
    assert payload["manifest_hash"] == manifest["manifest_hash"]


@pytest.mark.unit
def test_manifest_hash_stable_across_builds(tmp_path: Path) -> None:
    raw = {"2330": _daily_df([100, 101, 102])}
    store_a = _make_store(providers=[_close_provider()], raw_daily=raw, cache_dir=tmp_path)
    store_b = _make_store(providers=[_close_provider()], raw_daily=raw, cache_dir=tmp_path)

    store_a.build(["2330"], date(2025, 1, 2), date(2025, 1, 6))
    store_b.build(["2330"], date(2025, 1, 2), date(2025, 1, 6))

    assert store_a.manifest()["manifest_hash"] == store_b.manifest()["manifest_hash"]
