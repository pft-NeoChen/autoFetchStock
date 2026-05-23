"""TASK-D03d — Market regime classifier (V2 §6.1 caveat #3).

Labels each trading day as BULL / BEAR / RANGE based on the market index's
position relative to long-term and intermediate moving averages. Window-
and walk-forward-level helpers aggregate day labels for the V2 §6.1
``regime_coverage`` decision check.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Iterable, Optional

import pandas as pd


__all__ = [
    "Regime",
    "RegimeCoverage",
    "classify_regime",
    "classify_window",
    "count_regime_coverage",
]

DEFAULT_FAST_WINDOW = 50
DEFAULT_SLOW_WINDOW = 200


class Regime(str, Enum):
    BULL = "bull"
    BEAR = "bear"
    RANGE = "range"


@dataclass(frozen=True)
class RegimeCoverage:
    bull: int = 0
    bear: int = 0
    range: int = 0


# ── Day-level ───────────────────────────────────────────────────────────────


def classify_regime(
    market_ohlc: pd.DataFrame,
    ref_date: date,
    *,
    fast_window: int = DEFAULT_FAST_WINDOW,
    slow_window: int = DEFAULT_SLOW_WINDOW,
) -> Optional[Regime]:
    """Label ``ref_date`` as BULL / BEAR / RANGE.

    Returns ``None`` when ``ref_date`` is absent from the index or the
    slow MA cannot be computed (insufficient history).
    """
    raise NotImplementedError("RED stub")


# ── Window-level ────────────────────────────────────────────────────────────


def classify_window(
    market_ohlc: pd.DataFrame,
    start: date,
    end: date,
    *,
    fast_window: int = DEFAULT_FAST_WINDOW,
    slow_window: int = DEFAULT_SLOW_WINDOW,
) -> Optional[Regime]:
    """Aggregate day labels in [start, end] (inclusive) → most-common label.

    Returns ``None`` when the window has no classifiable day.
    """
    raise NotImplementedError("RED stub")


def count_regime_coverage(
    windows: Iterable[tuple[date, date]],
    market_ohlc: pd.DataFrame,
    *,
    fast_window: int = DEFAULT_FAST_WINDOW,
    slow_window: int = DEFAULT_SLOW_WINDOW,
) -> RegimeCoverage:
    """Count how many input windows fall into each regime label.

    Windows that classify_window cannot label are skipped silently.
    """
    raise NotImplementedError("RED stub")
