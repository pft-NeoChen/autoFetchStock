"""
Unit tests for stock search ranking and submit resolution.
"""

from datetime import datetime

import pytest

from src.exceptions import StockNotFoundError
from src.fetcher.data_fetcher import DataFetcher
from src.fetcher.twse_parser import TWSEParser
from src.models import StockInfo


@pytest.fixture
def sample_stock_list():
    return [
        StockInfo(stock_id="030264", stock_name="國巨元富58購01"),
        StockInfo(stock_id="033843", stock_name="國巨中信57購01"),
        StockInfo(stock_id="2327", stock_name="國巨*"),
        StockInfo(stock_id="2330", stock_name="台積電"),
        StockInfo(stock_id="2887", stock_name="台新金"),
    ]


class TestSearchStocks:
    def test_exact_name_ranks_underlying_stock_before_warrants(self, sample_stock_list):
        results = TWSEParser.search_stocks(sample_stock_list, "國巨")

        assert results
        assert results[0].stock_id == "2327"

    def test_exact_warrant_name_stays_first_for_warrant_queries(self, sample_stock_list):
        results = TWSEParser.search_stocks(sample_stock_list, "國巨元富58購01")

        assert results
        assert results[0].stock_id == "030264"

    def test_full_width_digits_match_exact_stock_id(self, sample_stock_list):
        results = TWSEParser.search_stocks(sample_stock_list, "２３２７")

        assert results
        assert results[0].stock_id == "2327"


class TestResolveStock:
    @pytest.fixture(autouse=True)
    def _setup(self, sample_stock_list):
        self.fetcher = DataFetcher()
        self.fetcher._stock_list_cache = sample_stock_list
        self.fetcher._stock_list_cache_time = datetime.now()

    def test_resolves_exact_stock_name(self):
        stock = self.fetcher.resolve_stock("國巨")

        assert stock.stock_id == "2327"

    def test_resolves_exact_stock_id(self):
        stock = self.fetcher.resolve_stock("2330")

        assert stock.stock_name == "台積電"

    def test_rejects_ambiguous_partial_name(self):
        with pytest.raises(StockNotFoundError):
            self.fetcher.resolve_stock("台")
