"""
TWSE API response parser for autoFetchStock.

This module handles parsing and validation of TWSE API responses:
- Real-time quote parsing (getStockInfo.jsp)
- Daily history parsing (STOCK_DAY)
- Stock list parsing (C_public.jsp)

All parsed data is validated for OHLC integrity before returning.
"""

import logging
import re
from datetime import datetime, date, time
from typing import List, Optional, Tuple

from src.models import (
    StockInfo,
    RealtimeQuote,
    DailyOHLC,
    IntradayTick,
    PriceDirection,
    PriceChange,
)
from src.exceptions import InvalidDataError, StockNotFoundError

logger = logging.getLogger("autofetchstock.fetcher")


class TWSEParser:
    """Parser for TWSE API responses."""

    @staticmethod
    def parse_realtime_quote(data: dict, stock_id: str) -> RealtimeQuote:
        """
        Parse real-time quote from TWSE getStockInfo.jsp response.

        Expected response format:
        {
            "msgArray": [{
                "n": "台積電",      # stock name
                "z": "985.00",     # latest price
                "o": "980.00",     # open price
                "h": "990.00",     # high price
                "l": "978.00",     # low price
                "y": "975.00",     # previous close
                "v": "25630",      # volume (lots)
                "t": "13:30:00"    # time
            }],
            "rtcode": "0000"
        }

        Args:
            data: Raw JSON response from TWSE API
            stock_id: Stock ID for error reporting

        Returns:
            RealtimeQuote instance

        Raises:
            InvalidDataError: If response format is invalid
            StockNotFoundError: If stock not found
        """
        # Check response status
        if data.get("rtcode") != "0000":
            raise InvalidDataError(
                message="API 回傳錯誤狀態",
                field="rtcode",
                value=data.get("rtcode")
            )

        msg_array = data.get("msgArray", [])
        if not msg_array:
            raise StockNotFoundError(stock_id=stock_id)

        quote_data = msg_array[0]

        try:
            # Parse prices (handle "-" for no data)
            current_price = TWSEParser._parse_price(quote_data.get("z", "-"))
            open_price = TWSEParser._parse_price(quote_data.get("o", "-"))
            high_price = TWSEParser._parse_price(quote_data.get("h", "-"))
            low_price = TWSEParser._parse_price(quote_data.get("l", "-"))
            previous_close = TWSEParser._parse_price(quote_data.get("y", "-"))

            # Parse best bid/ask (take first one if multiple separated by _)
            best_bid_str = quote_data.get("b", "-").split("_")[0]
            best_bid = TWSEParser._parse_price(best_bid_str)
            best_ask_str = quote_data.get("a", "-").split("_")[0]
            best_ask = TWSEParser._parse_price(best_ask_str)

            # Parse limit up and limit down prices
            limit_up_price = TWSEParser._parse_price(quote_data.get("u", "-")) or 0.0
            limit_down_price = TWSEParser._parse_price(quote_data.get("w", "-")) or 0.0

            # Improved Price Fallback Logic (REQ-040)
            if current_price is None:
                if open_price is None:
                    # Case 1: Market not yet opened or no trades today
                    # Use previous close as the current valuation
                    current_price = previous_close
                else:
                    # Case 2: Market is open but no trade in this specific poll
                    # Use best bid/ask as they are more current than yesterday's close
                    if best_bid:
                        current_price = best_bid
                    elif best_ask:
                        current_price = best_ask
                    else:
                        # Last resort: use the day's open/high/low if everything else is missing
                        current_price = open_price

            if current_price is None:
                raise InvalidDataError(
                    message="無法取得有效股價",
                    field="z",
                    value=quote_data.get("z")
                )

            # Calculate price change (Restored)
            if previous_close and previous_close > 0:
                price_change = PriceChange.calculate(current_price, previous_close)
            else:
                price_change = PriceChange(amount=0, percentage=0, direction=PriceDirection.FLAT)

            # Parse volumes (Restored)
            volume_str = quote_data.get("v", "0")
            volume = int(volume_str.replace(",", "")) if volume_str and volume_str != "-" else 0

            tick_volume_str = quote_data.get("tv", "0")
            tick_volume = int(tick_volume_str.replace(",", "")) if tick_volume_str and tick_volume_str != "-" else 0

            # Parse timestamp
            time_str = quote_data.get("t", "")
            timestamp = datetime.now()
            if time_str:
                try:
                    t = datetime.strptime(time_str, "%H:%M:%S").time()
                    timestamp = datetime.combine(date.today(), t)
                except ValueError:
                    pass

            return RealtimeQuote(
                stock_id=stock_id,
                stock_name=quote_data.get("n", ""),
                current_price=current_price,
                open_price=open_price,   # None when TWSE returns "-"; handled by data_processor
                high_price=high_price,   # None when TWSE returns "-"; handled by data_processor
                low_price=low_price,     # None when TWSE returns "-"; handled by data_processor
                previous_close=previous_close or current_price,
                change_amount=price_change.amount,
                change_percent=price_change.percentage,
                direction=price_change.direction,
                total_volume=volume,
                tick_volume=tick_volume,
                best_bid=best_bid or 0,
                best_ask=best_ask or 0,
                timestamp=timestamp,
                limit_up_price=limit_up_price,
                limit_down_price=limit_down_price,
            )

        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"Failed to parse realtime quote for {stock_id}: {e}")
            raise InvalidDataError(
                message="即時報價資料解析失敗",
                field="msgArray",
                value=str(e)
            )

    @staticmethod
    def parse_daily_history(data: dict, stock_id: str) -> List[DailyOHLC]:
        """
        Parse daily OHLC history from TWSE STOCK_DAY or TPEx history responses.
        """
        stat = data.get("stat")
        if stat and str(stat).lower() != "ok":
            if "查無資料" in str(stat) or "沒有符合條件的資料" in str(stat):
                logger.warning(f"No data available for {stock_id}")
                return []
            raise InvalidDataError(
                message="API 回傳錯誤狀態",
                field="stat",
                value=stat
            )

        is_otc_new = "tables" in data and isinstance(data.get("tables"), list)
        is_otc_legacy = "aaData" in data
        is_otc = is_otc_new or is_otc_legacy

        if is_otc_new:
            tables = data.get("tables", [])
            raw_data = tables[0].get("data", []) if tables else []
        else:
            raw_data = data.get("data", data.get("aaData", []))
        
        if not raw_data:
            logger.warning(f"Empty data array for {stock_id}")
            return []

        results = []
        for row in raw_data:
            try:
                if is_otc_new:
                    # New TPEx format: 日期, 成交張數, 成交仟元, 開盤, 最高, 最低, 收盤, 漲跌, 筆數
                    if len(row) < 7:
                        continue
                    date_str = row[0]
                    volume_lots = TWSEParser._parse_number(row[1])
                    turnover = TWSEParser._parse_number(row[2]) * 1000
                    open_price = TWSEParser._parse_price(row[3])
                    high_price = TWSEParser._parse_price(row[4])
                    low_price = TWSEParser._parse_price(row[5])
                    close_price = TWSEParser._parse_price(row[6])
                elif is_otc_legacy:
                    # Legacy TPEx format: Date, ID, Name, Close, Change, Open, High, Low, Volume, Turnover...
                    if len(row) < 10:
                        continue
                    date_str = row[0]
                    open_price = TWSEParser._parse_price(row[5])
                    high_price = TWSEParser._parse_price(row[6])
                    low_price = TWSEParser._parse_price(row[7])
                    close_price = TWSEParser._parse_price(row[3])
                    volume_shares = TWSEParser._parse_number(row[8])
                    turnover = TWSEParser._parse_number(row[9])
                    volume_lots = volume_shares // 1000 if volume_shares else 0
                else:
                    # TWSE format: 0:Date, 1:Volume, 2:Turnover, 3:Open, 4:High, 5:Low, 6:Close, 7:Change...
                    if len(row) < 7: continue
                    date_str = row[0]
                    volume_shares = TWSEParser._parse_number(row[1])
                    turnover = TWSEParser._parse_number(row[2])
                    open_price = TWSEParser._parse_price(row[3])
                    high_price = TWSEParser._parse_price(row[4])
                    low_price = TWSEParser._parse_price(row[5])
                    close_price = TWSEParser._parse_price(row[6])

                # Parse date (民國年 -> 西元年)
                parsed_date = TWSEParser._parse_roc_date(date_str)

                # Skip if any price is None
                if any(p is None for p in [open_price, high_price, low_price, close_price]):
                    logger.warning(f"Skipping row with invalid prices: {row}")
                    continue

                if not is_otc_new:
                    # TWSE and legacy TPEx report volume in shares.
                    volume_lots = volume_shares // 1000 if volume_shares else 0

                # Validate OHLC integrity
                if not TWSEParser._validate_ohlc(open_price, high_price, low_price, close_price, volume_lots):
                    logger.warning(f"OHLC validation failed for {date_str}: O={open_price}, H={high_price}, L={low_price}, C={close_price}")
                    continue

                ohlc = DailyOHLC(
                    date=parsed_date,
                    open=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                    volume=volume_lots,
                    turnover=turnover,
                    timestamp=datetime.now(),
                )
                results.append(ohlc)

            except Exception as e:
                logger.warning(f"Failed to parse row {row}: {e}")
                continue

        logger.info(f"Parsed {len(results)} daily records for {stock_id} (Market: {'OTC' if is_otc else 'TSE'})")
        return results

    @staticmethod
    def parse_stock_list(html_content: str, market: str = "tse") -> List[StockInfo]:
        """
        Parse stock list from TWSE C_public.jsp HTML response.

        The HTML contains a table with stock codes and names.
        Format: "代號　名稱" (e.g., "2330　台積電")

        Args:
            html_content: Raw HTML content from TWSE
            market: Market identifier ("tse" or "otc")

        Returns:
            List of StockInfo instances

        Raises:
            InvalidDataError: If HTML parsing fails
        """
        results = []

        try:
            # Pattern to match stock entries in the table
            # Format: stock_id + fullwidth space + name
            pattern = r'<td[^>]*>(\d{4,6})\u3000([^<]+)</td>'
            matches = re.findall(pattern, html_content)

            for stock_id, stock_name in matches:
                stock_name = stock_name.strip()
                if stock_name and not stock_name.startswith("上市認購"):
                    try:
                        stock_info = StockInfo(
                            stock_id=stock_id,
                            stock_name=stock_name,
                            market=market
                        )
                        results.append(stock_info)
                    except ValueError:
                        continue

            # Also try alternative pattern for different HTML formats
            if not results:
                # Alternative: look for rows with stock code pattern
                alt_pattern = r'>(\d{4})\s+([^<\s]+[^<]*)<'
                alt_matches = re.findall(alt_pattern, html_content)
                for stock_id, stock_name in alt_matches:
                    stock_name = stock_name.strip()
                    if stock_name and len(stock_id) == 4:
                        try:
                            stock_info = StockInfo(
                                stock_id=stock_id,
                                stock_name=stock_name,
                                market=market
                            )
                            results.append(stock_info)
                        except ValueError:
                            continue

            logger.info(f"Parsed {len(results)} stocks from {market} stock list")
            return results

        except Exception as e:
            logger.error(f"Failed to parse stock list HTML: {e}")
            raise InvalidDataError(
                message="股票清單解析失敗",
                field="html",
                value=str(e)
            )

    @staticmethod
    def parse_intraday_ticks(data: dict, stock_id: str, previous_close: float) -> List[IntradayTick]:
        """
        Parse intraday tick data from TWSE response.

        This is a placeholder for intraday tick parsing.
        The actual TWSE API for intraday data may require different handling.

        Args:
            data: Raw JSON response
            stock_id: Stock ID
            previous_close: Previous day's closing price

        Returns:
            List of IntradayTick instances
        """
        # Note: TWSE doesn't provide public tick-by-tick data easily
        # This would need to be implemented based on available data sources
        logger.warning(f"Intraday tick parsing not fully implemented for {stock_id}")
        return []

    @staticmethod
    def _parse_price(value: str) -> Optional[float]:
        """
        Parse price string to float.

        Args:
            value: Price string (may contain commas or be "-" for no data)

        Returns:
            Float value or None if invalid
        """
        if not value or value == "-" or value == "--":
            return None
        try:
            # Remove commas and convert to float
            cleaned = value.replace(",", "").strip()
            return float(cleaned)
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _parse_number(value: str) -> int:
        """
        Parse number string to int.

        Args:
            value: Number string (may contain commas)

        Returns:
            Integer value or 0 if invalid
        """
        if not value or value == "-":
            return 0
        try:
            cleaned = value.replace(",", "").strip()
            return int(cleaned)
        except (ValueError, AttributeError):
            return 0

    @staticmethod
    def _parse_roc_date(date_str: str) -> date:
        """
        Parse ROC (民國) date string to Python date.

        Args:
            date_str: Date in format "YYY/MM/DD" (民國年)

        Returns:
            Python date object

        Raises:
            ValueError: If date format is invalid
        """
        parts = date_str.split("/")
        if len(parts) != 3:
            raise ValueError(f"Invalid date format: {date_str}")

        roc_year = int(parts[0])
        month = int(parts[1])
        day = int(parts[2])

        # Convert ROC year to Western year (民國 + 1911 = 西元)
        western_year = roc_year + 1911

        return date(western_year, month, day)

    @staticmethod
    def _validate_ohlc(open_price: float, high: float, low: float, close: float, volume: int) -> bool:
        """
        Validate OHLC data integrity (REQ-083).

        Validation rules:
        - All prices must be positive
        - high >= max(open, close)
        - low <= min(open, close)
        - volume >= 0

        Args:
            open_price: Opening price
            high: High price
            low: Low price
            close: Closing price
            volume: Volume

        Returns:
            True if valid, False otherwise
        """
        # Check all prices are positive
        if any(p <= 0 for p in [open_price, high, low, close]):
            return False

        # Check high >= max(open, close)
        if high < max(open_price, close):
            return False

        # Check low <= min(open, close)
        if low > min(open_price, close):
            return False

        # Check volume is non-negative
        if volume < 0:
            return False

        return True

    @staticmethod
    def normalize_search_text(value: str) -> str:
        """Normalize stock search text for matching and ranking."""
        normalized = []
        for char in value or "":
            code = ord(char)
            if 0xFF01 <= code <= 0xFF5E:
                normalized.append(chr(code - 0xFEE0))
            elif code == 0x3000:
                normalized.append(" ")
            else:
                normalized.append(char)

        collapsed = "".join(normalized).strip().upper()
        # Ignore spacing and the trailing markers commonly seen in TWSE names,
        # e.g. "國巨*" should behave the same as "國巨" in search ranking.
        return re.sub(r"[\s*＊]+", "", collapsed)

    @staticmethod
    def _is_primary_stock(stock: StockInfo) -> bool:
        """Heuristically prefer plain stock/ETF codes over warrants."""
        return stock.stock_id.isdigit() and len(stock.stock_id) == 4

    @staticmethod
    def search_stocks(stock_list: List[StockInfo], keyword: str) -> List[StockInfo]:
        """
        Search stocks by keyword (ID or name).

        Args:
            stock_list: List of all stocks
            keyword: Search keyword

        Returns:
            List of matching StockInfo instances
        """
        keyword = TWSEParser.normalize_search_text(keyword)
        if not keyword:
            return []

        results = []

        for stock in stock_list:
            stock_id = TWSEParser.normalize_search_text(stock.stock_id)
            stock_name = TWSEParser.normalize_search_text(stock.stock_name)

            # Match by ID (exact or prefix)
            if stock_id.startswith(keyword):
                results.append(stock)
            # Match by name (contains)
            elif keyword in stock_name:
                results.append(stock)

        def sort_key(stock: StockInfo) -> tuple:
            stock_id = TWSEParser.normalize_search_text(stock.stock_id)
            stock_name = TWSEParser.normalize_search_text(stock.stock_name)
            name_index = stock_name.find(keyword)
            name_gap = abs(len(stock_name) - len(keyword))

            return (
                0 if stock_id == keyword else 1,
                0 if stock_name == keyword else 1,
                0 if stock_id.startswith(keyword) else 1,
                0 if stock_name.startswith(keyword) else 1,
                name_index if name_index >= 0 else 9999,
                name_gap,
                0 if TWSEParser._is_primary_stock(stock) else 1,
                len(stock.stock_id),
                stock.stock_id,
            )

        results.sort(key=sort_key)

        return results[:20]  # Limit results
