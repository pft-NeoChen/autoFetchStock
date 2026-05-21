"""TASK-F01 RED tests: backward-adjusted OHLC for corporate actions."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.features.corporate_actions import (
    CorporateActionEvent,
    apply_backward_adjustment,
)


pytestmark = pytest.mark.unit


def _ohlc_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100.0, 102.0, 104.0, 52.0, 53.0],
            "high": [101.0, 103.0, 105.0, 53.0, 54.0],
            "low": [99.0, 101.0, 103.0, 51.0, 52.0],
            "close": [100.0, 102.0, 104.0, 52.0, 53.0],
        },
        index=pd.to_datetime(
            ["2026-05-18", "2026-05-19", "2026-05-20", "2026-05-21", "2026-05-22"]
        ),
    )


def test_no_events_preserves_raw_prices_and_flags_false() -> None:
    raw = _ohlc_df()

    out = apply_backward_adjustment(raw, [])

    pd.testing.assert_frame_equal(out[["open", "high", "low", "close"]], raw)
    pd.testing.assert_frame_equal(
        out[["adj_open", "adj_high", "adj_low", "adj_close"]],
        raw.rename(
            columns={
                "open": "adj_open",
                "high": "adj_high",
                "low": "adj_low",
                "close": "adj_close",
            }
        ),
    )
    assert out["is_corporate_action_day"].tolist() == [False, False, False, False, False]
    assert out["corporate_action_factor"].tolist() == [1.0, 1.0, 1.0, 1.0, 1.0]


def test_cash_dividend_backward_adjusts_prior_rows_only() -> None:
    event = CorporateActionEvent.cash_dividend(
        ex_date=date(2026, 5, 21),
        cash_dividend=10.0,
        previous_close=100.0,
    )

    out = apply_backward_adjustment(_ohlc_df(), [event])

    assert out.loc[pd.Timestamp("2026-05-20"), "adj_close"] == pytest.approx(93.6)
    assert out.loc[pd.Timestamp("2026-05-21"), "adj_close"] == pytest.approx(52.0)
    assert out.loc[pd.Timestamp("2026-05-21"), "is_corporate_action_day"] is True


def test_stock_split_one_to_two_halves_prior_ohlc() -> None:
    event = CorporateActionEvent.stock_split(
        ex_date=date(2026, 5, 21),
        split_ratio=2.0,
    )

    out = apply_backward_adjustment(_ohlc_df(), [event])

    assert out.loc[pd.Timestamp("2026-05-20"), "adj_open"] == pytest.approx(52.0)
    assert out.loc[pd.Timestamp("2026-05-20"), "adj_high"] == pytest.approx(52.5)
    assert out.loc[pd.Timestamp("2026-05-20"), "adj_low"] == pytest.approx(51.5)
    assert out.loc[pd.Timestamp("2026-05-20"), "adj_close"] == pytest.approx(52.0)


def test_cash_capital_reduction_adjusts_by_theoretical_reference_price() -> None:
    event = CorporateActionEvent.cash_capital_reduction(
        ex_date=date(2026, 5, 21),
        cash_refund=10.0,
        capital_reduction_ratio=0.2,
        previous_close=100.0,
    )

    out = apply_backward_adjustment(_ohlc_df(), [event])

    assert event.adjustment_factor == pytest.approx(1.125)
    assert out.loc[pd.Timestamp("2026-05-20"), "adj_close"] == pytest.approx(117.0)
    assert out.loc[pd.Timestamp("2026-05-21"), "adj_close"] == pytest.approx(52.0)


def test_multiple_events_compound_in_chronological_order() -> None:
    events = [
        CorporateActionEvent.from_factor(date(2026, 5, 22), 0.8, "cash_dividend"),
        CorporateActionEvent.from_factor(date(2026, 5, 20), 0.5, "stock_split"),
    ]

    out = apply_backward_adjustment(_ohlc_df(), events)

    assert out.loc[pd.Timestamp("2026-05-19"), "corporate_action_factor"] == pytest.approx(
        0.4
    )
    assert out.loc[pd.Timestamp("2026-05-20"), "corporate_action_factor"] == pytest.approx(
        0.8
    )
    assert out.loc[pd.Timestamp("2026-05-22"), "corporate_action_factor"] == pytest.approx(
        1.0
    )


def test_event_with_missing_adjustment_data_only_sets_event_flag() -> None:
    event = CorporateActionEvent(
        ex_date=date(2026, 5, 21),
        event_type="major_capital_change",
        adjustment_factor=None,
    )

    out = apply_backward_adjustment(_ohlc_df(), [event])

    pd.testing.assert_series_equal(out["adj_close"], out["close"], check_names=False)
    assert out.loc[pd.Timestamp("2026-05-21"), "is_corporate_action_day"] is True
    assert out["corporate_action_factor"].tolist() == [1.0, 1.0, 1.0, 1.0, 1.0]
