"""
Unit tests for stock news filtering helpers.
"""

from src.app.callbacks import (
    _collect_ticker_headlines,
    _extract_articles_from_run,
    _format_news_time,
    _render_fundamentals_strip,
    _render_ai_panel,
    _render_event_timeline,
    _render_favorite_signal_strip,
    _render_news_chat_messages,
    _render_right_rail_news_list,
)
from src.models import Advisor, AdvisorBullet, AdvisorDimension, FundamentalsSnapshot


def _run_dict():
    return {
        "categories": {
            "STOCK_TW": {
                "articles": [
                    {
                        "title": "台積電先進製程新聞",
                        "excerpt": "晶圓代工需求升溫",
                        "summary": "",
                        "full_text": "",
                        "published_at": "2026-04-24T09:00:00+08:00",
                        "related_stock_ids": [],
                    },
                    {
                        "title": "鴻海電動車新聞",
                        "excerpt": "2317 供應鏈",
                        "summary": "",
                        "full_text": "",
                        "published_at": "2026-04-24T08:00:00+08:00",
                        "related_stock_ids": [],
                    },
                ],
            },
            "FINANCIAL": {
                "articles": [
                    {
                        "title": "總經新聞",
                        "excerpt": "大盤震盪",
                        "summary": "",
                        "full_text": "",
                        "published_at": "2026-04-24T07:00:00+08:00",
                        "related_stock_ids": [],
                    },
                ],
            },
        }
    }


def test_extract_articles_falls_back_to_stock_name_for_legacy_untagged_news():
    articles = _extract_articles_from_run(_run_dict(), "ALL", "2330", "台積電")

    assert len(articles) == 1
    assert articles[0]["title"] == "台積電先進製程新聞"


def test_extract_articles_falls_back_to_stock_id_for_legacy_untagged_news():
    articles = _extract_articles_from_run(_run_dict(), "ALL", "2317", "鴻海")

    assert len(articles) == 1
    assert articles[0]["title"] == "鴻海電動車新聞"


def test_collect_ticker_headlines_prefers_stock_name_match():
    headlines = _collect_ticker_headlines(_run_dict(), "2330", "台積電")

    assert headlines[0]["title"] == "台積電先進製程新聞"


def test_format_news_time_displays_source_timestamps_in_taiwan_time():
    assert _format_news_time("2026-04-24T12:07:00+00:00") == "04/24 20:07"
    assert _format_news_time("2026-04-24T20:07:00+08:00") == "04/24 20:07"
    assert _format_news_time("2026-04-24T20:07:00") == "04/24 20:07"


def test_render_event_timeline_empty_state():
    rendered = _render_event_timeline(None)

    assert "議題演進尚未產生" in str(rendered.children)


def test_render_fundamentals_strip_shows_placeholders_for_missing_values():
    rendered = _render_fundamentals_strip(FundamentalsSnapshot())

    assert rendered.className == "fund-strip"
    assert str(rendered).count("--") == 6


def test_render_ai_panel_contains_expandable_dimension_cards():
    advisor = Advisor(
        overall_score=7.1,
        stance="偏多",
        confidence=0.82,
        delta="+0.4 vs 昨日",
        recommendation="偏多觀察。",
        dimensions=[
            AdvisorDimension(
                key="news",
                label="新聞面",
                score=7.4,
                direction="up",
                summary="新聞偏多。",
                bullets=[AdvisorBullet("bull", "法說展望優於預期。")],
            ),
            AdvisorDimension("chip", "籌碼面", 6.1, "up", "籌碼偏多。", []),
            AdvisorDimension("fund", "基本面", 5.5, "neu", "基本面中性。", []),
            AdvisorDimension("tech", "技術面", 6.8, "up", "技術面偏多。", []),
        ],
    )

    rendered = _render_ai_panel(advisor, "2330", "台積電")

    assert "AI 顧問" in str(rendered)
    assert str(rendered).count("ai-dim-card") == 4
    assert "策略觀點" in str(rendered)


def test_render_event_timeline_with_cluster():
    rendered = _render_event_timeline({
        "clusters": [
            {
                "title": "AI 供應鏈",
                "summary": "AI 需求升溫",
                "first_seen": "20260424",
                "last_seen": "20260425",
                "article_urls": ["https://example.com/a"],
                "daily_count": {"20260424": 1, "20260425": 2},
            }
        ]
    })

    assert rendered.className == "event-timeline-inner"
    assert "AI 供應鏈" in str(rendered)


def test_render_event_timeline_with_anomaly_badge():
    rendered = _render_event_timeline({
        "clusters": [
            {
                "title": "AI 供應鏈",
                "summary": "AI 需求升溫",
                "first_seen": "20260424",
                "last_seen": "20260425",
                "article_urls": ["https://example.com/a"],
                "daily_count": {"20260424": 1, "20260425": 3},
                "is_anomaly": True,
            }
        ]
    })

    assert "爆量" in str(rendered)


def test_render_favorite_signal_strip_marks_anomaly_stock():
    rendered = _render_favorite_signal_strip(
        [
            {
                "stock_id": "2330",
                "stock_name": "台積電",
                "signal": "neutral",
                "reason": "r",
            }
        ],
        {
            "clusters": [
                {
                    "is_anomaly": True,
                    "related_stock_ids": ["2330"],
                }
            ]
        },
    )

    assert "爆量" in str(rendered)


def test_render_news_chat_messages_with_citations():
    rendered = _render_news_chat_messages([
        {"role": "user", "content": "AI 最近如何？"},
        {
            "role": "assistant",
            "content": "AI 需求升溫 [1]",
            "citations": [
                {
                    "title": "AI demand",
                    "url": "https://example.com/ai",
                }
            ],
        },
    ])

    assert "AI demand" in str(rendered)
    assert "https://example.com/ai" in str(rendered)


def test_render_right_rail_news_list_sorts_by_impact_then_time():
    rendered = _render_right_rail_news_list([
        {
            "title": "低影響",
            "published_at": "2026-04-24T09:00:00+08:00",
            "impact_score": 3.0,
            "impact_direction": "neutral",
            "source": "A",
            "related_stock_ids": ["2330"],
            "url": "https://example.com/low",
        },
        {
            "title": "高影響較新",
            "published_at": "2026-04-24T10:00:00+08:00",
            "impact_score": 8.0,
            "impact_direction": "up",
            "source": "B",
            "related_stock_ids": ["2330"],
            "url": "https://example.com/high-new",
        },
        {
            "title": "高影響較舊",
            "published_at": "2026-04-24T08:00:00+08:00",
            "impact_score": 8.0,
            "impact_direction": "down",
            "source": "C",
            "related_stock_ids": ["2330"],
            "url": "https://example.com/high-old",
        },
    ])

    assert [row.children[1].children for row in rendered] == [
        "高影響較新",
        "高影響較舊",
        "低影響",
    ]
    assert rendered[0].className == "right-rail-news-row"
    assert "pill-up" in rendered[0].children[0].children[-1].className
