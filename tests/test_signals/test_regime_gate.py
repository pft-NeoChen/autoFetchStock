"""TASK-S05 — Regime gating tests."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.backtest.regime_classifier import Regime
from src.signals.rules.regime_gate import (
    DEFAULT_ALLOWED_REGIMES,
    RegimeGateConfig,
    evaluate_regime_for_signal,
    gate_by_regime,
)


def _market_df(close_series: list[float], start: date = date(2024, 1, 1)) -> pd.DataFrame:
    idx = pd.date_range(start=start, periods=len(close_series), freq="B")
    return pd.DataFrame(
        {
            "open": close_series,
            "high": [c * 1.005 for c in close_series],
            "low": [c * 0.995 for c in close_series],
            "close": close_series,
            "volume": [1_000_000] * len(close_series),
        },
        index=idx,
    )


# ---- gate_by_regime ----

@pytest.mark.unit
def test_gate_bull_passes_by_default() -> None:
    ok, reason = gate_by_regime(Regime.BULL)
    assert ok is True
    assert "bull" in reason.lower()


@pytest.mark.unit
def test_gate_bear_blocked_by_default() -> None:
    ok, reason = gate_by_regime(Regime.BEAR)
    assert ok is False
    assert "bear" in reason.lower()


@pytest.mark.unit
def test_gate_range_allowed_by_default() -> None:
    # R2 amendment (2026-05-24): RANGE now in default allowed set.
    ok, reason = gate_by_regime(Regime.RANGE)
    assert ok is True
    assert "range" in reason.lower()


@pytest.mark.unit
def test_gate_range_blocked_when_explicitly_restricted_to_bull() -> None:
    ok, reason = gate_by_regime(Regime.RANGE, allowed=frozenset({Regime.BULL}))
    assert ok is False
    assert "range" in reason.lower()


@pytest.mark.unit
def test_gate_unknown_blocked_by_default() -> None:
    ok, reason = gate_by_regime(None)
    assert ok is False
    assert "unknown" in reason.lower() or "insufficient" in reason.lower()


@pytest.mark.unit
def test_gate_unknown_passes_when_configured() -> None:
    ok, _ = gate_by_regime(None, pass_on_unknown=True)
    assert ok is True


@pytest.mark.unit
def test_gate_custom_allowed_set_includes_range() -> None:
    allowed = frozenset({Regime.BULL, Regime.RANGE})
    assert gate_by_regime(Regime.RANGE, allowed=allowed)[0] is True
    assert gate_by_regime(Regime.BEAR, allowed=allowed)[0] is False
    assert gate_by_regime(Regime.BULL, allowed=allowed)[0] is True


@pytest.mark.unit
def test_default_allowed_is_bull_and_range() -> None:
    # R2 amendment (2026-05-24): widened from {BULL} → {BULL, RANGE}.
    # BULL strict definition (close>MA200 AND MA50>MA200) misses V-shaped
    # recoveries where close is still under MA200; RANGE keeps sideways
    # consolidations tradeable while BEAR (clear downtrend) stays blocked.
    assert DEFAULT_ALLOWED_REGIMES == frozenset({Regime.BULL, Regime.RANGE})


# ---- evaluate_regime_for_signal ----

@pytest.mark.unit
def test_evaluate_bull_market_passes() -> None:
    closes = [100 + i * 0.5 for i in range(250)]
    df = _market_df(closes)
    ok, reason = evaluate_regime_for_signal(df, df.index[-1].date())
    assert ok is True
    assert "bull" in reason.lower()


@pytest.mark.unit
def test_evaluate_bear_market_blocked() -> None:
    closes = [200 - i * 0.5 for i in range(250)]
    df = _market_df(closes)
    ok, reason = evaluate_regime_for_signal(df, df.index[-1].date())
    assert ok is False
    assert "bear" in reason.lower()


@pytest.mark.unit
def test_evaluate_insufficient_history_blocks() -> None:
    df = _market_df([100 + i for i in range(50)])  # < MA200
    ok, _ = evaluate_regime_for_signal(df, df.index[-1].date())
    assert ok is False


@pytest.mark.unit
def test_evaluate_uses_config_overrides() -> None:
    closes = [200 - i * 0.5 for i in range(250)]  # BEAR
    df = _market_df(closes)
    cfg = RegimeGateConfig(allowed=frozenset({Regime.BULL, Regime.BEAR}))
    ok, _ = evaluate_regime_for_signal(df, df.index[-1].date(), config=cfg)
    assert ok is True


@pytest.mark.unit
def test_evaluate_default_config_when_none_passed() -> None:
    # R2 amendment (2026-05-24): flat → RANGE → now PASSES by default.
    # BEAR still blocked (covered by test_evaluate_bear_market_blocked above).
    df = _market_df([100.0] * 250)
    ok, _ = evaluate_regime_for_signal(df, df.index[-1].date())
    assert ok is True
