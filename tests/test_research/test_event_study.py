"""TASK-S1-HELPER - event-study research helper."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from src.research.event_study import (
    EventStudyResult,
    compute_forward_returns,
    evaluate_event_study_gate,
    event_study,
)


def _ohlc_frame() -> pd.DataFrame:
    dates = pd.date_range("2025-01-02", periods=6, freq="B")
    idx = pd.MultiIndex.from_product([dates, ["2330", "2317"]], names=["date", "stock_id"])
    closes = {
        "2330": [100.0, 101.0, 103.0, 106.0, 110.0, 111.0],
        "2317": [50.0, 50.0, 49.0, 51.0, 52.0, 50.0],
    }
    rows: list[dict[str, float]] = []
    for date in dates:
        for stock_id in ["2330", "2317"]:
            close = closes[stock_id][dates.get_loc(date)]
            rows.append({"open": close - 1.0, "high": close + 1.0, "low": close - 2.0, "close": close})
    return pd.DataFrame(rows, index=idx)


def _trigger_mask(ohlc: pd.DataFrame, events: list[tuple[str, str]]) -> pd.Series:
    mask = pd.Series(False, index=ohlc.index, name="trigger")
    for date, stock_id in events:
        mask.loc[(pd.Timestamp(date), stock_id)] = True
    return mask


def _passing_result() -> EventStudyResult:
    return EventStudyResult(
        n_events=100,
        base_rate=0.50,
        hit_rate=0.56,
        mean_return_bp={3: 35.0, 5: 70.0},
        median_return_bp={3: 10.0, 5: 20.0},
        top5pct_excluded_mean_bp={3: 5.0, 5: 10.0},
        return_distribution={3: np.array([0.0035]), 5: np.array([0.007])},
        cost_adjusted_mean_bp={3: 35.0, 5: 70.0},
        cost_adjusted_median_bp={3: 10.0, 5: 20.0},
    )


@pytest.mark.unit
def test_compute_forward_returns_known_values() -> None:
    ohlc = _ohlc_frame()

    result = compute_forward_returns(ohlc, horizons=[1, 3])

    first_2330 = (pd.Timestamp("2025-01-02"), "2330")
    first_2317 = (pd.Timestamp("2025-01-02"), "2317")
    assert result.loc[first_2330, "forward_return_1d"] == pytest.approx(0.01)
    assert result.loc[first_2330, "forward_return_3d"] == pytest.approx(0.06)
    assert result.loc[first_2317, "forward_return_3d"] == pytest.approx(0.02)


@pytest.mark.unit
def test_compute_forward_returns_is_nan_safe_at_series_tail() -> None:
    ohlc = _ohlc_frame()

    result = compute_forward_returns(ohlc, horizons=[1, 3])

    last_2330 = (pd.Timestamp("2025-01-09"), "2330")
    near_tail_2330 = (pd.Timestamp("2025-01-07"), "2330")
    assert np.isnan(result.loc[last_2330, "forward_return_1d"])
    assert np.isnan(result.loc[near_tail_2330, "forward_return_3d"])


@pytest.mark.unit
def test_compute_forward_returns_respects_horizons_param() -> None:
    ohlc = _ohlc_frame()

    result = compute_forward_returns(ohlc, horizons=[5])

    assert list(result.columns) == ["forward_return_5d"]


@pytest.mark.unit
def test_event_study_empty_trigger_mask_returns_empty_result() -> None:
    ohlc = _ohlc_frame()
    mask = pd.Series(False, index=ohlc.index)

    result = event_study(mask, ohlc, horizons=[1])

    assert result.n_events == 0
    assert result.hit_rate == 0.0
    assert result.return_distribution[1].size == 0
    assert np.isnan(result.mean_return_bp[1])


@pytest.mark.unit
def test_event_study_all_trigger_mean_and_hit_rate() -> None:
    ohlc = _ohlc_frame()
    mask = pd.Series(True, index=ohlc.index)

    result = event_study(mask, ohlc, horizons=[1])

    expected_returns = compute_forward_returns(ohlc, [1])["forward_return_1d"].dropna()
    assert result.n_events == len(expected_returns)
    assert result.mean_return_bp[1] == pytest.approx(float(expected_returns.mean() * 10000))
    assert result.median_return_bp[1] == pytest.approx(float(expected_returns.median() * 10000))
    assert result.hit_rate == pytest.approx(float((expected_returns > 0).mean()))


@pytest.mark.unit
def test_event_study_uses_injected_cost_model() -> None:
    ohlc = _ohlc_frame()
    mask = _trigger_mask(ohlc, [("2025-01-02", "2330"), ("2025-01-03", "2330")])
    calls: list[tuple[float, float, float]] = []

    def cost_model(price_in: float, price_out: float, shares: float, **_: Any) -> dict[str, float]:
        calls.append((price_in, price_out, shares))
        return {"total": price_in * shares * 0.01}

    result = event_study(mask, ohlc, horizons=[1], cost_model=cost_model)
    raw_mean = result.mean_return_bp[1]

    assert len(calls) == 2
    assert result.cost_adjusted_mean_bp[1] == pytest.approx(raw_mean - 100.0)


@pytest.mark.unit
def test_event_study_top5pct_excluded_removes_largest_event() -> None:
    dates = pd.date_range("2025-01-02", periods=21, freq="B")
    idx = pd.MultiIndex.from_product([dates, ["2330"]], names=["date", "stock_id"])
    # Nineteen small gains and one outlier among the 20 events that have 1d forward returns.
    close = [100.0]
    close.extend([101.0 + i * 0.01 for i in range(19)])
    close.append(140.0)
    ohlc = pd.DataFrame({"close": close}, index=idx)
    mask = pd.Series(True, index=ohlc.index)

    result = event_study(mask, ohlc, horizons=[1])
    distribution_bp = result.return_distribution[1] * 10000
    expected = np.delete(distribution_bp, np.argmax(distribution_bp)).mean()

    assert result.n_events == 20
    assert result.top5pct_excluded_mean_bp[1] == pytest.approx(float(expected))


@pytest.mark.unit
def test_event_study_base_rate_uses_event_dates_universe() -> None:
    ohlc = _ohlc_frame()
    mask = _trigger_mask(ohlc, [("2025-01-02", "2330"), ("2025-01-03", "2330")])

    result = event_study(mask, ohlc, horizons=[1])
    fwd = compute_forward_returns(ohlc, [1])["forward_return_1d"]
    event_dates = [pd.Timestamp("2025-01-02"), pd.Timestamp("2025-01-03")]
    expected_base = (fwd.loc[event_dates] > 0).mean()

    assert result.base_rate == pytest.approx(float(expected_base))


@pytest.mark.unit
def test_evaluate_event_study_gate_passes_only_when_all_metrics_pass() -> None:
    verdict = evaluate_event_study_gate(_passing_result(), horizon=5)

    assert verdict.passed is True
    assert verdict.reasons == []


@pytest.mark.unit
def test_evaluate_event_study_gate_fails_with_metric_reasons() -> None:
    result = _passing_result()
    result.cost_adjusted_median_bp[5] = -1.0

    verdict = evaluate_event_study_gate(result, horizon=5)

    assert verdict.passed is False
    assert any("cost_adjusted_median" in reason for reason in verdict.reasons)


@pytest.mark.unit
def test_evaluate_event_study_gate_uses_horizon_specific_mean_threshold() -> None:
    result = _passing_result()
    result.cost_adjusted_mean_bp = {3: 35.0, 5: 35.0}

    assert evaluate_event_study_gate(result, horizon=3).passed is True
    assert evaluate_event_study_gate(result, horizon=5).passed is False


@pytest.mark.unit
def test_signals_package_does_not_import_research_helpers() -> None:
    signals_dir = Path("src/signals")
    offenders: list[str] = []
    for path in signals_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "src.research" or node.module.startswith("src.research."):
                    offenders.append(str(path))
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "src.research" or alias.name.startswith("src.research."):
                        offenders.append(str(path))

    assert offenders == []
