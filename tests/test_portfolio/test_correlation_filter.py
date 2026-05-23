"""TASK-R03 — Correlation Filter."""

from __future__ import annotations

import pandas as pd
import pytest

from src.portfolio.correlation_filter import (
    CorrelationFilter,
    CorrelationFilterConfig,
    PositionExposure,
    build_correlation_clusters,
    portfolio_beta_after_add,
)


def _returns() -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=60, freq="B")
    base = pd.Series([i * 0.001 for i in range(60)], index=idx)
    return pd.DataFrame(
        {
            "2330": base,
            "2454": base * 1.01,
            "2303": base * 0.99,
            "2881": -base,
            "1301": pd.Series([(-1) ** i * 0.002 for i in range(60)], index=idx),
        }
    )


def test_build_correlation_clusters_groups_highly_correlated_same_sector() -> None:
    sectors = {"2330": "semi", "2454": "semi", "2303": "semi", "2881": "finance"}

    clusters = build_correlation_clusters(
        returns=_returns(),
        sectors=sectors,
        threshold=0.9,
    )

    assert clusters["2330"] == clusters["2454"] == clusters["2303"]
    assert clusters["2881"] != clusters["2330"]


def test_build_correlation_clusters_keeps_low_correlation_separate() -> None:
    sectors = {"2330": "semi", "1301": "semi"}

    clusters = build_correlation_clusters(
        returns=_returns()[["2330", "1301"]],
        sectors=sectors,
        threshold=0.9,
    )

    assert clusters["2330"] != clusters["1301"]


def test_filter_blocks_candidate_when_cluster_limit_reached() -> None:
    filt = CorrelationFilter(CorrelationFilterConfig(max_per_cluster=2))
    clusters = {"2330": "semi:2330", "2454": "semi:2330", "2303": "semi:2330"}

    decision = filt.evaluate(
        candidate="2303",
        current_positions=[
            PositionExposure("2330", market_value=100_000, beta=1.0),
            PositionExposure("2454", market_value=100_000, beta=1.1),
        ],
        clusters=clusters,
        candidate_market_value=100_000,
        candidate_beta=1.0,
        portfolio_equity=1_000_000,
    )

    assert decision.allowed is False
    assert "cluster_limit" in decision.reasons


def test_filter_allows_candidate_in_different_cluster() -> None:
    filt = CorrelationFilter(CorrelationFilterConfig(max_per_cluster=2))
    clusters = {"2330": "semi:2330", "2454": "semi:2330", "2881": "finance:2881"}

    decision = filt.evaluate(
        candidate="2881",
        current_positions=[
            PositionExposure("2330", market_value=100_000, beta=1.0),
            PositionExposure("2454", market_value=100_000, beta=1.1),
        ],
        clusters=clusters,
        candidate_market_value=100_000,
        candidate_beta=0.8,
        portfolio_equity=1_000_000,
    )

    assert decision.allowed is True
    assert decision.projected_beta <= 1.2


def test_portfolio_beta_after_add_weighted_by_market_value() -> None:
    beta = portfolio_beta_after_add(
        current_positions=[
            PositionExposure("2330", market_value=100_000, beta=1.0),
            PositionExposure("2454", market_value=200_000, beta=1.3),
        ],
        candidate_market_value=100_000,
        candidate_beta=0.5,
        portfolio_equity=1_000_000,
    )

    assert beta == pytest.approx((100_000 * 1.0 + 200_000 * 1.3 + 100_000 * 0.5) / 1_000_000)


def test_filter_blocks_when_projected_portfolio_beta_exceeds_cap() -> None:
    filt = CorrelationFilter(CorrelationFilterConfig(max_portfolio_beta=1.2))

    decision = filt.evaluate(
        candidate="2603",
        current_positions=[PositionExposure("2330", market_value=500_000, beta=1.5)],
        clusters={"2330": "semi:2330", "2603": "shipping:2603"},
        candidate_market_value=400_000,
        candidate_beta=1.4,
        portfolio_equity=1_000_000,
    )

    assert decision.allowed is False
    assert decision.projected_beta > 1.2
    assert "portfolio_beta" in decision.reasons


def test_unknown_candidate_cluster_is_itself() -> None:
    filt = CorrelationFilter()

    decision = filt.evaluate(
        candidate="9999",
        current_positions=[],
        clusters={},
        candidate_market_value=100_000,
        candidate_beta=1.0,
        portfolio_equity=1_000_000,
    )

    assert decision.allowed is True
    assert decision.cluster_id == "9999"
