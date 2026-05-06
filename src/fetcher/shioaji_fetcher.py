"""
Shioaji (Sinopac) API fetcher implementation for real-time streaming data.
"""

import os
import threading
import time
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime, timedelta

import shioaji as sj
from shioaji.constant import QuoteVersion

from src.config import AppConfig, get_logger
from src.models import RealtimeQuote, IntradayTick, DailyOHLC, PriceDirection

logger = get_logger("autofetchstock.fetcher")

class ShioajiFetcher:
    """
    Singleton fetcher for Shioaji API.
    Handles connection, streaming subscriptions, and data conversion.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ShioajiFetcher, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, config: Optional[AppConfig] = None):
        if self._initialized:
            return
        
        self.config = config or AppConfig()
        self.api = sj.Shioaji(simulation=self.config.shioaji_simulation)
        self.is_connected = False
        self._subscriptions: Dict[str, Any] = {}
        self._last_quotes: Dict[str, RealtimeQuote] = {}  # Cache for latest quotes
        self._last_bidask: Dict[str, dict] = {}  # Cache for latest bid/ask five-level data
        self._on_quote_callback: Optional[Callable[[RealtimeQuote], None]] = None
        self._on_tick_callback: Optional[Callable[[IntradayTick], None]] = None
        
        self._initialized = True
        logger.info(f"ShioajiFetcher initialized (Simulation: {self.config.shioaji_simulation})")

    @staticmethod
    def _normalize_datetime(value: Any) -> Optional[datetime]:
        """Normalize Shioaji timestamp fields to local naive datetimes."""
        if value is None:
            return None

        parsed = None

        if isinstance(value, datetime):
            if value.tzinfo is not None:
                parsed = value.astimezone().replace(tzinfo=None)
            else:
                parsed = value
        elif isinstance(value, (int, float)):
            if value > 0:
                # Shioaji snapshot ts is commonly epoch nanoseconds.
                seconds = value / 1_000_000_000 if value > 10_000_000_000 else value
                try:
                    parsed = datetime.fromtimestamp(seconds)
                except (OSError, OverflowError, ValueError):
                    pass
        elif isinstance(value, str) and value:
            try:
                parsed_str = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed_str.tzinfo is not None:
                    parsed = parsed_str.astimezone().replace(tzinfo=None)
                else:
                    parsed = parsed_str
            except ValueError:
                pass

        if parsed is not None:
            # TODO(phase 7.1): Replace hour-band heuristic with zoneinfo-based
            # fix at source. Current band masks symptom (22:30 / 06:30 ticks)
            # but will misfire on legit after-hours sessions (盤後定盤 14:30+,
            # 早盤試撮 08:00–09:00). See IMPLEMENTATION_PLAN.md Phase 7.1.
            if parsed.hour >= 15:
                parsed -= timedelta(hours=8)
            elif parsed.hour < 8:
                parsed += timedelta(hours=8)
            return parsed

        return None

    @classmethod
    def _extract_source_datetime(cls, obj: Any) -> datetime:
        """Extract the transaction/source time from Shioaji objects."""
        for attr in ("datetime", "ts", "timestamp"):
            parsed = cls._normalize_datetime(getattr(obj, attr, None))
            if parsed is not None:
                return parsed
        return datetime.now()

    def login(self) -> bool:
        """Log in to Shioaji API and activate CA."""
        try:
            api_key, secret_key = self.config.get_shioaji_credentials()
            if not api_key or not secret_key:
                logger.error("Shioaji API keys not configured for current mode.")
                return False

            accounts = self.api.login(api_key, secret_key)
            logger.info(f"Shioaji login successful ({'Simulation' if self.config.shioaji_simulation else 'Production'}). Accounts: {len(accounts)}")

            # Activate CA if configured
            if self.config.shioaji_cert_path and os.path.exists(self.config.shioaji_cert_path):
                self.api.activate_ca(
                    self.config.shioaji_cert_path,
                    self.config.shioaji_cert_password,
                    self.config.shioaji_person_id
                )
                logger.info("Shioaji CA activated.")
            
            # Note: Using set_on_quote_stk_v1_callback explicitly
            logger.info("Setting Shioaji callbacks...")
            self.api.quote.set_on_quote_stk_v1_callback(self._handle_quote)
            self.api.quote.set_on_tick_stk_v1_callback(self._handle_tick)
            
            self.is_connected = True
            return True
        except Exception as e:
            logger.error(f"Shioaji login failed: {str(e)}")
            self.is_connected = False
            return False

    def logout(self):
        """Log out from Shioaji API."""
        if self.is_connected:
            self.api.logout()
            self.is_connected = False
            logger.info("Shioaji logged out.")

    def subscribe(self, stock_id: str):
        """Subscribe to real-time quotes and ticks for a stock."""
        if not self.is_connected:
            logger.warning(f"Cannot subscribe to {stock_id}: Not connected.")
            return

        try:
            contract = self.api.Contracts.Stocks[stock_id]
            if not contract:
                logger.error(f"Stock contract not found: {stock_id}")
                return

            # Store metadata for callback use
            self._subscriptions[stock_id] = {
                "contract": contract,
                "name": contract.name,
                "reference": getattr(contract, "reference", 0)
            }
            
            # Subscribe to Quote and Tick
            logger.info(f"Subscribing to {stock_id} ({contract.name})...")
            self.api.quote.subscribe(contract, quote_type=sj.constant.QuoteType.Quote, version=QuoteVersion.v1)
            self.api.quote.subscribe(contract, quote_type=sj.constant.QuoteType.Tick, version=QuoteVersion.v1)
            
            logger.info(f"Subscribed to Shioaji streaming for {stock_id} ({contract.name})")
        except Exception as e:
            logger.error(f"Error subscribing to {stock_id}: {str(e)}")

    def unsubscribe(self, stock_id: str):
        """Unsubscribe from a stock."""
        if stock_id in self._subscriptions:
            sub_info = self._subscriptions.pop(stock_id)
            contract = sub_info["contract"]
            self.api.quote.unsubscribe(contract, quote_type=sj.constant.QuoteType.Quote)
            self.api.quote.unsubscribe(contract, quote_type=sj.constant.QuoteType.Tick)
            
            # Remove from cache
            self._last_quotes.pop(stock_id, None)
            self._last_bidask.pop(stock_id, None)
            
            logger.info(f"Unsubscribed from {stock_id}")

    def get_last_quote(self, stock_id: str) -> Optional[RealtimeQuote]:
        """Get the last received quote for a stock."""
        return self._last_quotes.get(stock_id)

    def get_last_bidask(self, stock_id: str) -> Optional[dict]:
        """Get the last received bid/ask five-level data for a stock."""
        return self._last_bidask.get(stock_id)
        
    def is_subscribed(self, stock_id: str) -> bool:
        """Check if stock is currently subscribed."""
        return stock_id in self._subscriptions

    def fetch_quote(self, stock_id: str) -> Optional[RealtimeQuote]:
        """
        Fetch a single snapshot quote for a stock using Shioaji API.
        Useful for filling gaps when streaming hasn't provided data yet.
        """
        if not self.is_connected:
            return None

        try:
            contract = self.api.Contracts.Stocks[stock_id]
            if not contract:
                return None
                
            snapshots = self.api.snapshots([contract])
            if not snapshots:
                return None
                
            snapshot = snapshots[0]
            
            # Convert Snapshot to RealtimeQuote (similar logic to _handle_quote)
            reference = getattr(contract, "reference", 0)
            current_price = float(snapshot.close)
            
            # Calculate change
            if reference > 0:
                change = current_price - reference
                change_percent = (change / reference) * 100
                if change > 0:
                    direction = PriceDirection.UP
                elif change < 0:
                    direction = PriceDirection.DOWN
                else:
                    direction = PriceDirection.FLAT
            else:
                change = 0.0
                change_percent = 0.0
                direction = PriceDirection.FLAT

            # Robust attribute access for Shioaji Snapshot object
            total_vol = int(getattr(snapshot, 'total_volume', getattr(snapshot, 'vol_sum', 0)))
            tick_vol = int(getattr(snapshot, 'volume', 0))
            bid_price = float(getattr(snapshot, 'bid_price', 0.0)) if getattr(snapshot, 'bid_price', None) else 0.0
            ask_price = float(getattr(snapshot, 'ask_price', 0.0)) if getattr(snapshot, 'ask_price', None) else 0.0
            
            timestamp = self._extract_source_datetime(snapshot)

            # Construct quote object
            rt_quote = RealtimeQuote(
                stock_id=stock_id,
                stock_name=contract.name,
                current_price=current_price,
                open_price=float(snapshot.open),
                high_price=float(snapshot.high),
                low_price=float(snapshot.low),
                previous_close=reference,
                change_amount=change,
                change_percent=change_percent,
                direction=direction,
                total_volume=total_vol,
                tick_volume=tick_vol,
                best_bid=bid_price,
                best_ask=ask_price,
                timestamp=timestamp,
                limit_up_price=float(getattr(contract, 'limit_up', 0)),
                limit_down_price=float(getattr(contract, 'limit_down', 0)),
                is_simtrade=bool(getattr(snapshot, "simtrade", False)),
            )
            
            # Update internal cache too
            self._last_quotes[stock_id] = rt_quote
            
            return rt_quote

        except Exception as e:
            logger.error(f"Error fetching snapshot for {stock_id}: {e}")
            return None

    def fetch_daily_history(self, stock_id: str, year: int, month: int) -> List[DailyOHLC]:
        """
        Fetch historical daily OHLC data using Shioaji kbars.
        Automatically resamples 1-minute kbars into daily data.
        """
        if not self.is_connected:
            return []

        try:
            contract = self.api.Contracts.Stocks[stock_id]
            if not contract:
                logger.error(f"Stock contract not found: {stock_id}")
                return []

            # Calculate start and end dates for the given month
            from datetime import date
            import calendar
            import pandas as pd
            from src.models import DailyOHLC
            
            start_date = date(year, month, 1)
            last_day = calendar.monthrange(year, month)[1]
            end_date = date(year, month, last_day)

            # Shioaji expects string format YYYY-MM-DD
            start_str = start_date.strftime("%Y-%m-%d")
            end_str = end_date.strftime("%Y-%m-%d")

            logger.info(f"Fetching Shioaji kbars for {stock_id} from {start_str} to {end_str}...")
            kbars = self.api.kbars(contract, start=start_str, end=end_str)
            
            if not kbars or not hasattr(kbars, 'ts') or not kbars.ts:
                return []

            # Convert to DataFrame
            df = pd.DataFrame({**kbars})
            df['ts'] = pd.to_datetime(df['ts'])
            df.set_index('ts', inplace=True)
            
            # Resample to daily OHLC
            daily_df = df.resample('D').agg({
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum',
                'Amount': 'sum'
            }).dropna()

            # Convert to List[DailyOHLC]
            records = []
            for d, row in daily_df.iterrows():
                # Volume from kbars is already in lots for Taiwan stocks
                vol_lots = int(row['Volume'])
                
                records.append(DailyOHLC(
                    date=d.date(),
                    open=float(row['Open']),
                    high=float(row['High']),
                    low=float(row['Low']),
                    close=float(row['Close']),
                    volume=vol_lots,
                    turnover=float(row['Amount']),
                    timestamp=datetime.now()
                ))
                
            return records

        except Exception as e:
            logger.error(f"Failed to fetch Shioaji daily history for {stock_id}: {e}")
            return []

    def _handle_quote(self, exchange, quote):
        """Callback handler for Shioaji Quote updates."""
        try:
            stock_id = quote.code
            vol_sum = int(getattr(quote, 'total_volume', getattr(quote, 'vol_sum', 0)))
            logger.debug(f"[Shioaji] Quote for {stock_id}: vol={vol_sum}, price={quote.close}")
            
            sub_info = self._subscriptions.get(stock_id, {})
            stock_name = sub_info.get("name", "")
            reference = sub_info.get("reference", 0)
            contract = sub_info.get("contract")
            limit_up = float(getattr(contract, "limit_up", 0)) if contract else 0.0
            limit_down = float(getattr(contract, "limit_down", 0)) if contract else 0.0
            
            current_price = float(quote.close)
            
            # Calculate change and direction
            if reference > 0:
                change = current_price - reference
                change_percent = (change / reference) * 100
                if change > 0:
                    direction = PriceDirection.UP
                elif change < 0:
                    direction = PriceDirection.DOWN
                else:
                    direction = PriceDirection.FLAT
            else:
                change = 0.0
                change_percent = 0.0
                direction = PriceDirection.FLAT
            
            # Shioaji quote object fields mapping
            rt_quote = RealtimeQuote(
                stock_id=stock_id,
                stock_name=stock_name,
                current_price=current_price,
                open_price=float(quote.open) if hasattr(quote, 'open') else current_price,
                high_price=float(quote.high) if hasattr(quote, 'high') else current_price,
                low_price=float(quote.low) if hasattr(quote, 'low') else current_price,
                previous_close=reference,
                change_amount=change,
                change_percent=change_percent,
                direction=direction,
                total_volume=int(getattr(quote, 'total_volume', getattr(quote, 'vol_sum', 0))),
                tick_volume=int(quote.volume) if hasattr(quote, 'volume') else 0,
                best_bid=float(quote.bid_price[0]) if hasattr(quote, 'bid_price') and quote.bid_price else 0.0,
                best_ask=float(quote.ask_price[0]) if hasattr(quote, 'ask_price') and quote.ask_price else 0.0,
                timestamp=self._extract_source_datetime(quote),
                limit_up_price=limit_up,
                limit_down_price=limit_down,
                is_simtrade=bool(getattr(quote, "simtrade", False)),
            )
            
            # Update cache
            self._last_quotes[stock_id] = rt_quote

            # Extract and cache five-level bid/ask data
            try:
                bid_prices = [float(p) for p in quote.bid_price] if hasattr(quote, 'bid_price') and quote.bid_price else []
                bid_volumes = [int(v) for v in quote.bid_volume] if hasattr(quote, 'bid_volume') and quote.bid_volume else []
                ask_prices = [float(p) for p in quote.ask_price] if hasattr(quote, 'ask_price') and quote.ask_price else []
                ask_volumes = [int(v) for v in quote.ask_volume] if hasattr(quote, 'ask_volume') and quote.ask_volume else []

                if bid_prices and ask_prices:
                    self._last_bidask[stock_id] = {
                        "bid_price": bid_prices,
                        "bid_volume": bid_volumes,
                        "ask_price": ask_prices,
                        "ask_volume": ask_volumes,
                        "bid_side_total_vol": int(quote.bid_side_total_vol) if hasattr(quote, 'bid_side_total_vol') else 0,
                        "ask_side_total_vol": int(quote.ask_side_total_vol) if hasattr(quote, 'ask_side_total_vol') else 0,
                    }
            except Exception as e:
                logger.debug(f"Failed to extract bidask data: {e}")

            if self._on_quote_callback:
                logger.debug(f"Invoking quote callback for {stock_id}")
                self._on_quote_callback(rt_quote)
            else:
                logger.warning(f"No quote callback set for {stock_id}")
                
        except Exception as e:
            logger.error(f"Error handling shioaji quote: {str(e)}")

    def _handle_tick(self, exchange, tick):
        """Callback handler for Shioaji Tick updates."""
        # logger.info(f"Raw Tick: code={tick.code}, type={tick.tick_type}, vol={tick.volume}, odd={tick.intraday_odd}")
        
        # filter out simtrade (trial trades before market open/during pauses)
        if tick.simtrade:
            return

        try:
            sub_info = self._subscriptions.get(tick.code, {})
            # Convert Shioaji Tick to IntradayTick
            # tick_type: 1=Buy, 2=Sell
            buy_vol = int(tick.volume) if tick.tick_type == 1 else 0
            sell_vol = int(tick.volume) if tick.tick_type == 2 else 0
            accumulated_volume = int(getattr(tick, "total_volume", 0) or 0)
            
            # Normalize datetime to fix timezone shift bug
            corrected_dt = self._normalize_datetime(tick.datetime) or tick.datetime
            
            it_tick = IntradayTick(
                time=corrected_dt.time(),
                price=float(tick.close),
                volume=int(tick.volume),
                buy_volume=buy_vol,
                sell_volume=sell_vol,
                accumulated_volume=accumulated_volume,
                timestamp=corrected_dt,
                is_odd=getattr(tick, 'intraday_odd', False)
            )
            
            # Attach metadata for storage use (AppController expects these)
            it_tick.stock_id = tick.code
            it_tick.stock_name = sub_info.get("name", "")
            it_tick.reference = sub_info.get("reference", 0)

            if self._on_tick_callback:
                self._on_tick_callback(it_tick)
        except Exception as e:
            logger.error(f"Error handling shioaji tick: {str(e)}")

    def set_callbacks(self, on_quote: Optional[Callable] = None, on_tick: Optional[Callable] = None):
        """Set external callbacks for data processing."""
        self._on_quote_callback = on_quote
        self._on_tick_callback = on_tick
