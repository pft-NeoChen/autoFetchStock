"""
Data fetcher for autoFetchStock.

This module handles all TWSE API interactions:
- Real-time quote fetching (getStockInfo.jsp)
- Daily history fetching (STOCK_DAY)
- Intraday tick fetching
- Stock search functionality

Includes rate limiting, timeout handling, and retry logic.
"""

import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

import requests

from src.models import (
    StockInfo,
    RealtimeQuote,
    DailyOHLC,
    IntradayTick,
)
from src.exceptions import (
    ConnectionTimeoutError,
    InvalidDataError,
    StockNotFoundError,
    ServiceUnavailableError,
)
from src.fetcher.twse_parser import TWSEParser

logger = logging.getLogger("autofetchstock.fetcher")


class DataFetcher:
    """
    TWSE data fetcher with rate limiting and error handling.

    Implements REQ-002 (HTTPS), REQ-010 (search), REQ-011 (code/name search),
    REQ-060 (interval control), REQ-064 (timestamp tracking), and error
    handling requirements REQ-100 through REQ-104.
    """

    # API endpoints
    REALTIME_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
    DAILY_HISTORY_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
    OTC_HISTORY_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
    STOCK_LIST_URL = "https://isin.twse.com.tw/isin/C_public.jsp"

    # Rate limiting and timeout settings
    REQUEST_INTERVAL: float = 3.0  # Minimum seconds between requests
    CONNECTION_TIMEOUT: int = 10  # Connection timeout in seconds
    RETRY_DELAY: int = 30  # Delay before retry on timeout (REQ-100)

    # Failure tracking
    MAX_CONSECUTIVE_FAILURES: int = 3

    # HTTP headers
    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.tpex.org.tw/zh-tw/mainboard/trading/info/stock-pricing.html"
    }

    def __init__(self, storage=None, shioaji_fetcher=None):
        """Initialize HTTP session and tracking variables."""
        self._session = requests.Session()
        self._session.headers.update(self.DEFAULT_HEADERS)
        self._last_request_time: float = 0
        self._consecutive_failures: int = 0
        self._stock_list_cache: Optional[List[StockInfo]] = None
        self._stock_list_cache_time: Optional[datetime] = None
        self._realtime_quote_cache: Dict[str, RealtimeQuote] = {}
        self._is_fetching_list: bool = False
        self.storage = storage # Optional storage for persistent cache
        self.shioaji_fetcher = shioaji_fetcher # Optional Shioaji fetcher for cached quotes
        logger.info("DataFetcher initialized")
        
        # Try to pre-load stock list in background or early
        # Note: In a real app, this might be better in a separate thread
        # but for now we'll just let the first search handle it or call it here.
        # self._get_stock_list() 

    def fetch_realtime_quote(self, stock_id: str, blocking: bool = True) -> Optional[RealtimeQuote]:
        """
        Fetch real-time quote for a stock (REQ-002).

        Args:
            stock_id: Stock ID (e.g., "2330")
            blocking: Whether to block/sleep if rate limit is hit.

        Returns:
            RealtimeQuote with current price, change, volume, etc.
            Returns None if blocking=False and rate limit is hit.

        Raises:
            ConnectionTimeoutError: Connection timeout (REQ-100)
            InvalidDataError: Invalid response format (REQ-101)
            StockNotFoundError: Stock not found (REQ-102)
            ServiceUnavailableError: Too many consecutive failures (REQ-104)
        """
        # Check Shioaji cache first (bypass TWSE API if available)
        if self.shioaji_fetcher:
            cached_quote = self.shioaji_fetcher.get_last_quote(stock_id)
            if cached_quote:
                self._realtime_quote_cache[stock_id] = cached_quote
                logger.debug(f"Using cached Shioaji quote for {stock_id}: {cached_quote.current_price}")
                return cached_quote

        self._check_consecutive_failures()

        # Determine if it's TSE or OTC
        stock_list = self._get_stock_list()
        prefix = "tse"
        for s in stock_list:
            if s.stock_id == stock_id:
                prefix = s.market
                break

        # Format the exchange channel parameter
        ex_ch = f"{prefix}_{stock_id}.tw"
        params = {
            "ex_ch": ex_ch,
            "json": "1",
            "delay": "0",
        }

        try:
            data = self._make_request(self.REALTIME_URL, params, blocking=blocking)
            quote = TWSEParser.parse_realtime_quote(data, stock_id)
            self._realtime_quote_cache[stock_id] = quote
            self._reset_failure_count()
            logger.info(f"Fetched realtime quote for {stock_id}: {quote.current_price}")
            return quote

        except BlockingIOError:
            # Rate limit hit in non-blocking mode
            return self._realtime_quote_cache.get(stock_id)
            
        except (InvalidDataError, StockNotFoundError):
            self._increment_failure_count()
            raise

    def get_cached_quote(self, stock_id: str) -> Optional[RealtimeQuote]:
        """Return the most recent cached quote from Shioaji or local fallback cache."""
        if self.shioaji_fetcher:
            cached_quote = self.shioaji_fetcher.get_last_quote(stock_id)
            if cached_quote:
                self._realtime_quote_cache[stock_id] = cached_quote
                return cached_quote
        return self._realtime_quote_cache.get(stock_id)

    def fetch_daily_history(
        self,
        stock_id: str,
        year: int,
        month: int
    ) -> List[DailyOHLC]:
        """
        Fetch daily OHLC history for a stock for a specific month.
        Supports both TSE and OTC stocks.
        """
        self._check_consecutive_failures()

        market = self._get_market(stock_id)

        if market == "tse":
            # TWSE (Listed)
            date_str = f"{year}{month:02d}01"
            params = {
                "response": "json",
                "date": date_str,
                "stockNo": stock_id,
            }
            url = self.DAILY_HISTORY_URL
        else:
            # TPEx (OTC)
            params = {
                "code": stock_id,
                "date": f"{year}/{month:02d}/01",
                "response": "json",
            }
            url = self.OTC_HISTORY_URL

        try:
            method = "GET" if market == "tse" else "POST"
            data = self._make_request(url, params, method=method)
            records = TWSEParser.parse_daily_history(data, stock_id)
            self._reset_failure_count()
            logger.info(f"Fetched {len(records)} daily records for {stock_id} ({year}/{month})")
            return records

        except InvalidDataError:
            self._increment_failure_count()
            raise

    def _get_market(self, stock_id: str) -> str:
        """Helper to get market for a stock_id."""
        stock_list = self._get_stock_list()
        for s in stock_list:
            if s.stock_id == stock_id:
                return s.market
        return "tse"

    def fetch_intraday_ticks(
        self,
        stock_id: str,
        previous_close: float = None
    ) -> List[IntradayTick]:
        """
        Fetch intraday tick data for a stock.

        Note: TWSE doesn't provide public tick-by-tick API easily.
        This is a placeholder that returns empty list.

        Args:
            stock_id: Stock ID
            previous_close: Previous day's closing price

        Returns:
            List of IntradayTick records (currently empty)
        """
        logger.warning(f"Intraday tick fetching not fully implemented for {stock_id}")
        # Note: Real implementation would need a different data source
        # or use the realtime quote endpoint with polling
        return []

    def preload_stock_list(self) -> None:
        """Pre-load stock list into cache."""
        self._get_stock_list()

    def search_stock(self, keyword: str) -> List[StockInfo]:
        """
        Search stocks by ID or name (REQ-010, REQ-011).

        Args:
            keyword: Search keyword (stock ID or name)

        Returns:
            List of matching StockInfo (up to 20 results)

        Raises:
            ConnectionTimeoutError: Connection timeout
        """
        # Normalize keyword for search (handle full-width if parser doesn't)
        # Parser now handles it, but we'll strip it here anyway
        keyword = keyword.strip()
        if not keyword:
            return []

        # Get or refresh stock list cache
        stock_list = self._get_stock_list()

        # Search using parser
        results = TWSEParser.search_stocks(stock_list, keyword)
        logger.info(f"Search '{keyword}' returned {len(results)} results")
        return results

    def resolve_stock(self, keyword: str) -> StockInfo:
        """
        Resolve a user-entered stock ID or exact stock name into StockInfo.

        Falls back to search ranking, but only auto-selects when the match is
        unambiguous enough for a submit action.
        """
        keyword = keyword.strip()
        if not keyword:
            raise StockNotFoundError(keyword=keyword)

        normalized_keyword = TWSEParser.normalize_search_text(keyword)
        stock_list = self._get_stock_list()

        for stock in stock_list:
            if TWSEParser.normalize_search_text(stock.stock_id) == normalized_keyword:
                return stock

        results = TWSEParser.search_stocks(stock_list, keyword)
        if not results:
            raise StockNotFoundError(keyword=keyword)

        top_match = results[0]
        if len(results) == 1:
            return top_match

        if TWSEParser.normalize_search_text(top_match.stock_name) == normalized_keyword:
            return top_match

        raise StockNotFoundError(keyword=keyword)

    def _get_stock_list(self) -> List[StockInfo]:
        """
        Get stock list, using cache if available and fresh.

        Returns:
            List of all StockInfo
        """
        # 1. Check memory cache (valid for 1 hour)
        if self._stock_list_cache and self._stock_list_cache_time:
            age = (datetime.now() - self._stock_list_cache_time).total_seconds()
            if age < 3600:
                return self._stock_list_cache

        # 2. Check persistent cache (valid for 24 hours)
        if self.storage:
            cached_list, cached_time = self.storage.load_stock_list_cache()
            if cached_list and cached_time:
                age = (datetime.now() - cached_time).total_seconds()
                if age < 86400: # 24 hours
                    # Convert dicts back to StockInfo objects
                    self._stock_list_cache = [
                        StockInfo(
                            stock_id=s["stock_id"], 
                            stock_name=s["stock_name"], 
                            market=s["market"]
                        ) for s in cached_list
                    ]
                    self._stock_list_cache_time = cached_time # Use file time or now? File time is safer.
                    logger.info(f"Loaded {len(self._stock_list_cache)} stocks from persistent cache")
                    return self._stock_list_cache

        try:
            # 3. Fetch from Web
            # Fetch Listed stocks (TSE)
            tse_params = {"strMode": "2"}
            tse_response = self._make_request(
                self.STOCK_LIST_URL,
                tse_params,
                expect_json=False,
                bypass_limit=True
            )
            tse_stocks = TWSEParser.parse_stock_list(tse_response, market="tse")

            # Fetch OTC stocks (OTC)
            otc_params = {"strMode": "4"}
            otc_response = self._make_request(
                self.STOCK_LIST_URL,
                otc_params,
                expect_json=False,
                bypass_limit=True
            )
            otc_stocks = TWSEParser.parse_stock_list(otc_response, market="otc")

            self._stock_list_cache = tse_stocks + otc_stocks
            self._stock_list_cache_time = datetime.now()
            
            # 4. Save to persistent cache
            if self.storage:
                # Convert to dicts for JSON
                cache_data = [
                    {
                        "stock_id": s.stock_id,
                        "stock_name": s.stock_name,
                        "market": s.market
                    } for s in self._stock_list_cache
                ]
                self.storage.save_stock_list_cache(cache_data)
            
            logger.info(f"Refreshed stock list cache: {len(self._stock_list_cache)} stocks (TSE: {len(tse_stocks)}, OTC: {len(otc_stocks)})")
            return self._stock_list_cache

        except Exception as e:
            logger.warning(f"Failed to fetch stock list: {e}")
            if self._stock_list_cache:
                return self._stock_list_cache
            return []

    def _make_request(
        self,
        url: str,
        params: dict = None,
        expect_json: bool = True,
        bypass_limit: bool = False,
        blocking: bool = True,
        method: str = "GET",
    ):
        """
        Make HTTP request with rate limiting, timeout, and retry.

        Args:
            url: Request URL
            params: Query parameters
            expect_json: Whether to parse response as JSON
            bypass_limit: Whether to skip rate limiting (for non-API calls)
            blocking: Whether to block if rate limit is hit

        Returns:
            Parsed JSON dict or raw text response

        Raises:
            ConnectionTimeoutError: Connection timeout after retry
            InvalidDataError: Invalid response format
            BlockingIOError: If non-blocking and rate limit hit
        """
        # Rate limiting (REQ-060)
        if not bypass_limit:
            if not self._enforce_rate_limit(blocking=blocking):
                raise BlockingIOError("Rate limit exceeded")

        # First attempt
        try:
            return self._execute_request(url, params, expect_json, method=method)

        except ConnectionTimeoutError:
            # Retry after delay (REQ-100)
            logger.warning(f"Request timeout, retrying in {self.RETRY_DELAY}s...")
            time.sleep(self.RETRY_DELAY)

            try:
                return self._execute_request(url, params, expect_json, method=method)
            except ConnectionTimeoutError:
                self._increment_failure_count()
                raise

    def _execute_request(
        self,
        url: str,
        params: dict = None,
        expect_json: bool = True,
        method: str = "GET",
    ):
        """
        Execute single HTTP request.

        Args:
            url: Request URL
            params: Query parameters
            expect_json: Whether to parse response as JSON

        Returns:
            Parsed JSON dict or raw text response

        Raises:
            ConnectionTimeoutError: Connection timeout
            InvalidDataError: Invalid response format
        """
        try:
            method = method.upper()
            request_kwargs = {"timeout": self.CONNECTION_TIMEOUT}
            if method == "GET":
                request_kwargs["params"] = params
            else:
                request_kwargs["data"] = params

            response = self._session.request(method, url, **request_kwargs)
            response.raise_for_status()

            # Update last request time (REQ-064)
            self._last_request_time = time.time()

            if expect_json:
                try:
                    return response.json()
                except ValueError as e:
                    logger.error(f"JSON parse error: {e}")
                    raise InvalidDataError(
                        message="回應格式非 JSON",
                        field="response",
                        value=response.text[:100]
                    )
            else:
                return response.text

        except requests.Timeout:
            logger.warning(f"Request timeout: {url}")
            raise ConnectionTimeoutError(
                url=url,
                timeout=self.CONNECTION_TIMEOUT
            )

        except requests.RequestException as e:
            logger.error(f"Request error: {e}")
            raise ConnectionTimeoutError(
                url=url,
                timeout=self.CONNECTION_TIMEOUT
            )

    def _enforce_rate_limit(self, blocking: bool = True) -> bool:
        """
        Enforce minimum interval between requests.

        Implements rate limiting per TWSE API requirements.

        Args:
            blocking: Whether to sleep if rate limit is hit.

        Returns:
            True if request can proceed (either waited or didn't need to).
            False if rate limit hit and blocking=False.
        """
        if self._last_request_time > 0:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.REQUEST_INTERVAL:
                if not blocking:
                    return False
                
                sleep_time = self.REQUEST_INTERVAL - elapsed
                logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
                time.sleep(sleep_time)
        return True

    def _check_consecutive_failures(self) -> None:
        """
        Check if consecutive failures exceed threshold.

        Raises:
            ServiceUnavailableError: Too many consecutive failures (REQ-104)
        """
        if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
            logger.error(
                f"Service unavailable: {self._consecutive_failures} consecutive failures"
            )
            raise ServiceUnavailableError(
                failures=self._consecutive_failures
            )

    def _increment_failure_count(self) -> None:
        """Increment consecutive failure counter."""
        self._consecutive_failures += 1
        logger.warning(f"Consecutive failures: {self._consecutive_failures}")

    def _reset_failure_count(self) -> None:
        """Reset consecutive failure counter on success."""
        if self._consecutive_failures > 0:
            logger.debug(f"Reset failure count from {self._consecutive_failures}")
            self._consecutive_failures = 0

    def close(self) -> None:
        """Close HTTP session and cleanup resources."""
        self._session.close()
        logger.info("DataFetcher closed")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False
