"""
Unit tests for stock news filtering helpers.
"""

from src.app.callbacks import (
    _collect_ticker_headlines,
    _extract_articles_from_run,
    _render_event_timeline,
)


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


def test_render_event_timeline_empty_state():
    rendered = _render_event_timeline(None)

    assert "議題演進尚未產生" in str(rendered.children)


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
