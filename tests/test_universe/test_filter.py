"""TASK-U01 RED tests: src/universe/filter.py — daily universe filter.

V2 §0.2 rules:
- 20d average turnover ≥ 50,000,000
- listing days ≥ 60
- close price ≥ 5
- exclude F-shares, ETN, warrants, warning, disposition, full-delivery stocks
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from src.universe.filter import StockMeta, filter_universe


pytestmark = pytest.mark.unit


# --------------------------------------------------------------- fixtures


def _daily_df(
    start: date,
    n_days: int,
    close: float = 100.0,
    turnover: float = 100_000_000.0,
) -> pd.DataFrame:
    rows = []
    for i in range(n_days):
        d = start + timedelta(days=i)
        rows.append({"date": d, "close": close, "turnover": turnover})
    return pd.DataFrame(rows).set_index("date")


def _meta(
    stock_id: str = "2330",
    name: str = "台積電",
    listing_date: date = date(2020, 1, 1),
    is_etn: bool = False,
    is_warning: bool = False,
    is_disposition: bool = False,
    is_full_delivery: bool = False,
    is_warrant: bool = False,
) -> StockMeta:
    return StockMeta(
        stock_id=stock_id,
        name=name,
        listing_date=listing_date,
        is_etn=is_etn,
        is_warning=is_warning,
        is_disposition=is_disposition,
        is_full_delivery=is_full_delivery,
        is_warrant=is_warrant,
    )


# --------------------------------------------------------------- tests


def test_liquidity_below_threshold_excluded() -> None:
    """20d avg turnover < 50,000,000 → excluded."""
    target = date(2024, 6, 1)
    daily = {"2330": _daily_df(target - timedelta(days=60), 61, turnover=10_000_000)}
    metas = {"2330": _meta()}

    out = filter_universe(target, ["2330"], daily, metas)
    assert out == []


def test_liquidity_at_threshold_included() -> None:
    """20d avg turnover == exactly 50,000,000 → included (≥ inclusive)."""
    target = date(2024, 6, 1)
    daily = {"2330": _daily_df(target - timedelta(days=60), 61, turnover=50_000_000)}
    metas = {"2330": _meta()}

    out = filter_universe(target, ["2330"], daily, metas)
    assert out == ["2330"]


def test_listing_days_below_60_excluded() -> None:
    target = date(2024, 6, 1)
    daily = {"2330": _daily_df(target - timedelta(days=30), 31)}
    metas = {"2330": _meta(listing_date=target - timedelta(days=30))}

    out = filter_universe(target, ["2330"], daily, metas)
    assert out == []


def test_price_below_5_excluded() -> None:
    target = date(2024, 6, 1)
    daily = {"2330": _daily_df(target - timedelta(days=60), 61, close=4.5)}
    metas = {"2330": _meta()}

    out = filter_universe(target, ["2330"], daily, metas)
    assert out == []


def test_f_stock_excluded_by_name() -> None:
    """F-股 detected via name containing 'F-' or '-KY' suffix (台股慣例)."""
    target = date(2024, 6, 1)
    daily = {
        "F1234": _daily_df(target - timedelta(days=60), 61),
        "1234": _daily_df(target - timedelta(days=60), 61),
    }
    metas = {
        "F1234": _meta(stock_id="F1234", name="F-某外國"),
        "1234": _meta(stock_id="1234", name="正常股"),
    }

    out = filter_universe(target, ["F1234", "1234"], daily, metas)
    assert "F1234" not in out
    assert "1234" in out


def test_etn_excluded() -> None:
    target = date(2024, 6, 1)
    daily = {"020001": _daily_df(target - timedelta(days=60), 61)}
    metas = {"020001": _meta(stock_id="020001", name="某ETN", is_etn=True)}

    out = filter_universe(target, ["020001"], daily, metas)
    assert out == []


def test_warning_stock_excluded() -> None:
    target = date(2024, 6, 1)
    daily = {"2330": _daily_df(target - timedelta(days=60), 61)}
    metas = {"2330": _meta(is_warning=True)}

    out = filter_universe(target, ["2330"], daily, metas)
    assert out == []


def test_disposition_stock_excluded() -> None:
    target = date(2024, 6, 1)
    daily = {"2330": _daily_df(target - timedelta(days=60), 61)}
    metas = {"2330": _meta(is_disposition=True)}

    out = filter_universe(target, ["2330"], daily, metas)
    assert out == []


def test_full_delivery_stock_excluded() -> None:
    target = date(2024, 6, 1)
    daily = {"2330": _daily_df(target - timedelta(days=60), 61)}
    metas = {"2330": _meta(is_full_delivery=True)}

    out = filter_universe(target, ["2330"], daily, metas)
    assert out == []


def test_empty_input_returns_empty_list() -> None:
    out = filter_universe(date(2024, 6, 1), [], {}, {})
    assert out == []


def test_pure_function_idempotent() -> None:
    """Calling twice with same inputs must produce identical result."""
    target = date(2024, 6, 1)
    daily = {"2330": _daily_df(target - timedelta(days=60), 61)}
    metas = {"2330": _meta()}

    out1 = filter_universe(target, ["2330"], daily, metas)
    out2 = filter_universe(target, ["2330"], daily, metas)
    assert out1 == out2 == ["2330"]


def test_ignores_data_after_target_date() -> None:
    """Point-in-time: data with date > target must NOT influence the filter.

    Stock has only 40 bars before target but 30 bars after. Listing days = 40 < 60 → excluded.
    """
    target = date(2024, 6, 1)
    # 40 bars before target, 30 bars after (total 70, but only 40 valid for the filter)
    daily = {"2330": _daily_df(target - timedelta(days=39), 70)}
    metas = {"2330": _meta(listing_date=target - timedelta(days=39))}

    out = filter_universe(target, ["2330"], daily, metas)
    assert out == []
