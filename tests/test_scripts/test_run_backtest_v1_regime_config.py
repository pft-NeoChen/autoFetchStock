"""V1 §6.1 Plan D — widened regime gate config.

First Plan A run with default RegimeGateConfig (allowed={BULL}) produced
n_trades=1 because 0050 close<MA200 throughout OOS → all windows BEAR
→ gate blocked everything. Widening to {BULL, RANGE} lets the strategy
operate in sideways markets while still avoiding clear downtrends.

This test pins:
  1. ``make_regime_gated_entry_factory`` accepts a ``RegimeGateConfig``
  2. Custom allowed set is honoured at decision time
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from scripts.run_backtest_v1 import make_regime_gated_entry_factory
from src.backtest.regime_classifier import Regime
from src.signals.rules.regime_gate import RegimeGateConfig


pytestmark = pytest.mark.unit


def _bear_market(n: int = 260) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    # Strictly declining close → BEAR per MA-based classifier.
    closes = [200.0 - i * 0.5 for i in range(n)]
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes,
         "volume": [1_000] * n},
        index=idx,
    )


def _flat_market(n: int = 260) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    closes = [100.0] * n
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes,
         "volume": [1_000] * n},
        index=idx,
    )


def _inner_factory_recording(calls: list[date]):
    def factory(stock_id: str, frame: pd.DataFrame):
        def decider(today, row, has_position):
            calls.append(today)
            return None
        return decider
    return factory


def test_gated_factory_default_blocks_in_bear_market():
    """Default config (allowed={BULL}) still blocks BEAR — regression check."""
    calls: list[date] = []
    market = _bear_market()
    gated = make_regime_gated_entry_factory(
        inner_factory=_inner_factory_recording(calls),
        market_ohlc=market,
    )
    decider = gated("2330", pd.DataFrame())
    decider(market.index[250].date(), None, False)
    assert calls == []


def test_gated_factory_widened_config_allows_range_regime():
    calls: list[date] = []
    market = _flat_market()
    cfg = RegimeGateConfig(allowed=frozenset({Regime.BULL, Regime.RANGE}))
    gated = make_regime_gated_entry_factory(
        inner_factory=_inner_factory_recording(calls),
        market_ohlc=market,
        config=cfg,
    )
    decider = gated("2330", pd.DataFrame())
    ref = market.index[250].date()
    decider(ref, None, False)
    # Flat market = RANGE; widened allowed set lets inner fire.
    assert calls == [ref]


def test_gated_factory_widened_still_blocks_bear():
    calls: list[date] = []
    market = _bear_market()
    cfg = RegimeGateConfig(allowed=frozenset({Regime.BULL, Regime.RANGE}))
    gated = make_regime_gated_entry_factory(
        inner_factory=_inner_factory_recording(calls),
        market_ohlc=market,
        config=cfg,
    )
    decider = gated("2330", pd.DataFrame())
    decider(market.index[250].date(), None, False)
    # BEAR still blocked.
    assert calls == []
