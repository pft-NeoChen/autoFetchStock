"""TASK-F01 — Corporate actions and backward-adjusted OHLC (V2 §0.4)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

OHLC_COLUMNS = ("open", "high", "low", "close")
ADJUSTED_COLUMNS = {
    "open": "adj_open",
    "high": "adj_high",
    "low": "adj_low",
    "close": "adj_close",
}

__all__ = [
    "ADJUSTED_COLUMNS",
    "OHLC_COLUMNS",
    "CorporateActionEvent",
    "apply_backward_adjustment",
]


@dataclass(frozen=True)
class CorporateActionEvent:
    """A corporate action on its ex-date.

    ``adjustment_factor`` is the factor applied to rows before ``ex_date``.
    Keep it ``None`` when source data is incomplete; the event will still be
    flagged but prices will not be adjusted.
    """

    ex_date: date
    event_type: str
    adjustment_factor: float | None = None

    @classmethod
    def from_factor(
        cls,
        ex_date: date,
        adjustment_factor: float,
        event_type: str,
    ) -> "CorporateActionEvent":
        _validate_positive("adjustment_factor", adjustment_factor)
        return cls(
            ex_date=ex_date,
            event_type=event_type,
            adjustment_factor=float(adjustment_factor),
        )

    @classmethod
    def cash_dividend(
        cls,
        *,
        ex_date: date,
        cash_dividend: float,
        previous_close: float,
    ) -> "CorporateActionEvent":
        _validate_positive("previous_close", previous_close)
        factor = (previous_close - cash_dividend) / previous_close
        _validate_positive("cash dividend adjustment factor", factor)
        return cls.from_factor(ex_date, factor, "cash_dividend")

    @classmethod
    def stock_split(
        cls,
        *,
        ex_date: date,
        split_ratio: float,
    ) -> "CorporateActionEvent":
        _validate_positive("split_ratio", split_ratio)
        return cls.from_factor(ex_date, 1.0 / split_ratio, "stock_split")

    @classmethod
    def cash_capital_reduction(
        cls,
        *,
        ex_date: date,
        cash_refund: float,
        capital_reduction_ratio: float,
        previous_close: float,
    ) -> "CorporateActionEvent":
        _validate_positive("previous_close", previous_close)
        if not 0 <= capital_reduction_ratio < 1:
            raise ValueError("capital_reduction_ratio must be >= 0 and < 1")
        reference_price = (previous_close - cash_refund) / (
            1.0 - capital_reduction_ratio
        )
        factor = reference_price / previous_close
        _validate_positive("capital reduction adjustment factor", factor)
        return cls.from_factor(ex_date, factor, "cash_capital_reduction")


def _validate_positive(name: str, value: float) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _coerce_event(raw_event: CorporateActionEvent | dict[str, Any]) -> CorporateActionEvent:
    if isinstance(raw_event, CorporateActionEvent):
        return raw_event
    return CorporateActionEvent(
        ex_date=pd.Timestamp(raw_event["ex_date"]).date(),
        event_type=str(raw_event.get("event_type", "unknown")),
        adjustment_factor=raw_event.get("adjustment_factor"),
    )


def _index_dates(index: pd.Index) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(index)).normalize()


def _ensure_ohlc_columns(df: pd.DataFrame) -> None:
    missing = [col for col in OHLC_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"ohlc_df missing columns: {missing}")


def apply_backward_adjustment(
    ohlc_df: pd.DataFrame,
    events: Iterable[CorporateActionEvent | dict[str, Any]],
) -> pd.DataFrame:
    """Return a copy with adjusted OHLC columns and corporate action flags."""
    _ensure_ohlc_columns(ohlc_df)

    out = ohlc_df.copy()
    for raw_col, adj_col in ADJUSTED_COLUMNS.items():
        out[adj_col] = out[raw_col].astype(float)
    out["is_corporate_action_day"] = False
    out["corporate_action_factor"] = 1.0

    index_dates = _index_dates(out.index)
    normalized_events = sorted(
        (_coerce_event(event) for event in events),
        key=lambda event: event.ex_date,
    )

    for event in normalized_events:
        ex_timestamp = pd.Timestamp(event.ex_date).normalize()
        event_day_mask = index_dates == ex_timestamp
        if event_day_mask.any():
            out.loc[event_day_mask, "is_corporate_action_day"] = True

        if event.adjustment_factor is None:
            continue

        _validate_positive("adjustment_factor", event.adjustment_factor)
        prior_mask = index_dates < ex_timestamp
        if not prior_mask.any():
            continue

        for adj_col in ADJUSTED_COLUMNS.values():
            out.loc[prior_mask, adj_col] = (
                out.loc[prior_mask, adj_col] * event.adjustment_factor
            )
        out.loc[prior_mask, "corporate_action_factor"] = (
            out.loc[prior_mask, "corporate_action_factor"] * event.adjustment_factor
        )

    return out
