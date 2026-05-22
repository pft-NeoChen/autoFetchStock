"""TASK-S03 — Long-entry rule (V2 §2 第一版策略).

Pure evaluator over an ``EntryConditions`` snapshot. The actual orchestration
(building the snapshot from FeatureStore + market frame + risk state) lives
in the eventual ``LongEntryEngine`` subclass.

Returned ``invalidations`` are the conditions that should make the
caller close the position (used by TASK-S04 exit rules).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

__all__ = ["EntryConditions", "evaluate_long_entry"]


_SEVERITY_ORDER = {"normal": 0, "low": 1, "mid": 2, "high": 3, "extreme": 4}


@dataclass(frozen=True)
class EntryConditions:
    # Price action
    close: float
    open: float
    ma_5: float
    ma_20: float
    ma_60: float
    upper_shadow: float
    candle_body: float
    atr_14: float

    # Volume
    spike_severity: str  # "normal" | "low" | "mid" | "high" | "extreme"
    high_20d: float

    # Chip
    foreign_net_streak: int           # signed; +N = N 連續 net buy
    margin_balance_5d_change: float   # 融資 5 日變化

    # Market regime
    market_close: float
    market_ma_60: float

    # State / risk
    is_limit_up: bool
    news_severity: float           # -10 ~ +10；大負值代表重大利空
    breached_daily_loss: bool


def _severity_at_least(sev: str, level: str) -> bool:
    return _SEVERITY_ORDER.get(sev.lower(), 0) >= _SEVERITY_ORDER[level]


def evaluate_long_entry(c: EntryConditions) -> Tuple[bool, List[str], List[str]]:
    """Return (passes, reasons, invalidations).

    A failed avoid-check or a missing entry-condition returns ``(False, [], [])``;
    we keep reasons empty on failure to avoid logging misleading partial logic
    in the journal. ``invalidations`` ride with successful signals only.
    """
    reasons: list[str] = []

    # ── Avoid-list checks (early-exit) ──────────────────────────────────
    if c.is_limit_up:
        return False, [], []
    if c.breached_daily_loss:
        return False, [], []
    if c.news_severity <= -5.0:
        return False, [], []
    if c.candle_body > 0 and c.upper_shadow > c.candle_body * 1.5:
        return False, [], []

    # ── Entry conditions ────────────────────────────────────────────────
    if not (c.close > c.ma_20 and c.close > c.ma_60):
        return False, [], []
    reasons.append("trend_ma20_ma60")

    if not _severity_at_least(c.spike_severity, "mid"):
        return False, [], []
    reasons.append(f"spike_{c.spike_severity}")

    red_candle = c.close < c.open
    breakout_20d = c.close > c.high_20d
    if red_candle and not breakout_20d:
        return False, [], []
    reasons.append("breakout_20d" if breakout_20d else "green_spike")

    chip_ok = c.foreign_net_streak >= 3 or c.margin_balance_5d_change < 0
    if not chip_ok:
        return False, [], []
    reasons.append("chip_supportive")

    if c.market_close <= c.market_ma_60:
        return False, [], []
    reasons.append("market_above_ma60")

    invalidations = [
        "break_below_ma20",
        "break_below_ma10",
        "stop_atr",  # close < entry − 1.5 × ATR
        "trailing_atr",
        "time_stop_10d",
    ]
    return True, reasons, invalidations
