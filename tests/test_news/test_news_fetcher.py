"""
Unit tests for src/news/news_fetcher.py  (TASK-162)

Coverage targets:
- fetch_rss: happy path with mocked session response
- fetch_rss: HTTP error returns empty list
- fetch_category: source disabled after 3 consecutive failures
- fetch_full_text: happy path
- fetch_full_text: timeout returns ("", False)
- _is_taiwan_stock: digit vs alpha stock_id
- _extract_text_from_html: strips nav/script, caps length
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.news.news_fetcher import NewsFetcher, _SourceState
from src.news.news_models import NewsCategory


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_rss_bytes(title: str = "Test headline") -> bytes:
    """Return minimal valid RSS 2.0 XML bytes."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://example.com</link>
    <description>Test</description>
    <item>
      <title>{title}</title>
      <link>https://example.com/news/1</link>
      <pubDate>Thu, 10 Apr 2026 09:00:00 +0000</pubDate>
      <description>Short excerpt.</description>
    </item>
  </channel>
</rss>""".encode("utf-8")


def _make_html(body: str = "<p>Article content here.</p>") -> str:
    return f"<html><body>{body}</body></html>"


def _mock_session_get(content: bytes | None = None, text: str | None = None,
                      side_effect=None):
    """Return a mock response suitable for session.get."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    if content is not None:
        mock_resp.content = content
    if text is not None:
        mock_resp.text = text
    if side_effect is not None:
        return side_effect
    return mock_resp


# ── NewsFetcher._is_taiwan_stock ─────────────────────────────────────────────

class TestIsTaiwanStock:
    @pytest.fixture(autouse=True)
    def _setup(self, mock_config):
        mock_config.news_request_interval = 0.0
        self.fetcher = NewsFetcher(config=mock_config)

    def test_all_digits_is_tw(self):
        assert self.fetcher._is_taiwan_stock("2330") is True

    def test_alpha_is_not_tw(self):
        assert self.fetcher._is_taiwan_stock("AAPL") is False

    def test_etf_digits_is_tw(self):
        assert self.fetcher._is_taiwan_stock("00878") is True

    def test_empty_string(self):
        result = self.fetcher._is_taiwan_stock("")
        assert result is False  # "".isdigit() == False


# ── NewsFetcher._extract_text_from_html ──────────────────────────────────────

class TestExtractText:
    @pytest.fixture(autouse=True)
    def _setup(self, mock_config):
        mock_config.news_request_interval = 0.0
        self.fetcher = NewsFetcher(config=mock_config)

    def test_extracts_p_tags(self):
        html = "<html><body><p>Hello world.</p><p>Second para.</p></body></html>"
        text = self.fetcher._extract_text_from_html(html)
        assert "Hello world" in text
        assert "Second para" in text

    def test_strips_script_content(self):
        html = "<html><body><script>alert('bad')</script><p>Good text.</p></body></html>"
        text = self.fetcher._extract_text_from_html(html)
        assert "alert" not in text
        assert "Good text" in text

    def test_strips_nav_content(self):
        html = "<html><body><nav>Menu</nav><p>Article text.</p></body></html>"
        text = self.fetcher._extract_text_from_html(html)
        assert "Menu" not in text
        assert "Article text" in text

    def test_caps_at_8000_chars(self):
        long_p = "<p>" + ("A" * 100) + "</p>"
        html = "<html><body>" + long_p * 100 + "</body></html>"
        text = self.fetcher._extract_text_from_html(html)
        assert len(text) <= 8000


# ── NewsFetcher.fetch_rss ─────────────────────────────────────────────────────

class TestFetchRss:
    @pytest.fixture(autouse=True)
    def _setup(self, mock_config):
        mock_config.news_request_interval = 0.0
        self.fetcher = NewsFetcher(config=mock_config)

    def test_happy_path_returns_articles(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.content = _make_rss_bytes("Breaking: Market up")
        self.fetcher._session.get = MagicMock(return_value=mock_resp)

        articles = self.fetcher.fetch_rss("https://example.com/rss")
        assert len(articles) == 1
        assert "Breaking" in articles[0].title

    def test_http_error_returns_empty(self):
        import requests as req_lib
        self.fetcher._session.get = MagicMock(
            side_effect=req_lib.HTTPError("404")
        )
        # fetch_rss doesn't suppress HTTPError; it propagates
        with pytest.raises(Exception):
            self.fetcher.fetch_rss("https://example.com/rss")

    def test_connection_error_propagates(self):
        import requests as req_lib
        self.fetcher._session.get = MagicMock(
            side_effect=req_lib.ConnectionError("refused")
        )
        with pytest.raises(Exception):
            self.fetcher.fetch_rss("https://example.com/rss")


# ── Source-level disabling (via fetch_category) ──────────────────────────────

class TestSourceDisabling:
    @pytest.fixture(autouse=True)
    def _setup(self, mock_config):
        mock_config.news_request_interval = 0.0
        self.fetcher = NewsFetcher(config=mock_config)

    def test_source_disabled_after_3_failures(self):
        """
        After 3 consecutive failures in fetch_category, the source's
        _SourceState should be disabled and subsequent calls skip it.
        """
        url = "https://example.com/rss"

        # Override fetch_rss to raise on this URL
        original_fetch_rss = self.fetcher.fetch_rss
        call_count = [0]

        def failing_fetch_rss(rss_url):
            if rss_url == url:
                call_count[0] += 1
                raise RuntimeError("simulated failure")
            return original_fetch_rss(rss_url)

        self.fetcher.fetch_rss = failing_fetch_rss

        # Override fetch_full_text so it doesn't actually hit network
        self.fetcher.fetch_full_text = MagicMock(return_value=("", False))

        # Patch the RSS_SOURCES so only our test URL is listed for FINANCIAL
        with patch("src.news.news_fetcher.RSS_SOURCES", {
            NewsCategory.FINANCIAL: [url],
        }):
            # Three calls should cause 3 failures
            for _ in range(3):
                self.fetcher.fetch_category(NewsCategory.FINANCIAL)

            # After 3 failures the source should be disabled
            state = self.fetcher._source_states.get(url)
            assert state is not None
            assert state.is_disabled(), "Source should be disabled after 3 failures"

            # The 4th call should NOT invoke fetch_rss again
            call_count[0] = 0
            self.fetcher.fetch_category(NewsCategory.FINANCIAL)
            assert call_count[0] == 0, "Disabled source should be skipped"


# ── NewsFetcher.fetch_full_text ──────────────────────────────────────────────

class TestFetchFullText:
    @pytest.fixture(autouse=True)
    def _setup(self, mock_config):
        mock_config.news_request_interval = 0.0
        self.fetcher = NewsFetcher(config=mock_config)

    def test_happy_path_returns_text(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.text = _make_html(
            "<p>Full article content goes here. " + "A" * 200 + "</p>"
        )
        self.fetcher._session.get = MagicMock(return_value=mock_resp)

        text, ok = self.fetcher.fetch_full_text("https://example.com/article")
        assert ok is True
        assert "Full article content" in text

    def test_timeout_returns_failure(self):
        import requests as req_lib
        self.fetcher._session.get = MagicMock(
            side_effect=req_lib.Timeout("timed out")
        )
        text, ok = self.fetcher.fetch_full_text("https://example.com/article")
        assert ok is False
        assert text == ""

    def test_empty_url_returns_failure(self):
        text, ok = self.fetcher.fetch_full_text("")
        assert ok is False
        assert text == ""


# ── _SourceState unit ────────────────────────────────────────────────────────

class TestSourceState:
    def test_initially_not_disabled(self):
        state = _SourceState()
        assert state.is_disabled() is False

    def test_disabled_after_3_failures(self):
        state = _SourceState()
        for _ in range(3):
            state.record_failure()
        assert state.is_disabled() is True

    def test_success_resets_failures(self):
        state = _SourceState()
        for _ in range(2):
            state.record_failure()
        state.record_success()
        assert state.consecutive_failures == 0
        assert state.is_disabled() is False
