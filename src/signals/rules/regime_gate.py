"""TASK-S05 — Regime gating for SignalEngine (V2 §2, §6.1).

Lightweight wrapper over :mod:`src.backtest.regime_classifier`. Allows the
entry pipeline to block long signals during BEAR / RANGE regimes (and
optionally during insufficient-history periods).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import FrozenSet, Optional, Tuple

import pandas as pd

from src.backtest.regime_classifier import (
    DEFAULT_FAST_WINDOW,
    DEFAULT_SLOW_WINDOW,
    Regime,
    classify_regime,
)

__all__ = [
    "DEFAULT_ALLOWED_REGIMES",
    "RegimeGateConfig",
    "evaluate_regime_for_signal",
    "gate_by_regime",
]


DEFAULT_ALLOWED_REGIMES: FrozenSet[Regime] = frozenset({Regime.BULL})


@dataclass(frozen=True)
class RegimeGateConfig:
    allowed: FrozenSet[Regime] = DEFAULT_ALLOWED_REGIMES
    pass_on_unknown: bool = False
    fast_window: int = DEFAULT_FAST_WINDOW
    slow_window: int = DEFAULT_SLOW_WINDOW


def gate_by_regime(
    regime: Optional[Regime],
    *,
    allowed: FrozenSet[Regime] = DEFAULT_ALLOWED_REGIMES,
    pass_on_unknown: bool = False,
) -> Tuple[bool, str]:
    """Return ``(passes, reason)`` for an already-classified regime label.

    ``None`` (insufficient data) is blocked unless ``pass_on_unknown`` is True.
    Reason text always names the current regime so journal entries are
    debuggable without joining a separate table.
    """
    raise NotImplementedError("RED stub")


def evaluate_regime_for_signal(
    market_ohlc: pd.DataFrame,
    ref_date: date,
    config: Optional[RegimeGateConfig] = None,
) -> Tuple[bool, str]:
    """Classify ``ref_date`` then apply :func:`gate_by_regime`."""
    raise NotImplementedError("RED stub")
