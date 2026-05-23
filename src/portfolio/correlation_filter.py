"""TASK-R03 — Sector and correlation based portfolio filter (V2 §6.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

import pandas as pd

__all__ = [
    "CorrelationDecision",
    "CorrelationFilter",
    "CorrelationFilterConfig",
    "PositionExposure",
    "build_correlation_clusters",
    "portfolio_beta_after_add",
]


@dataclass(frozen=True)
class PositionExposure:
    stock_id: str
    market_value: float
    beta: float


@dataclass(frozen=True)
class CorrelationFilterConfig:
    correlation_window: int = 60
    correlation_threshold: float = 0.9
    max_per_cluster: int = 2
    max_portfolio_beta: float = 1.2

    def __post_init__(self) -> None:
        if self.correlation_window <= 1:
            raise ValueError("correlation_window must be > 1")
        if not 0.0 <= self.correlation_threshold <= 1.0:
            raise ValueError("correlation_threshold must be in [0, 1]")
        if self.max_per_cluster <= 0:
            raise ValueError("max_per_cluster must be positive")
        if self.max_portfolio_beta <= 0:
            raise ValueError("max_portfolio_beta must be positive")


@dataclass(frozen=True)
class CorrelationDecision:
    allowed: bool
    candidate: str
    cluster_id: str
    cluster_count: int
    projected_beta: float
    reasons: list[str] = field(default_factory=list)


def build_correlation_clusters(
    *,
    returns: pd.DataFrame,
    sectors: Mapping[str, str],
    threshold: float = 0.9,
) -> dict[str, str]:
    if returns.empty:
        return {}
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be in [0, 1]")

    stock_ids = [str(c) for c in returns.columns]
    parent = {sid: sid for sid in stock_ids}
    corr = returns.astype(float).corr()

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra = find(a)
        rb = find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for i, a in enumerate(stock_ids):
        for b in stock_ids[i + 1:]:
            if sectors.get(a, a) != sectors.get(b, b):
                continue
            val = corr.loc[a, b]
            if pd.notna(val) and abs(float(val)) >= threshold:
                union(a, b)

    return {sid: f"{sectors.get(sid, 'unknown')}:{find(sid)}" for sid in stock_ids}


def portfolio_beta_after_add(
    *,
    current_positions: Sequence[PositionExposure],
    candidate_market_value: float,
    candidate_beta: float,
    portfolio_equity: float,
) -> float:
    if portfolio_equity <= 0:
        raise ValueError("portfolio_equity must be positive")
    weighted = sum(p.market_value * p.beta for p in current_positions)
    weighted += candidate_market_value * candidate_beta
    return weighted / portfolio_equity


class CorrelationFilter:
    def __init__(self, config: CorrelationFilterConfig | None = None) -> None:
        self.config = config or CorrelationFilterConfig()

    def evaluate(
        self,
        *,
        candidate: str,
        current_positions: Sequence[PositionExposure],
        clusters: Mapping[str, str],
        candidate_market_value: float,
        candidate_beta: float,
        portfolio_equity: float,
    ) -> CorrelationDecision:
        cluster_id = clusters.get(candidate, candidate)
        cluster_count = sum(
            1 for p in current_positions if clusters.get(p.stock_id, p.stock_id) == cluster_id
        )
        projected_beta = portfolio_beta_after_add(
            current_positions=current_positions,
            candidate_market_value=candidate_market_value,
            candidate_beta=candidate_beta,
            portfolio_equity=portfolio_equity,
        )

        reasons: list[str] = []
        if cluster_count >= self.config.max_per_cluster:
            reasons.append("cluster_limit")
        if projected_beta > self.config.max_portfolio_beta:
            reasons.append("portfolio_beta")

        return CorrelationDecision(
            allowed=not reasons,
            candidate=candidate,
            cluster_id=cluster_id,
            cluster_count=cluster_count,
            projected_beta=projected_beta,
            reasons=reasons,
        )
