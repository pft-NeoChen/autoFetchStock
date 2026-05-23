"""V1 §6.1 Plan D — per-stock regime gate.

Plan D widening to ``{BULL, RANGE}`` didn't help because 0050 was BEAR
all 3 OOS windows (no RANGE). Real fix: each stock's own MA200 decides
its regime, so small-cap winners (decoupled from 0050) trade on their
own merits.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from scripts.run_backtest_v1 import make_per_stock_regime_gated_entry_factory


pytestmark = pytest.mark.unit


def _frame(closes: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(closes), freq="B")
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes,
         "volume": [1_000] * len(closes)},
        index=idx,
    )


def _inner_recorder(calls: dict[str, list[date]]):
    def factory(stock_id: str, frame: pd.DataFrame):
        def decider(today, row, has_position):
            calls.setdefault(stock_id, []).append(today)
            return None
        return decider
    return factory


def test_per_stock_gate_uses_each_stocks_own_ohlc():
    # Bull stock: strictly rising → close>MA200 AND MA50>MA200 → BULL.
    bull = _frame([100.0 + i * 0.5 for i in range(260)])
    # Bear stock: strictly falling → BEAR.
    bear = _frame([200.0 - i * 0.5 for i in range(260)])

    calls: dict[str, list[date]] = {}
    gated = make_per_stock_regime_gated_entry_factory(
        inner_factory=_inner_recorder(calls),
        feature_frames={"BULL_STK": bull, "BEAR_STK": bear},
    )

    ref = bull.index[250].date()

    bull_decider = gated("BULL_STK", bull)
    bull_decider(ref, None, False)

    bear_decider = gated("BEAR_STK", bear)
    bear_decider(ref, None, False)

    assert calls.get("BULL_STK") == [ref]
    assert "BEAR_STK" not in calls  # BEAR → gate blocked


def test_per_stock_gate_missing_frame_blocks_safely():
    calls: dict[str, list[date]] = {}
    bull = _frame([100.0 + i * 0.5 for i in range(260)])
    gated = make_per_stock_regime_gated_entry_factory(
        inner_factory=_inner_recorder(calls),
        feature_frames={"BULL_STK": bull},
    )
    # Unknown stock id → no frame → gate returns None without crashing.
    decider = gated("UNKNOWN", pd.DataFrame())
    decider(bull.index[250].date(), None, False)
    assert "UNKNOWN" not in calls
