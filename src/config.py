"""
Application configuration and constants for autoFetchStock.

This module defines:
- AppConfig: Application configuration dataclass
- LOGGING_CONFIG: Logging configuration dictionary
- setup_logging(): Function to initialize the logging system
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import logging.config
import os


@dataclass
class AppConfig:
    """Application configuration settings."""

    # Server settings
    host: str = "127.0.0.1"
    port: int = 8050
    debug: bool = False

    # Data directories
    data_dir: str = "data"

    # Fetch settings
    fetch_interval: int = 5  # seconds between fetches
    request_timeout: int = 10  # HTTP request timeout in seconds
    request_interval: float = 3.0  # minimum interval between API requests
    max_consecutive_failures: int = 3  # failures before pausing auto-fetch

    # Market hours (Taiwan Stock Exchange)
    market_open_hour: int = 9
    market_open_minute: int = 0
    market_close_hour: int = 13
    market_close_minute: int = 30
    timezone: str = "Asia/Taipei"

    # Logging settings
    log_level: str = "INFO"
    log_file: str = "logs/app.log"

    # Cache settings
    cache_max_stocks: int = 20  # max stocks in LRU cache
    stock_list_cache_hours: int = 24  # stock list cache validity

    # Storage settings
    min_disk_space_mb: int = 100  # minimum free disk space in MB

    def __post_init__(self):
        """Ensure directories exist after initialization."""
        # Create data directories
        data_path = Path(self.data_dir)
        for subdir in ["stocks", "intraday", "cache", "backup"]:
            (data_path / subdir).mkdir(parents=True, exist_ok=True)

        # Create logs directory
        log_path = Path(self.log_file).parent
        log_path.mkdir(parents=True, exist_ok=True)


# TWSE API endpoints
TWSE_API_ENDPOINTS = {
    "realtime": "https://mis.twse.com.tw/stock/api/getStockInfo.jsp",
    "daily_history": "https://www.twse.com.tw/exchangeReport/STOCK_DAY",
    "daily_all": "https://www.twse.com.tw/exchangeReport/MI_INDEX",
    "stock_list": "https://isin.twse.com.tw/isin/C_public.jsp",
}

# Default User-Agent for API requests
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def get_logging_config(log_file: str = "logs/app.log", log_level: str = "INFO") -> dict:
    """
    Generate logging configuration dictionary.

    Args:
        log_file: Path to the log file
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    Returns:
        Logging configuration dictionary for use with logging.config.dictConfig()
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S"
            },
            "detailed": {
                "format": "%(asctime)s [%(levelname)s] %(name)s.%(funcName)s:%(lineno)d: %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S"
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": log_level,
                "formatter": "standard",
                "stream": "ext://sys.stdout"
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "DEBUG",
                "formatter": "detailed",
                "filename": log_file,
                "maxBytes": 10485760,  # 10MB
                "backupCount": 5,
                "encoding": "utf-8"
            }
        },
        "loggers": {
            "autofetchstock": {
                "level": "DEBUG",
                "handlers": ["console", "file"],
                "propagate": False
            },
            "autofetchstock.fetcher": {
                "level": "DEBUG",
                "handlers": ["console", "file"],
                "propagate": False
            },
            "autofetchstock.storage": {
                "level": "DEBUG",
                "handlers": ["console", "file"],
                "propagate": False
            },
            "autofetchstock.processor": {
                "level": "DEBUG",
                "handlers": ["console", "file"],
                "propagate": False
            },
            "autofetchstock.renderer": {
                "level": "INFO",
                "handlers": ["console", "file"],
                "propagate": False
            },
            "autofetchstock.scheduler": {
                "level": "INFO",
                "handlers": ["console", "file"],
                "propagate": False
            },
            "autofetchstock.app": {
                "level": "INFO",
                "handlers": ["console", "file"],
                "propagate": False
            }
        },
        "root": {
            "level": log_level,
            "handlers": ["console"]
        }
    }


# Default logging configuration
LOGGING_CONFIG = get_logging_config()


def setup_logging(config: Optional[AppConfig] = None) -> None:
    """
    Initialize the logging system.

    Args:
        config: Optional AppConfig instance. If None, uses default settings.
    """
    if config is None:
        log_file = "logs/app.log"
        log_level = "INFO"
    else:
        log_file = config.log_file
        log_level = config.log_level

    # Ensure log directory exists
    log_path = Path(log_file).parent
    log_path.mkdir(parents=True, exist_ok=True)

    # Get and apply logging configuration
    logging_config = get_logging_config(log_file, log_level)
    logging.config.dictConfig(logging_config)

    # Log initialization
    logger = logging.getLogger("autofetchstock")
    logger.info("Logging system initialized")


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for the specified module.

    Args:
        name: Module name (e.g., "autofetchstock.fetcher")

    Returns:
        Logger instance
    """
    return logging.getLogger(name)
