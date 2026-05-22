"""TASK-J01 — TradeJournal."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from src.backtest.engine import Trade
from src.journal.trade_journal import (
    CashLedgerEntry,
    CostBreakdown,
    FillSnapshot,
    TradeJournal,
    TradeJournalEntry,
)


def _entry(**overrides) -> TradeJournalEntry:
    base = dict(
        trade_id="t-001",
        stock_id="2330",
        signal_timestamp=datetime(2026, 5, 20, 13, 30),
        signal_snapshot={"action": "entry", "score": 0.82},
        quote_snapshot={"current_price": 100.0},
        feature_snapshot={"ma_20": 95.0, "atr_14": 3.5},
        entry_fill=FillSnapshot(
            fill_date=date(2026, 5, 21),
            price=100.0,
            shares=1000,
            requested_shares=1000,
            fill_ratio=1.0,
        ),
        exit_fill=FillSnapshot(
            fill_date=date(2026, 5, 24),
            price=110.0,
            shares=1000,
            requested_shares=1000,
            fill_ratio=1.0,
        ),
        exit_reason="take_profit",
        costs=CostBreakdown(fees_in=142.5, fees_out=156.75, tax=330.0, slippage=20.0),
        cash_ledger=[
            CashLedgerEntry(date=date(2026, 5, 21), kind="buy", amount=-100142.5),
            CashLedgerEntry(date=date(2026, 5, 26), kind="sell_settlement", amount=109513.25),
        ],
        notes=["smoke"],
    )
    base.update(overrides)
    return TradeJournalEntry(**base)


@pytest.mark.unit
def test_entry_computes_gross_net_pnl_and_holding_days() -> None:
    entry = _entry()

    assert entry.gross_pnl == pytest.approx(10_000.0)
    assert entry.net_pnl == pytest.approx(9_350.75)
    assert entry.net_pnl_pct == pytest.approx(0.0935075)
    assert entry.holding_days == 3


@pytest.mark.unit
def test_entry_roundtrips_to_json_dict() -> None:
    entry = _entry()

    restored = TradeJournalEntry.from_dict(entry.to_dict())

    assert restored == entry
    assert restored.signal_timestamp == datetime(2026, 5, 20, 13, 30)
    assert restored.cash_ledger[1].date == date(2026, 5, 26)


@pytest.mark.unit
def test_journal_records_append_only_jsonl(tmp_path: Path) -> None:
    journal = TradeJournal(tmp_path)

    first = journal.record(_entry(trade_id="t-001"))
    second = journal.record(_entry(trade_id="t-002", stock_id="2317"))

    assert first.trade_id == "t-001"
    assert second.trade_id == "t-002"
    assert len((tmp_path / "trades.jsonl").read_text().splitlines()) == 2


@pytest.mark.unit
def test_journal_loads_all_records_sorted_by_signal_timestamp(tmp_path: Path) -> None:
    journal = TradeJournal(tmp_path)
    later = _entry(trade_id="later", signal_timestamp=datetime(2026, 5, 21, 13, 30))
    earlier = _entry(trade_id="earlier", signal_timestamp=datetime(2026, 5, 20, 13, 30))

    journal.record(later)
    journal.record(earlier)

    assert [e.trade_id for e in journal.list()] == ["earlier", "later"]


@pytest.mark.unit
def test_journal_filters_by_stock_id(tmp_path: Path) -> None:
    journal = TradeJournal(tmp_path)
    journal.record(_entry(trade_id="a", stock_id="2330"))
    journal.record(_entry(trade_id="b", stock_id="2317"))

    assert [e.trade_id for e in journal.list(stock_id="2330")] == ["a"]


@pytest.mark.unit
def test_from_backtest_trade_preserves_costs_and_cash_ledger() -> None:
    trade = Trade(
        stock_id="2330",
        entry_date=date(2026, 5, 21),
        entry_price=100.0,
        exit_date=date(2026, 5, 24),
        exit_price=110.0,
        shares=1000,
        pnl=9350.75,
        pnl_pct=0.0935075,
        fees=299.25,
        tax=330.0,
        reason="take_profit",
    )

    entry = TradeJournalEntry.from_backtest_trade(
        trade,
        signal_timestamp=datetime(2026, 5, 20, 13, 30),
        signal_snapshot={"action": "entry"},
        quote_snapshot={"current_price": 100.0},
        feature_snapshot={"atr_14": 3.5},
        fees_in=142.5,
        fees_out=156.75,
        settlement_date=date(2026, 5, 26),
    )

    assert entry.trade_id.startswith("2330-2026-05-21-2026-05-24")
    assert entry.costs.total == pytest.approx(649.25)
    assert entry.net_pnl == pytest.approx(trade.pnl)
    assert entry.cash_ledger[1].kind == "sell_settlement"


@pytest.mark.unit
def test_journal_summary_aggregates_trade_count_and_net_pnl(tmp_path: Path) -> None:
    journal = TradeJournal(tmp_path)
    journal.record(_entry(trade_id="a"))
    journal.record(_entry(trade_id="b", exit_fill=FillSnapshot(date(2026, 5, 24), 90.0, 1000, 1000, 1.0)))

    summary = journal.summary()

    assert summary["trade_count"] == 2
    assert summary["net_pnl"] == pytest.approx(-1298.5)
    assert summary["gross_pnl"] == pytest.approx(0.0)
