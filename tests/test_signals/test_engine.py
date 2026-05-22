"""TASK-S02 — Signal dataclass + SignalEngine framework (V2 §2)."""

from __future__ import annotations

from datetime import datetime
from typing import List

import pandas as pd
import pytest

from src.signals.engine import Signal, SignalEngine


# ---- Signal dataclass ----

@pytest.mark.unit
def test_signal_has_required_fields() -> None:
    sig = Signal(
        timestamp=datetime(2025, 1, 6, 13, 30),
        stock_id="2330",
        action="entry",
        side="long",
        score=0.7,
        confidence=0.8,
        reasons=["ma_trend", "atr_filter"],
        invalidations=["break_ma10"],
        features_snapshot={"ma_20": 100.0},
    )
    assert sig.timestamp.year == 2025
    assert sig.stock_id == "2330"
    assert sig.action == "entry"
    assert sig.side == "long"
    assert sig.reasons == ["ma_trend", "atr_filter"]


@pytest.mark.unit
def test_signal_has_no_risk_field() -> None:
    # V2 §2 修訂：risk 欄位移到 PositionSizer / RiskManager
    fields = {f.name for f in Signal.__dataclass_fields__.values()}
    assert "risk" not in fields
    assert "stop_loss" not in fields
    assert "position_size" not in fields


@pytest.mark.unit
def test_signal_to_dict_roundtrip() -> None:
    sig = Signal(
        timestamp=datetime(2025, 1, 6, 13, 30),
        stock_id="2330",
        action="entry",
        side="long",
        score=0.7,
        confidence=0.8,
        reasons=["r1"],
        invalidations=["i1"],
        features_snapshot={"x": 1.0},
    )
    d = sig.to_dict()
    assert d["stock_id"] == "2330"
    assert d["timestamp"] == "2025-01-06T13:30:00"
    restored = Signal.from_dict(d)
    assert restored == sig


@pytest.mark.unit
def test_signal_validates_action_and_side() -> None:
    with pytest.raises(ValueError):
        Signal(
            timestamp=datetime(2025, 1, 6),
            stock_id="2330",
            action="weird",
            side="long",
            score=0.5,
            confidence=0.5,
            reasons=[],
            invalidations=[],
            features_snapshot={},
        )
    with pytest.raises(ValueError):
        Signal(
            timestamp=datetime(2025, 1, 6),
            stock_id="2330",
            action="entry",
            side="diagonal",
            score=0.5,
            confidence=0.5,
            reasons=[],
            invalidations=[],
            features_snapshot={},
        )


# ---- SignalEngine ----

class _StubEngine(SignalEngine):
    def generate(self, feature_df: pd.DataFrame) -> List[Signal]:
        out: list[Signal] = []
        for (ts, sid), row in feature_df.iterrows():
            if row.get("trigger", False):
                out.append(
                    Signal(
                        timestamp=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                        stock_id=sid,
                        action="entry",
                        side="long",
                        score=float(row.get("score", 0.5)),
                        confidence=0.5,
                        reasons=["stub"],
                        invalidations=[],
                        features_snapshot=row.to_dict(),
                    )
                )
        return out


@pytest.mark.unit
def test_engine_can_be_subclassed_and_generates_signals() -> None:
    idx = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2025-01-06"), "2330"), (pd.Timestamp("2025-01-06"), "2317")],
        names=["date", "stock_id"],
    )
    df = pd.DataFrame({"trigger": [True, False], "score": [0.6, 0.0]}, index=idx)

    engine = _StubEngine()
    signals = engine.generate(df)

    assert len(signals) == 1
    assert signals[0].stock_id == "2330"
    assert signals[0].score == pytest.approx(0.6)


@pytest.mark.unit
def test_engine_empty_input_returns_empty_list() -> None:
    engine = _StubEngine()
    df = pd.DataFrame(
        columns=["trigger", "score"],
        index=pd.MultiIndex.from_arrays([[], []], names=["date", "stock_id"]),
    )
    assert engine.generate(df) == []


@pytest.mark.unit
def test_engine_base_class_generate_is_abstract() -> None:
    # Direct instantiation should fail because generate is abstract
    with pytest.raises(TypeError):
        SignalEngine()  # type: ignore[abstract]
