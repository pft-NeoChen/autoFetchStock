"""V1 verdict-fix — equal_weight benchmark must match OOS span (V2 §3.5).

The first V1 §6.1 run produced equal_weight_total_return ≈ 300% because
it spanned the full 2-year feature range, while the strategy only trades
during ~9 months of OOS windows. The comparison was apples-to-oranges.

Fix: ``equal_weight_total_return`` accepts an optional ``oos_dates``
parameter and uses only those dates. Test pins behaviour.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.run_backtest_v1 import equal_weight_total_return


pytestmark = pytest.mark.unit


def _frame(closes: list[float], start: str) -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(closes), freq="B")
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1_000] * len(closes),
        },
        index=idx,
    )


def test_equal_weight_default_uses_full_range():
    f = _frame([100, 110, 121, 133, 146], "2024-01-01")
    # full span → ~46%
    ret = equal_weight_total_return({"A": f})
    assert ret == pytest.approx(0.46, abs=0.01)


def test_equal_weight_restricted_to_oos_dates_only():
    # Stock 1 surges 4x over first month, flat thereafter.
    closes = [100, 200, 300, 400, 500] + [500] * 95
    f = _frame(closes, "2024-01-01")

    oos_start = f.index[10]
    oos_end = f.index[20]

    full = equal_weight_total_return({"A": f})
    oos = equal_weight_total_return({"A": f}, oos_dates=(oos_start, oos_end))

    assert full == pytest.approx(4.0, abs=0.01)
    # OOS slice is in flat region → ~0
    assert oos == pytest.approx(0.0, abs=0.01)


def test_equal_weight_oos_dates_empty_slice_returns_zero():
    f = _frame([100, 110, 121], "2024-01-01")
    # OOS range outside data → empty slice → 0
    after = pd.Timestamp("2030-01-01")
    ret = equal_weight_total_return(
        {"A": f}, oos_dates=(after, after + pd.Timedelta(days=30))
    )
    assert ret == 0.0
