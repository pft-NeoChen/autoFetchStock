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
    """Return ``(passes, reason)`` for an already-classified regime label."""
    if regime is None:
        if pass_on_unknown:
            return True, "regime_unknown_pass"
        return False, "regime_unknown_blocked"

    if regime in allowed:
        return True, f"regime_{regime.value}_allowed"
    return False, f"regime_{regime.value}_blocked"


def evaluate_regime_for_signal(
    market_ohlc: pd.DataFrame,
    ref_date: date,
    config: Optional[RegimeGateConfig] = None,
) -> Tuple[bool, str]:
    """Classify ``ref_date`` then apply :func:`gate_by_regime`."""
    cfg = config or RegimeGateConfig()
    regime = classify_regime(
        market_ohlc,
        ref_date,
        fast_window=cfg.fast_window,
        slow_window=cfg.slow_window,
    )
    return gate_by_regime(
        regime, allowed=cfg.allowed, pass_on_unknown=cfg.pass_on_unknown
    )
