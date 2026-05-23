"""TASK-J02 — Append-only signal log including filtered signals (V2 §5.2)."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional

from src.portfolio.risk_manager import RiskDecision
from src.signals.engine import Signal

__all__ = ["SignalLog", "SignalLogEntry"]


@dataclass(frozen=True)
class SignalLogEntry:
    signal: Signal
    entered: bool
    target_shares: int = 0
    approved_shares: int = 0
    filter_reasons: list[str] = field(default_factory=list)
    risk_decision: Optional[RiskDecision] = None
    quote_snapshot: Mapping[str, Any] = field(default_factory=dict)
    context_snapshot: Mapping[str, Any] = field(default_factory=dict)
    linked_trade_id: Optional[str] = None

    @property
    def stock_id(self) -> str:
        return self.signal.stock_id

    @property
    def timestamp(self) -> datetime:
        return self.signal.timestamp

    @property
    def was_filtered(self) -> bool:
        return not self.entered

    @property
    def signal_snapshot(self) -> dict[str, Any]:
        return self.signal.to_dict()

    @property
    def risk_decision_snapshot(self) -> dict[str, Any] | None:
        if self.risk_decision is None:
            return None
        return {
            "allowed": self.risk_decision.allowed,
            "approved_shares": self.risk_decision.approved_shares,
            "risk_amount": self.risk_decision.risk_amount,
            "reasons": list(self.risk_decision.reasons),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal_snapshot,
            "entered": self.entered,
            "target_shares": self.target_shares,
            "approved_shares": self.approved_shares,
            "filter_reasons": list(self.filter_reasons),
            "risk_decision": self.risk_decision_snapshot,
            "quote_snapshot": dict(self.quote_snapshot),
            "context_snapshot": dict(self.context_snapshot),
            "linked_trade_id": self.linked_trade_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SignalLogEntry":
        risk_data = data.get("risk_decision")
        risk_decision = None
        if risk_data is not None:
            risk_decision = RiskDecision(
                allowed=bool(risk_data["allowed"]),
                approved_shares=int(risk_data["approved_shares"]),
                risk_amount=float(risk_data["risk_amount"]),
                reasons=list(risk_data.get("reasons", [])),
            )
        return cls(
            signal=Signal.from_dict(dict(data["signal"])),
            entered=bool(data["entered"]),
            target_shares=int(data.get("target_shares", 0)),
            approved_shares=int(data.get("approved_shares", 0)),
            filter_reasons=list(data.get("filter_reasons", [])),
            risk_decision=risk_decision,
            quote_snapshot=dict(data.get("quote_snapshot", {})),
            context_snapshot=dict(data.get("context_snapshot", {})),
            linked_trade_id=data.get("linked_trade_id"),
        )

    @classmethod
    def from_signal(
        cls,
        signal: Signal,
        *,
        risk_decision: Optional[RiskDecision] = None,
        target_shares: int = 0,
        quote_snapshot: Optional[Mapping[str, Any]] = None,
        context_snapshot: Optional[Mapping[str, Any]] = None,
        linked_trade_id: Optional[str] = None,
        filter_reasons: Optional[list[str]] = None,
    ) -> "SignalLogEntry":
        entered = bool(risk_decision.allowed) if risk_decision is not None else linked_trade_id is not None
        approved_shares = risk_decision.approved_shares if risk_decision is not None else 0
        reasons = list(filter_reasons or [])
        if not reasons and risk_decision is not None and not risk_decision.allowed:
            reasons = list(risk_decision.reasons)
        return cls(
            signal=signal,
            entered=entered,
            target_shares=target_shares,
            approved_shares=approved_shares,
            filter_reasons=reasons,
            risk_decision=risk_decision,
            quote_snapshot=dict(quote_snapshot or {}),
            context_snapshot=dict(context_snapshot or {}),
            linked_trade_id=linked_trade_id,
        )


class SignalLog:
    def __init__(self, log_dir: Path, filename: str = "signals.jsonl") -> None:
        self._dir = Path(log_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / filename

    def record(self, entry: SignalLogEntry) -> SignalLogEntry:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        return entry

    def list(
        self,
        *,
        stock_id: Optional[str] = None,
        entered: Optional[bool] = None,
    ) -> list[SignalLogEntry]:
        if not self._path.exists():
            return []
        entries: list[SignalLogEntry] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = SignalLogEntry.from_dict(json.loads(line))
            if stock_id is not None and entry.stock_id != stock_id:
                continue
            if entered is not None and entry.entered != entered:
                continue
            entries.append(entry)
        return entries

    def summary(self) -> dict[str, Any]:
        entries = self.list()
        reasons: Counter[str] = Counter()
        for entry in entries:
            if not entry.entered:
                reasons.update(entry.filter_reasons or ["unknown"])
        return {
            "signal_count": len(entries),
            "entered_count": sum(1 for e in entries if e.entered),
            "filtered_count": sum(1 for e in entries if not e.entered),
            "filter_reasons": dict(reasons),
        }
