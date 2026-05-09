"""Tests for Phase 5 AI advisor heuristics."""

from datetime import datetime

from src.data.advisor import build_advisor
from src.models import (
    ChipKpiCard,
    FundamentalsSnapshot,
    PriceDirection,
    RealtimeQuote,
)


def _quote(change_percent: float = 2.4) -> RealtimeQuote:
    return RealtimeQuote(
        stock_id="2330",
        stock_name="台積電",
        current_price=920.0,
        open_price=900.0,
        high_price=925.0,
        low_price=898.0,
        previous_close=898.0,
        change_amount=22.0,
        change_percent=change_percent,
        direction=PriceDirection.UP,
        total_volume=45678,
        tick_volume=120,
        best_bid=919.0,
        best_ask=920.0,
        timestamp=datetime(2026, 5, 8, 10, 30),
    )


def test_build_advisor_returns_four_dimensions_in_spec_order():
    advisor = build_advisor("2330")

    assert [d.key for d in advisor.dimensions] == ["news", "chip", "fund", "tech"]
    assert advisor.stance == "中性"
    assert advisor.recommendation


def test_build_advisor_scores_positive_inputs_as_bullish():
    articles = [
        {"title": "法說展望優於預期", "impact_score": 8.5, "impact_direction": "up"},
        {"title": "外資調升目標價", "impact_score": 7.2, "impact_direction": "up"},
    ]
    cards = [
        ChipKpiCard("foreign", "外資", "+12,000", "up", "連3買"),
        ChipKpiCard("trust", "投信", "+800", "up", "連2買"),
        ChipKpiCard("dealer", "自營", "-120", "down", "小幅調節"),
    ]
    fund = FundamentalsSnapshot(
        eps_q=12.0,
        eps_yoy=24.0,
        gross_margin=52.5,
        gm_delta=1.8,
        pe=18.0,
        pe_avg=22.0,
        eps_period="2026Q1",
    )
    closes = [float(v) for v in range(80, 141)]

    advisor = build_advisor(
        "2330",
        articles=articles,
        chip_cards=cards,
        fundamentals=fund,
        quote=_quote(),
        daily_closes=closes,
    )

    assert advisor.overall_score > 6.0
    assert advisor.stance == "偏多"
    assert advisor.confidence > 0.7
    assert advisor.dimensions[0].direction == "up"
    assert advisor.dimensions[3].direction == "up"
