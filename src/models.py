"""
Data models for autoFetchStock.

This module defines all dataclasses and enums used throughout the application:
- PriceDirection: Enum for price movement direction
- KlinePeriod: Enum for K-line time periods
- StockInfo: Basic stock information
- RealtimeQuote: Real-time price quote
- DailyOHLC: Daily OHLC data
- IntradayTick: Intraday tick data
- PriceChange: Price change calculation result
- SchedulerStatus: Scheduler status information
"""

from dataclasses import dataclass, field
from datetime import datetime, date, time
from enum import Enum
from typing import List, Optional


class PriceDirection(Enum):
    """Stock price movement direction."""
    UP = "up"
    DOWN = "down"
    FLAT = "flat"


class KlinePeriod(Enum):
    """K-line time period options."""
    DAILY = "daily"      # 日 K
    WEEKLY = "weekly"    # 週 K
    MONTHLY = "monthly"  # 月 K
    MIN_1 = "1min"       # 1 分 K
    MIN_5 = "5min"       # 5 分 K
    MIN_15 = "15min"     # 15 分 K
    MIN_30 = "30min"     # 30 分 K
    MIN_60 = "60min"     # 60 分 K

    @property
    def display_name(self) -> str:
        """Get display name in Chinese."""
        names = {
            KlinePeriod.DAILY: "日K",
            KlinePeriod.WEEKLY: "週K",
            KlinePeriod.MONTHLY: "月K",
            KlinePeriod.MIN_1: "1分K",
            KlinePeriod.MIN_5: "5分K",
            KlinePeriod.MIN_15: "15分K",
            KlinePeriod.MIN_30: "30分K",
            KlinePeriod.MIN_60: "60分K",
        }
        return names.get(self, self.value)

    @property
    def minutes(self) -> Optional[int]:
        """Get minutes for minute-based periods, None for day/week/month."""
        minute_map = {
            KlinePeriod.MIN_1: 1,
            KlinePeriod.MIN_5: 5,
            KlinePeriod.MIN_15: 15,
            KlinePeriod.MIN_30: 30,
            KlinePeriod.MIN_60: 60,
        }
        return minute_map.get(self)

    @property
    def pandas_resample_rule(self) -> Optional[str]:
        """Get pandas resample rule for week/month periods."""
        resample_map = {
            KlinePeriod.WEEKLY: "W",
            KlinePeriod.MONTHLY: "ME",  # Month End
        }
        return resample_map.get(self)


@dataclass
class StockInfo:
    """Basic stock information."""
    stock_id: str          # Stock code (e.g., "2330")
    stock_name: str        # Stock name (e.g., "台積電")
    market: str = "tse"    # Market: tse (listed) or otc (OTC)

    def __post_init__(self):
        """Validate stock_id format."""
        if not self.stock_id:
            raise ValueError("stock_id cannot be empty")
        # Allow alphanumeric stock IDs (1-6 characters)
        if not self.stock_id.isalnum() or len(self.stock_id) > 6:
            raise ValueError(f"Invalid stock_id format: {self.stock_id}")


@dataclass
class RealtimeQuote:
    """Real-time stock quote data."""
    stock_id: str
    stock_name: str
    current_price: float       # Latest transaction price
    open_price: float          # Opening price
    high_price: float          # Day's high
    low_price: float           # Day's low
    previous_close: float      # Previous day's close
    change_amount: float       # Price change amount
    change_percent: float      # Price change percentage
    direction: PriceDirection  # Price direction
    total_volume: int          # Total volume (in lots/張)
    tick_volume: int           # Latest tick volume (in lots/張)
    best_bid: float            # Best bid price
    best_ask: float            # Best ask price
    timestamp: datetime        # Data timestamp

    def __post_init__(self):
        """Validate quote data."""
        if self.current_price < 0:
            raise ValueError("current_price must be non-negative")
        if self.total_volume < 0:
            raise ValueError("total_volume must be non-negative")


@dataclass
class DailyOHLC:
    """Daily OHLC (Open-High-Low-Close) data."""
    date: date               # Trading date
    open: float              # Opening price
    high: float              # Day's high
    low: float               # Day's low
    close: float             # Closing price
    volume: int              # Volume (in lots/張)
    turnover: int            # Turnover (in TWD)
    timestamp: datetime = field(default_factory=datetime.now)  # Record timestamp

    def __post_init__(self):
        """Validate OHLC data integrity."""
        # Validate prices are positive
        if any(p <= 0 for p in [self.open, self.high, self.low, self.close]):
            raise ValueError("All prices must be positive")

        # Validate high >= max(open, close)
        if self.high < max(self.open, self.close):
            raise ValueError(f"high ({self.high}) must be >= max(open, close) ({max(self.open, self.close)})")

        # Validate low <= min(open, close)
        if self.low > min(self.open, self.close):
            raise ValueError(f"low ({self.low}) must be <= min(open, close) ({min(self.open, self.close)})")

        # Validate volume is non-negative
        if self.volume < 0:
            raise ValueError("volume must be non-negative")

        # Validate turnover is non-negative
        if self.turnover < 0:
            raise ValueError("turnover must be non-negative")

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "date": self.date.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "turnover": self.turnover,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DailyOHLC":
        """Create instance from dictionary."""
        return cls(
            date=date.fromisoformat(data["date"]),
            open=float(data["open"]),
            high=float(data["high"]),
            low=float(data["low"]),
            close=float(data["close"]),
            volume=int(data["volume"]),
            turnover=int(data["turnover"]),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now(),
        )


@dataclass
class IntradayTick:
    """Intraday tick data for time-series chart."""
    time: time                  # Transaction time
    price: float                # Transaction price
    volume: int                 # Transaction volume (in lots/張)
    buy_volume: float           # Buy volume (positive, upward)
    sell_volume: float          # Sell volume (positive, shown downward as negative)
    accumulated_volume: int     # Accumulated volume for the day
    timestamp: datetime = field(default_factory=datetime.now)  # Record timestamp
    is_odd: bool = False        # Whether this is an odd lot trade (volume in shares)

    def __post_init__(self):
        """Validate tick data."""
        if self.price <= 0:
            raise ValueError("price must be positive")
        if self.volume < 0:
            raise ValueError("volume must be non-negative")
        if self.buy_volume < 0:
            raise ValueError("buy_volume must be non-negative")
        if self.sell_volume < 0:
            raise ValueError("sell_volume must be non-negative")
        if self.accumulated_volume < 0:
            raise ValueError("accumulated_volume must be non-negative")

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "time": self.time.isoformat(),
            "price": self.price,
            "volume": self.volume,
            "buy_volume": self.buy_volume,
            "sell_volume": self.sell_volume,
            "accumulated_volume": self.accumulated_volume,
            "timestamp": self.timestamp.isoformat(),
            "is_odd": self.is_odd,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "IntradayTick":
        """Create instance from dictionary."""
        return cls(
            time=time.fromisoformat(data["time"]),
            price=float(data["price"]),
            volume=int(data["volume"]),
            buy_volume=float(data["buy_volume"]),
            sell_volume=float(data["sell_volume"]),
            accumulated_volume=int(data["accumulated_volume"]),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now(),
            is_odd=data.get("is_odd", False),
        )


@dataclass
class PriceChange:
    """Price change calculation result."""
    amount: float              # Change amount (current - previous)
    percentage: float          # Change percentage
    direction: PriceDirection  # Price direction

    @classmethod
    def calculate(cls, current_price: float, previous_close: float) -> "PriceChange":
        """
        Calculate price change from current price and previous close.

        Args:
            current_price: Current/latest price
            previous_close: Previous day's closing price

        Returns:
            PriceChange instance with calculated values
        """
        if previous_close == 0:
            raise ValueError("previous_close cannot be zero")

        amount = current_price - previous_close
        percentage = round((amount / previous_close) * 100, 2)

        if amount > 0:
            direction = PriceDirection.UP
        elif amount < 0:
            direction = PriceDirection.DOWN
        else:
            direction = PriceDirection.FLAT

        return cls(amount=amount, percentage=percentage, direction=direction)


@dataclass
class SchedulerStatus:
    """Scheduler status information."""
    is_running: bool                      # Whether scheduler is running
    is_market_open: bool                  # Whether market is currently open
    is_paused: bool                       # Whether auto-fetch is paused due to errors
    active_jobs: List[str]                # List of active stock IDs being fetched
    last_fetch_time: Optional[datetime]   # Last successful fetch time
    consecutive_failures: int             # Number of consecutive failures

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "is_running": self.is_running,
            "is_market_open": self.is_market_open,
            "is_paused": self.is_paused,
            "active_jobs": self.active_jobs,
            "last_fetch_time": self.last_fetch_time.isoformat() if self.last_fetch_time else None,
            "consecutive_failures": self.consecutive_failures,
        }


@dataclass
class StockDailyFile:
    """Structure for stock daily data JSON file."""
    stock_id: str
    stock_name: str
    last_updated: datetime
    daily_data: List[DailyOHLC] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "stock_id": self.stock_id,
            "stock_name": self.stock_name,
            "last_updated": self.last_updated.isoformat(),
            "daily_data": [d.to_dict() for d in self.daily_data],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StockDailyFile":
        """Create instance from dictionary."""
        return cls(
            stock_id=data["stock_id"],
            stock_name=data["stock_name"],
            last_updated=datetime.fromisoformat(data["last_updated"]),
            daily_data=[DailyOHLC.from_dict(d) for d in data.get("daily_data", [])],
        )


@dataclass
class StockIntradayFile:
    """Structure for stock intraday data JSON file."""
    stock_id: str
    stock_name: str
    date: date
    previous_close: float
    ticks: List[IntradayTick] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "stock_id": self.stock_id,
            "stock_name": self.stock_name,
            "date": self.date.isoformat(),
            "previous_close": self.previous_close,
            "ticks": [t.to_dict() for t in self.ticks],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StockIntradayFile":
        """Create instance from dictionary."""
        return cls(
            stock_id=data["stock_id"],
            stock_name=data["stock_name"],
            date=date.fromisoformat(data["date"]),
            previous_close=float(data["previous_close"]),
            ticks=[IntradayTick.from_dict(t) for t in data.get("ticks", [])],
        )


@dataclass
class PriceExtremes:
    """Price extremes within a visible range."""
    highest_price: float
    highest_date: date
    lowest_price: float
    lowest_date: date

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "highest": {
                "price": self.highest_price,
                "date": self.highest_date.isoformat(),
            },
            "lowest": {
                "price": self.lowest_price,
                "date": self.lowest_date.isoformat(),
            },
        }
