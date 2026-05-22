"""TASK-S02 — Signal dataclass + SignalEngine framework (V2 §2).

Signals carry only the *trigger* description: which stock, what direction,
how confident, why, and the feature snapshot at trigger time. Sizing and
risk management live in ``src/portfolio/{position_sizer,risk_manager}.py``
(later phases).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, List

import pandas as pd

__all__ = ["Signal", "SignalEngine", "VALID_ACTIONS", "VALID_SIDES"]


VALID_ACTIONS = ("entry", "exit", "hold", "avoid")
VALID_SIDES = ("long", "short", "none")


@dataclass
class Signal:
    timestamp: datetime
    stock_id: str
    action: str
    side: str
    score: float
    confidence: float
    reasons: List[str] = field(default_factory=list)
    invalidations: List[str] = field(default_factory=list)
    features_snapshot: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.action not in VALID_ACTIONS:
            raise ValueError(f"action must be one of {VALID_ACTIONS}, got {self.action!r}")
        if self.side not in VALID_SIDES:
            raise ValueError(f"side must be one of {VALID_SIDES}, got {self.side!r}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Signal":
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            stock_id=data["stock_id"],
            action=data["action"],
            side=data["side"],
            score=float(data["score"]),
            confidence=float(data["confidence"]),
            reasons=list(data.get("reasons", [])),
            invalidations=list(data.get("invalidations", [])),
            features_snapshot=dict(data.get("features_snapshot", {})),
        )


class SignalEngine(ABC):
    """Abstract signal generator.

    Subclasses implement ``generate`` to produce a list of ``Signal`` for a
    feature DataFrame indexed by ``(date, stock_id)``.
    """

    @abstractmethod
    def generate(self, feature_df: pd.DataFrame) -> List[Signal]:
        """Return signals for the supplied feature frame."""
