"""TASK-J02 — SignalLog."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from src.journal.signal_log import SignalLog, SignalLogEntry
from src.portfolio.risk_manager import RiskDecision
from src.signals.engine import Signal


def _signal(stock_id: str = "2330", ts: datetime | None = None) -> Signal:
    return Signal(
        timestamp=ts or datetime(2026, 5, 20, 13, 30),
        stock_id=stock_id,
        action="entry",
        side="long",
        score=0.82,
        confidence=0.76,
        reasons=["volume_spike", "ma_trend"],
        invalidations=[],
        features_snapshot={"close": 100.0, "atr_14": 3.5},
    )


def _entry(**overrides) -> SignalLogEntry:
    base = dict(
        signal=_signal(),
        entered=True,
        target_shares=1000,
        approved_shares=1000,
        filter_reasons=[],
        risk_decision=RiskDecision(True, 1000, 5000.0, []),
        quote_snapshot={"current_price": 100.0},
        context_snapshot={"regime": "bull"},
        linked_trade_id="trade-001",
    )
    base.update(overrides)
    return SignalLogEntry(**base)


@pytest.mark.unit
def test_entry_records_signal_snapshot_and_entered_state() -> None:
    entry = _entry()

    assert entry.stock_id == "2330"
    assert entry.timestamp == datetime(2026, 5, 20, 13, 30)
    assert entry.entered is True
    assert entry.was_filtered is False
    assert entry.signal_snapshot["score"] == pytest.approx(0.82)


@pytest.mark.unit
def test_blocked_signal_records_filter_reasons_and_risk_decision() -> None:
    entry = _entry(
        entered=False,
        approved_shares=0,
        filter_reasons=["daily_loss_limit", "cash_insufficient"],
        risk_decision=RiskDecision(False, 0, 8000.0, ["daily_loss_limit"]),
        linked_trade_id=None,
    )

    assert entry.was_filtered is True
    assert entry.filter_reasons == ["daily_loss_limit", "cash_insufficient"]
    assert entry.risk_decision_snapshot["allowed"] is False
    assert entry.risk_decision_snapshot["reasons"] == ["daily_loss_limit"]


@pytest.mark.unit
def test_entry_roundtrips_to_json_dict() -> None:
    entry = _entry()

    restored = SignalLogEntry.from_dict(entry.to_dict())

    assert restored == entry
    assert restored.signal.stock_id == "2330"
    assert restored.risk_decision == RiskDecision(True, 1000, 5000.0, [])


@pytest.mark.unit
def test_signal_log_records_append_only_jsonl(tmp_path: Path) -> None:
    log = SignalLog(tmp_path)

    log.record(_entry(signal=_signal("2330")))
    log.record(_entry(signal=_signal("2317"), linked_trade_id="trade-002"))

    assert len((tmp_path / "signals.jsonl").read_text().splitlines()) == 2
    assert [entry.stock_id for entry in log.list()] == ["2330", "2317"]


@pytest.mark.unit
def test_signal_log_filters_by_entered_and_stock_id(tmp_path: Path) -> None:
    log = SignalLog(tmp_path)
    log.record(_entry(signal=_signal("2330"), entered=True))
    log.record(_entry(signal=_signal("2317"), entered=False, approved_shares=0, filter_reasons=["max_positions"]))
    log.record(_entry(signal=_signal("2330"), entered=False, approved_shares=0, filter_reasons=["daily_loss_limit"]))

    assert [entry.stock_id for entry in log.list(entered=True)] == ["2330"]
    assert [entry.filter_reasons[0] for entry in log.list(stock_id="2330", entered=False)] == ["daily_loss_limit"]


@pytest.mark.unit
def test_summary_counts_entered_filtered_and_reasons(tmp_path: Path) -> None:
    log = SignalLog(tmp_path)
    log.record(_entry(entered=True))
    log.record(_entry(entered=False, approved_shares=0, filter_reasons=["daily_loss_limit"]))
    log.record(_entry(entered=False, approved_shares=0, filter_reasons=["daily_loss_limit", "cash_insufficient"]))

    summary = log.summary()

    assert summary["signal_count"] == 3
    assert summary["entered_count"] == 1
    assert summary["filtered_count"] == 2
    assert summary["filter_reasons"] == {"daily_loss_limit": 2, "cash_insufficient": 1}


@pytest.mark.unit
def test_from_signal_and_risk_decision_builds_blocked_entry() -> None:
    entry = SignalLogEntry.from_signal(
        _signal(),
        risk_decision=RiskDecision(False, 0, 5000.0, ["single_trade_risk"]),
        target_shares=2000,
        quote_snapshot={"current_price": 100.0},
    )

    assert entry.entered is False
    assert entry.approved_shares == 0
    assert entry.filter_reasons == ["single_trade_risk"]
