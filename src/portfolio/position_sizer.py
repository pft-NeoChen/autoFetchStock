"""TASK-R02 — Position sizing rules (V2 §4.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from typing import Any

__all__ = [
    "PositionSizeDecision",
    "PositionSizer",
    "PositionSizerConfig",
    "PositionSizingError",
]


class PositionSizingError(ValueError):
    """Raised when sizing inputs or method names are invalid."""


@dataclass(frozen=True)
class PositionSizerConfig:
    target_annual_vol: float = 0.10
    trading_days: int = 252
    risk_budget_pct: float = 0.01
    atr_multiple: float = 2.0
    max_notional_pct: float = 0.15
    lot_size: int = 1000

    def __post_init__(self) -> None:
        _require_positive("target_annual_vol", self.target_annual_vol)
        _require_positive("trading_days", self.trading_days)
        _require_positive("risk_budget_pct", self.risk_budget_pct)
        _require_positive("atr_multiple", self.atr_multiple)
        _require_positive("max_notional_pct", self.max_notional_pct)
        _require_positive("lot_size", self.lot_size)


@dataclass(frozen=True)
class PositionSizeDecision:
    method: str
    allowed: bool
    target_shares: int
    target_notional: float
    risk_amount: float = 0.0
    reasons: list[str] = field(default_factory=list)


class PositionSizer:
    def __init__(self, config: PositionSizerConfig | None = None) -> None:
        self.config = config or PositionSizerConfig()

    def vol_target(
        self,
        *,
        account_equity: float,
        price: float,
        daily_vol: float,
        risk_multiplier: float = 1.0,
    ) -> PositionSizeDecision:
        self._validate_account_and_price(account_equity, price)
        _require_positive("daily_vol", daily_vol, PositionSizingError)
        multiplier = _validate_multiplier(risk_multiplier)

        annualized_vol = daily_vol * sqrt(self.config.trading_days)
        raw_notional = account_equity * (self.config.target_annual_vol / annualized_vol)
        notional, reasons = self._apply_caps(
            raw_notional=raw_notional,
            account_equity=account_equity,
            risk_multiplier=multiplier,
        )
        shares = self._round_lot(notional / price)
        if shares <= 0:
            return PositionSizeDecision("vol_target", False, 0, 0.0, reasons=reasons + ["below_lot_size"])
        return PositionSizeDecision(
            method="vol_target",
            allowed=True,
            target_shares=shares,
            target_notional=shares * price,
            reasons=reasons,
        )

    def atr_based(
        self,
        *,
        account_equity: float,
        price: float,
        atr: float,
        risk_multiplier: float = 1.0,
    ) -> PositionSizeDecision:
        self._validate_account_and_price(account_equity, price)
        _require_positive("atr", atr, PositionSizingError)
        multiplier = _validate_multiplier(risk_multiplier)

        risk_budget = account_equity * self.config.risk_budget_pct * multiplier
        per_share_risk = self.config.atr_multiple * atr
        raw_shares = risk_budget / per_share_risk
        raw_notional = raw_shares * price
        notional, reasons = self._apply_caps(
            raw_notional=raw_notional,
            account_equity=account_equity,
            risk_multiplier=1.0,
        )
        if multiplier != 1.0:
            reasons.append("risk_multiplier")
        shares = self._round_lot(notional / price)
        if shares <= 0:
            return PositionSizeDecision("atr_based", False, 0, 0.0, reasons=reasons + ["below_lot_size"])
        return PositionSizeDecision(
            method="atr_based",
            allowed=True,
            target_shares=shares,
            target_notional=shares * price,
            risk_amount=shares * per_share_risk,
            reasons=reasons,
        )

    def size_from_features(
        self,
        *,
        method: str,
        account_equity: float,
        features: Any,
        price_column: str = "close",
        vol_column: str = "vol_20",
        atr_column: str = "atr_14",
        risk_multiplier: float = 1.0,
    ) -> PositionSizeDecision:
        price = float(features[price_column])
        if method == "vol_target":
            return self.vol_target(
                account_equity=account_equity,
                price=price,
                daily_vol=float(features[vol_column]),
                risk_multiplier=risk_multiplier,
            )
        if method == "atr_based":
            return self.atr_based(
                account_equity=account_equity,
                price=price,
                atr=float(features[atr_column]),
                risk_multiplier=risk_multiplier,
            )
        raise PositionSizingError(f"unsupported sizing method: {method}")

    def _apply_caps(
        self,
        *,
        raw_notional: float,
        account_equity: float,
        risk_multiplier: float,
    ) -> tuple[float, list[str]]:
        reasons: list[str] = []
        notional = raw_notional
        max_notional = account_equity * self.config.max_notional_pct
        if notional > max_notional:
            notional = max_notional
            reasons.append("max_notional_cap")
        if risk_multiplier != 1.0:
            notional *= risk_multiplier
            reasons.append("risk_multiplier")
        return notional, reasons

    def _round_lot(self, shares: float) -> int:
        lots = int(shares // self.config.lot_size)
        return lots * self.config.lot_size

    @staticmethod
    def _validate_account_and_price(account_equity: float, price: float) -> None:
        _require_positive("account_equity", account_equity, PositionSizingError)
        _require_positive("price", price, PositionSizingError)


def _validate_multiplier(value: float) -> float:
    if value < 0:
        raise PositionSizingError("risk_multiplier must be non-negative")
    return float(value)


def _require_positive(name: str, value: float, exc_type: type[Exception] = ValueError) -> None:
    if value <= 0:
        raise exc_type(f"{name} must be positive")
