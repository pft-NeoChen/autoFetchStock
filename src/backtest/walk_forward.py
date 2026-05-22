"""TASK-B05 — Walk-forward + embargo (V2 §3.4).

Generates rolling IS/OOS windows with a business-day embargo between IS and
OOS. Provides utilities to merge small OOS samples and flag low-confidence
windows.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from src.backtest.execution_model import next_business_day

__all__ = [
    "WalkForwardWindow",
    "classify_oos_confidence",
    "merge_small_windows",
    "walk_forward_windows",
]


@dataclass(frozen=True)
class WalkForwardWindow:
    is_start: date
    is_end: date
    oos_start: date
    oos_end: date
    trade_count: int = 0


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    # Clamp day to month length
    day = min(d.day, 28)
    return date(year, month, day)


def walk_forward_windows(
    *,
    start: date,
    end: date,
    is_months: int = 12,
    oos_months: int = 3,
    embargo_business_days: int = 15,
) -> list[WalkForwardWindow]:
    out: list[WalkForwardWindow] = []
    is_start = start
    while True:
        is_end = _add_months(is_start, is_months)
        oos_start = next_business_day(is_end, n=embargo_business_days)
        oos_end = _add_months(oos_start, oos_months)
        if oos_end > end:
            break
        out.append(
            WalkForwardWindow(
                is_start=is_start,
                is_end=is_end,
                oos_start=oos_start,
                oos_end=oos_end,
            )
        )
        is_start = _add_months(is_start, oos_months)
    return out


def merge_small_windows(
    windows: list[WalkForwardWindow],
    *,
    min_trades: int,
) -> list[WalkForwardWindow]:
    """Fold consecutive windows with too few trades into a single record.

    The accumulator carries forward the earliest ``oos_start`` and updates
    ``oos_end`` / ``trade_count`` until it satisfies the threshold (or we
    run out of windows — in which case the final accumulator is kept and
    will be flagged by ``classify_oos_confidence``).
    """
    out: list[WalkForwardWindow] = []
    acc: WalkForwardWindow | None = None
    for w in windows:
        if acc is None:
            acc = w
        else:
            acc = replace(
                acc,
                oos_end=w.oos_end,
                trade_count=acc.trade_count + w.trade_count,
            )
        if acc.trade_count >= min_trades:
            out.append(acc)
            acc = None
    if acc is not None:
        out.append(acc)
    return out


def classify_oos_confidence(window: WalkForwardWindow, *, min_trades: int) -> str:
    return "OK" if window.trade_count >= min_trades else "LOW_CONFIDENCE"
