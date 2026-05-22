"""TASK-J01 — Append-only trade journal (V2 §5.1)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Optional

from src.backtest.engine import Trade

__all__ = [
    "CashLedgerEntry",
    "CostBreakdown",
    "FillSnapshot",
    "TradeJournal",
    "TradeJournalEntry",
]


@dataclass(frozen=True)
class FillSnapshot:
    fill_date: date
    price: float
    shares: int
    requested_shares: int
    fill_ratio: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "fill_date": self.fill_date.isoformat(),
            "price": self.price,
            "shares": self.shares,
            "requested_shares": self.requested_shares,
            "fill_ratio": self.fill_ratio,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FillSnapshot":
        return cls(
            fill_date=date.fromisoformat(str(data["fill_date"])),
            price=float(data["price"]),
            shares=int(data["shares"]),
            requested_shares=int(data["requested_shares"]),
            fill_ratio=float(data["fill_ratio"]),
        )


@dataclass(frozen=True)
class CostBreakdown:
    fees_in: float = 0.0
    fees_out: float = 0.0
    tax: float = 0.0
    slippage: float = 0.0

    @property
    def total(self) -> float:
        return self.fees_in + self.fees_out + self.tax + self.slippage

    def to_dict(self) -> dict[str, float]:
        return {
            "fees_in": self.fees_in,
            "fees_out": self.fees_out,
            "tax": self.tax,
            "slippage": self.slippage,
            "total": self.total,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CostBreakdown":
        return cls(
            fees_in=float(data.get("fees_in", 0.0)),
            fees_out=float(data.get("fees_out", 0.0)),
            tax=float(data.get("tax", 0.0)),
            slippage=float(data.get("slippage", 0.0)),
        )


@dataclass(frozen=True)
class CashLedgerEntry:
    date: date
    kind: str
    amount: float

    def to_dict(self) -> dict[str, Any]:
        return {"date": self.date.isoformat(), "kind": self.kind, "amount": self.amount}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CashLedgerEntry":
        return cls(
            date=date.fromisoformat(str(data["date"])),
            kind=str(data["kind"]),
            amount=float(data["amount"]),
        )


@dataclass(frozen=True)
class TradeJournalEntry:
    trade_id: str
    stock_id: str
    signal_timestamp: datetime
    signal_snapshot: Mapping[str, Any]
    quote_snapshot: Mapping[str, Any]
    feature_snapshot: Mapping[str, Any]
    entry_fill: FillSnapshot
    exit_fill: FillSnapshot
    exit_reason: str
    costs: CostBreakdown
    cash_ledger: list[CashLedgerEntry] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def gross_pnl(self) -> float:
        return (self.exit_fill.price - self.entry_fill.price) * self.entry_fill.shares

    @property
    def net_pnl(self) -> float:
        return self.gross_pnl - self.costs.total

    @property
    def net_pnl_pct(self) -> float:
        capital = self.entry_fill.price * self.entry_fill.shares
        return self.net_pnl / capital if capital else 0.0

    @property
    def holding_days(self) -> int:
        return (self.exit_fill.fill_date - self.entry_fill.fill_date).days

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "stock_id": self.stock_id,
            "signal_timestamp": self.signal_timestamp.isoformat(),
            "signal_snapshot": dict(self.signal_snapshot),
            "quote_snapshot": dict(self.quote_snapshot),
            "feature_snapshot": dict(self.feature_snapshot),
            "entry_fill": self.entry_fill.to_dict(),
            "exit_fill": self.exit_fill.to_dict(),
            "exit_reason": self.exit_reason,
            "costs": self.costs.to_dict(),
            "cash_ledger": [entry.to_dict() for entry in self.cash_ledger],
            "notes": list(self.notes),
            "gross_pnl": self.gross_pnl,
            "net_pnl": self.net_pnl,
            "net_pnl_pct": self.net_pnl_pct,
            "holding_days": self.holding_days,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TradeJournalEntry":
        return cls(
            trade_id=str(data["trade_id"]),
            stock_id=str(data["stock_id"]),
            signal_timestamp=datetime.fromisoformat(str(data["signal_timestamp"])),
            signal_snapshot=dict(data.get("signal_snapshot", {})),
            quote_snapshot=dict(data.get("quote_snapshot", {})),
            feature_snapshot=dict(data.get("feature_snapshot", {})),
            entry_fill=FillSnapshot.from_dict(data["entry_fill"]),
            exit_fill=FillSnapshot.from_dict(data["exit_fill"]),
            exit_reason=str(data.get("exit_reason", "")),
            costs=CostBreakdown.from_dict(data.get("costs", {})),
            cash_ledger=[
                CashLedgerEntry.from_dict(item)
                for item in data.get("cash_ledger", [])
            ],
            notes=list(data.get("notes", [])),
        )

    @classmethod
    def from_backtest_trade(
        cls,
        trade: Trade,
        *,
        signal_timestamp: datetime,
        signal_snapshot: Mapping[str, Any],
        quote_snapshot: Mapping[str, Any],
        feature_snapshot: Mapping[str, Any],
        fees_in: float,
        fees_out: float,
        settlement_date: date,
        trade_id: Optional[str] = None,
        slippage: Optional[float] = None,
        requested_shares: Optional[int] = None,
        notes: Optional[list[str]] = None,
    ) -> "TradeJournalEntry":
        requested = int(requested_shares or trade.shares)
        fill_ratio = trade.shares / requested if requested else 0.0
        gross_pnl = (trade.exit_price - trade.entry_price) * trade.shares
        inferred_slippage = gross_pnl - float(trade.pnl) - float(fees_in) - float(fees_out) - float(trade.tax)
        costs = CostBreakdown(
            fees_in=float(fees_in),
            fees_out=float(fees_out),
            tax=float(trade.tax),
            slippage=float(inferred_slippage if slippage is None else slippage),
        )
        tid = trade_id or (
            f"{trade.stock_id}-{trade.entry_date.isoformat()}-"
            f"{trade.exit_date.isoformat()}-{trade.reason}"
        )
        return cls(
            trade_id=tid,
            stock_id=trade.stock_id,
            signal_timestamp=signal_timestamp,
            signal_snapshot=dict(signal_snapshot),
            quote_snapshot=dict(quote_snapshot),
            feature_snapshot=dict(feature_snapshot),
            entry_fill=FillSnapshot(trade.entry_date, trade.entry_price, trade.shares, requested, fill_ratio),
            exit_fill=FillSnapshot(trade.exit_date, trade.exit_price, trade.shares, requested, fill_ratio),
            exit_reason=trade.reason,
            costs=costs,
            cash_ledger=[
                CashLedgerEntry(
                    date=trade.entry_date,
                    kind="buy",
                    amount=-(trade.entry_price * trade.shares + fees_in),
                ),
                CashLedgerEntry(
                    date=settlement_date,
                    kind="sell_settlement",
                    amount=(trade.exit_price * trade.shares - fees_out - trade.tax),
                ),
            ],
            notes=list(notes or []),
        )


class TradeJournal:
    def __init__(self, journal_dir: Path, filename: str = "trades.jsonl") -> None:
        self._dir = Path(journal_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / filename

    def record(self, entry: TradeJournalEntry) -> TradeJournalEntry:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        return entry

    def list(self, *, stock_id: Optional[str] = None) -> list[TradeJournalEntry]:
        if not self._path.exists():
            return []
        entries: list[TradeJournalEntry] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = TradeJournalEntry.from_dict(json.loads(line))
            if stock_id is None or entry.stock_id == stock_id:
                entries.append(entry)
        return sorted(entries, key=lambda e: (e.signal_timestamp, e.trade_id))

    def summary(self) -> dict[str, float | int]:
        entries = self.list()
        return {
            "trade_count": len(entries),
            "gross_pnl": sum(e.gross_pnl for e in entries),
            "net_pnl": sum(e.net_pnl for e in entries),
        }
