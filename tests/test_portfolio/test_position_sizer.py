"""TASK-R02 — PositionSizer."""

from __future__ import annotations

import pandas as pd
import pytest

from src.portfolio.position_sizer import (
    PositionSizer,
    PositionSizerConfig,
    PositionSizingError,
)


@pytest.mark.unit
def test_vol_target_sizes_from_annualized_20d_volatility() -> None:
    sizer = PositionSizer(
        PositionSizerConfig(
            target_annual_vol=0.10,
            trading_days=252,
            lot_size=1,
            max_notional_pct=1.0,
        )
    )

    decision = sizer.vol_target(
        account_equity=1_000_000,
        price=100.0,
        daily_vol=0.02,
    )

    expected_notional = 1_000_000 * (0.10 / (0.02 * (252 ** 0.5)))
    assert decision.allowed is True
    assert decision.method == "vol_target"
    assert decision.target_shares == int(expected_notional // 100.0)
    assert decision.target_notional == pytest.approx(decision.target_shares * 100.0)


@pytest.mark.unit
def test_vol_target_applies_max_notional_cap() -> None:
    sizer = PositionSizer(PositionSizerConfig(lot_size=1, max_notional_pct=0.15))

    decision = sizer.vol_target(
        account_equity=1_000_000,
        price=100.0,
        daily_vol=0.005,
    )

    assert decision.target_notional <= 150_000
    assert "max_notional_cap" in decision.reasons


@pytest.mark.unit
def test_vol_target_rounds_down_to_lot_size() -> None:
    sizer = PositionSizer(PositionSizerConfig(lot_size=1000, max_notional_pct=1.0))

    decision = sizer.vol_target(
        account_equity=1_000_000,
        price=80.0,
        daily_vol=0.02,
    )

    assert decision.target_shares % 1000 == 0
    assert decision.target_shares == 3000


@pytest.mark.unit
def test_atr_based_uses_account_risk_budget_over_k_atr() -> None:
    sizer = PositionSizer(
        PositionSizerConfig(
            risk_budget_pct=0.01,
            atr_multiple=2.0,
            lot_size=1,
            max_notional_pct=1.0,
        )
    )

    decision = sizer.atr_based(
        account_equity=1_000_000,
        price=100.0,
        atr=5.0,
    )

    assert decision.allowed is True
    assert decision.method == "atr_based"
    assert decision.target_shares == 1000
    assert decision.risk_amount == pytest.approx(10_000.0)


@pytest.mark.unit
def test_atr_based_applies_risk_manager_multiplier() -> None:
    sizer = PositionSizer(
        PositionSizerConfig(
            risk_budget_pct=0.01,
            atr_multiple=2.0,
            lot_size=1,
            max_notional_pct=1.0,
        )
    )

    decision = sizer.atr_based(
        account_equity=1_000_000,
        price=100.0,
        atr=5.0,
        risk_multiplier=0.5,
    )

    assert decision.target_shares == 500
    assert "risk_multiplier" in decision.reasons


@pytest.mark.unit
def test_returns_blocked_decision_when_rounded_size_is_zero() -> None:
    sizer = PositionSizer(PositionSizerConfig(lot_size=1000, max_notional_pct=0.01))

    decision = sizer.vol_target(
        account_equity=100_000,
        price=500.0,
        daily_vol=0.05,
    )

    assert decision.allowed is False
    assert decision.target_shares == 0
    assert "below_lot_size" in decision.reasons


@pytest.mark.unit
def test_invalid_inputs_raise() -> None:
    sizer = PositionSizer()

    with pytest.raises(PositionSizingError):
        sizer.vol_target(account_equity=1_000_000, price=100.0, daily_vol=0.0)

    with pytest.raises(PositionSizingError):
        sizer.atr_based(account_equity=1_000_000, price=100.0, atr=0.0)


@pytest.mark.unit
def test_size_from_features_supports_vol_target_and_atr_only() -> None:
    sizer = PositionSizer(PositionSizerConfig(lot_size=1, max_notional_pct=1.0))
    row = pd.Series({"close": 100.0, "vol_20": 0.02, "atr_14": 5.0})

    vol_decision = sizer.size_from_features(
        method="vol_target",
        account_equity=1_000_000,
        features=row,
    )
    atr_decision = sizer.size_from_features(
        method="atr_based",
        account_equity=1_000_000,
        features=row,
    )

    assert vol_decision.method == "vol_target"
    assert atr_decision.method == "atr_based"
    with pytest.raises(PositionSizingError):
        sizer.size_from_features(method="kelly", account_equity=1_000_000, features=row)
