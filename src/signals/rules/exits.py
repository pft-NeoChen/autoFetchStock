"""TASK-S04 — Exit rules (V2 §2 出場條件).

Pure evaluator over an ``ExitConditions`` snapshot. Any condition that fires
adds a short-code reason to the returned list; the caller decides which
reason to record in the trade journal when multiple fire simultaneously.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

__all__ = ["ExitConditions", "evaluate_exit"]


_SEVERITY_ORDER = {"normal": 0, "low": 1, "mid": 2, "high": 3, "extreme": 4}


@dataclass(frozen=True)
class ExitConditions:
    entry_price: float
    current_close: float
    current_open: float
    ma_10: float
    atr_14: float
    spike_severity: str
    candle_body: float
    highest_since_entry: float
    days_held: int
    trend_active: bool


def _severity_at_least(sev: str, level: str) -> bool:
    return _SEVERITY_ORDER.get(sev.lower(), 0) >= _SEVERITY_ORDER[level]


def evaluate_exit(c: ExitConditions) -> Tuple[bool, List[str]]:
    reasons: list[str] = []

    # 1. 固定停損：close < entry − 1.5 × ATR
    stop_threshold = c.entry_price - 1.5 * c.atr_14
    if c.current_close < stop_threshold:
        reasons.append("stop_atr")

    # 2. 收盤跌破 MA10
    if c.current_close < c.ma_10:
        reasons.append("break_below_ma10")

    # 3. 爆量長黑：spike ≥ HIGH 且收黑 (close < open) 且 body > ATR
    if (
        _severity_at_least(c.spike_severity, "high")
        and c.current_close < c.current_open
        and c.candle_body > c.atr_14
    ):
        reasons.append("bearish_volume_spike")

    # 4. 移動停利：highest_since_entry − close > 1.0 × ATR
    if (c.highest_since_entry - c.current_close) > c.atr_14:
        reasons.append("trailing_atr")

    # 5. 時間停損：持有 > 10 日且趨勢失效
    if c.days_held > 10 and not c.trend_active:
        reasons.append("time_stop_10d")

    return (len(reasons) > 0, reasons)
