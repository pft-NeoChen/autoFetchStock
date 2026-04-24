"""
Unit tests for news store refresh behavior.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from src.app.callbacks import CallbackManager


def _manager(storage=None, news_processor=None):
    return CallbackManager(
        app=None,
        fetcher=MagicMock(),
        storage=storage or MagicMock(),
        processor=MagicMock(),
        renderer=MagicMock(),
        scheduler=MagicMock(),
        news_processor=news_processor,
    )


def test_load_news_store_data_uses_cached_news_by_default():
    storage = MagicMock()
    storage.load_latest_news.return_value = SimpleNamespace(to_dict=lambda: {"cached": True})
    news_processor = MagicMock()
    manager = _manager(storage=storage, news_processor=news_processor)

    result = manager._load_news_store_data(force_refresh=False)

    assert result == {"cached": True}
    storage.load_latest_news.assert_called_once()
    news_processor.run.assert_not_called()


def test_load_news_store_data_runs_processor_for_manual_refresh():
    storage = MagicMock()
    news_processor = MagicMock()
    news_processor.run.return_value = SimpleNamespace(to_dict=lambda: {"fresh": True})
    manager = _manager(storage=storage, news_processor=news_processor)

    result = manager._load_news_store_data(force_refresh=True)

    assert result == {"fresh": True}
    news_processor.run.assert_called_once()
    storage.load_latest_news.assert_not_called()
