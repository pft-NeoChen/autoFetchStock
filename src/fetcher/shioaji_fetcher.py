"""
Shioaji (Sinopac) API fetcher implementation for real-time streaming data.
"""

import os
import threading
import time
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime

import shioaji as sj
from shioaji.constant import QuoteVersion

from src.config import AppConfig, get_logger
from src.models import RealtimeQuote, IntradayTick

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
        self._on_quote_callback: Optional[Callable[[RealtimeQuote], None]] = None
        self._on_tick_callback: Optional[Callable[[IntradayTick], None]] = None
        
        self._initialized = True
        logger.info(f"ShioajiFetcher initialized (Simulation: {self.config.shioaji_simulation})")

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
            
            logger.info(f"Unsubscribed from {stock_id}")

    def get_last_quote(self, stock_id: str) -> Optional[RealtimeQuote]:
        """Get the last received quote for a stock."""
        return self._last_quotes.get(stock_id)
        
    def is_subscribed(self, stock_id: str) -> bool:
        """Check if stock is currently subscribed."""
        return stock_id in self._subscriptions

    def _handle_quote(self, exchange, quote):
        """Callback handler for Shioaji Quote updates."""
        # logger.debug(f"Received quote for {quote.code}: simtrade={quote.simtrade}, price={quote.close}, vol_sum={getattr(quote, 'vol_sum', 'N/A')}")
        
        # filter out simtrade
        if quote.simtrade:
            return

        try:
            from src.models import PriceDirection, PriceChange

            stock_id = quote.code
            sub_info = self._subscriptions.get(stock_id, {})
            stock_name = sub_info.get("name", "")
            reference = sub_info.get("reference", 0)
            
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
                total_volume=int(quote.total_volume) if hasattr(quote, 'total_volume') else 0, # Reverted to total_volume based on log
                tick_volume=int(quote.volume) if hasattr(quote, 'volume') else 0,
                best_bid=float(quote.bid_price[0]) if hasattr(quote, 'bid_price') and quote.bid_price else 0.0,
                best_ask=float(quote.ask_price[0]) if hasattr(quote, 'ask_price') and quote.ask_price else 0.0,
                timestamp=datetime.now() # Use local time as quote.datetime might be offset
            )
            
            # Update cache
            self._last_quotes[stock_id] = rt_quote
            
            if self._on_quote_callback:
                self._on_quote_callback(rt_quote)
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
            # TickSTKv1 doesn't have bid/ask/total_volume
            # tick_type: 1=Buy, 2=Sell
            buy_vol = int(tick.volume) if tick.tick_type == 1 else 0
            sell_vol = int(tick.volume) if tick.tick_type == 2 else 0
            
            # if sell_vol > 0:
            #     logger.info(f"SELL DETECTED: {tick.code}, vol={sell_vol}")
            
            it_tick = IntradayTick(
                time=tick.datetime.time(),
                price=float(tick.close),
                volume=int(tick.volume),
                buy_volume=buy_vol,
                sell_volume=sell_vol,
                accumulated_volume=0, # Tick doesn't have accumulated volume
                timestamp=tick.datetime,
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