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
                open_price=open_price or current_price,
                high_price=high_price or current_price,
                low_price=low_price or current_price,
                previous_close=previous_close or current_price,
                change_amount=price_change.amount,
                change_percent=price_change.percentage,
                direction=price_change.direction,
                total_volume=volume,
                tick_volume=tick_volume,
                best_bid=best_bid or 0,
                best_ask=best_ask or 0,
                timestamp=timestamp,
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
        Parse daily OHLC history from TWSE STOCK_DAY or TPEx stk_quote_result response.
        """
        # TWSE uses 'stat', TPEx doesn't always use it or uses it differently
        stat = data.get("stat")
        if stat and stat != "OK":
            if "查無資料" in str(stat) or "沒有符合條件的資料" in str(stat):
                logger.warning(f"No data available for {stock_id}")
                return []
            raise InvalidDataError(
                message="API 回傳錯誤狀態",
                field="stat",
                value=stat
            )

        # TWSE uses 'data', TPEx uses 'aaData'
        # Detect market based on key
        is_otc = "aaData" in data
        raw_data = data.get("data", data.get("aaData", []))
        
        if not raw_data:
            logger.warning(f"Empty data array for {stock_id}")
            return []

        results = []
        for row in raw_data:
            try:
                if is_otc:
                    # OTC (TPEx) format: 0:Date, 1:ID, 2:Name, 3:Close, 4:Change, 5:Open, 6:High, 7:Low, 8:Volume...
                    if len(row) < 8: continue
                    date_str = row[0]
                    open_price = TWSEParser._parse_price(row[5])
                    high_price = TWSEParser._parse_price(row[6])
                    low_price = TWSEParser._parse_price(row[7])
                    close_price = TWSEParser._parse_price(row[3])
                    volume_shares = TWSEParser._parse_number(row[8])
                    turnover = TWSEParser._parse_number(row[9])
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

                # Convert volume from shares to lots (1 lot = 1000 shares)
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
    def search_stocks(stock_list: List[StockInfo], keyword: str) -> List[StockInfo]:
        """
        Search stocks by keyword (ID or name).

        Args:
            stock_list: List of all stocks
            keyword: Search keyword

        Returns:
            List of matching StockInfo instances
        """
        # Normalize full-width characters to half-width
        normalized_keyword = ""
        for char in keyword:
            code = ord(char)
            if 0xFF01 <= code <= 0xFF5E:
                normalized_keyword += chr(code - 0xFEE0)
            elif code == 0x3000:
                normalized_keyword += chr(0x0020)
            else:
                normalized_keyword += char
        
        keyword = normalized_keyword.strip().upper()
        results = []

        for stock in stock_list:
            # Match by ID (exact or prefix)
            if stock.stock_id.upper().startswith(keyword):
                results.append(stock)
            # Match by name (contains)
            elif keyword.lower() in stock.stock_name.lower():
                results.append(stock)

        # Sort: exact ID match first, then by ID
        results.sort(key=lambda s: (
            0 if s.stock_id.upper() == keyword else 1,
            s.stock_id
        ))

        return results[:20]  # Limit results
