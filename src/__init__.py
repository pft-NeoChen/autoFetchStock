"""
autoFetchStock - Taiwan Stock Data Fetching and Visualization System.

This package provides:
- TWSE API data fetching
- Local JSON storage
- Data processing and calculations
- Plotly chart rendering
- Automatic data fetching scheduling
- Dash web interface
"""

__version__ = "0.1.0"
__author__ = "autoFetchStock Team"

# Main components
from src.config import AppConfig, setup_logging
from src.models import (
    StockInfo,
    RealtimeQuote,
    DailyOHLC,
    IntradayTick,
    PriceChange,
    PriceDirection,
    KlinePeriod,
    SchedulerStatus,
)
from src.exceptions import (
    AutoFetchStockError,
    ConnectionTimeoutError,
    InvalidDataError,
    StockNotFoundError,
    DataCorruptedError,
    ServiceUnavailableError,
    DiskSpaceError,
    SchedulerTaskError,
)

__all__ = [
    # Version
    "__version__",
    # Config
    "AppConfig",
    "setup_logging",
    # Models
    "StockInfo",
    "RealtimeQuote",
    "DailyOHLC",
    "IntradayTick",
    "PriceChange",
    "PriceDirection",
    "KlinePeriod",
    "SchedulerStatus",
    # Exceptions
    "AutoFetchStockError",
    "ConnectionTimeoutError",
    "InvalidDataError",
    "StockNotFoundError",
    "DataCorruptedError",
    "ServiceUnavailableError",
    "DiskSpaceError",
    "SchedulerTaskError",
]
