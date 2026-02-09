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
            
            # Note: Using attribute assignment instead of set_callback based on testing
            self.api.on_quote_stkv1_callback = self._handle_quote
            self.api.on_tick_stkv1_callback = self._handle_tick
            
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
            logger.info(f"Unsubscribed from {stock_id}")

    def _handle_quote(self, exchange, quote):
        """Callback handler for Shioaji Quote updates."""
        try:
            sub_info = self._subscriptions.get(quote.code, {})
            rt_quote = RealtimeQuote(
                stock_id=quote.code,
                name=sub_info.get("name", ""),
                current_price=float(quote.close),
                change=float(quote.diff),
                change_percent=float(quote.diff_rate),
                volume=int(quote.vol_sum),
                timestamp=datetime.now()
            )
            if self._on_quote_callback:
                self._on_quote_callback(rt_quote)
        except Exception as e:
            logger.error(f"Error handling shioaji quote: {str(e)}")

    def _handle_tick(self, exchange, tick):
        """Callback handler for Shioaji Tick updates."""
        # filter out simtrade (trial trades before market open/during pauses)
        if tick.simtrade:
            return

        try:
            sub_info = self._subscriptions.get(tick.code, {})
            # Convert Shioaji Tick to IntradayTick
            it_tick = IntradayTick(
                stock_id=tick.code,
                price=float(tick.close),
                volume=int(tick.volume),
                timestamp=datetime.fromtimestamp(tick.datetime.timestamp()),
                bid_price=float(tick.bid_price[0]) if tick.bid_price else 0.0,
                ask_price=float(tick.ask_price[0]) if tick.ask_price else 0.0,
                tick_type="buy" if tick.tick_type == 1 else "sell" if tick.tick_type == 2 else "neutral"
            )
            
            # Attach metadata for storage use
            # Use dictionary if it_tick doesn't support setattr on all fields
            # or just rely on AppController to extract it.
            # Here we use it as a custom property on the object.
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