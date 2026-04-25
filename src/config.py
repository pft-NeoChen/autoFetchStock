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


def _env_int(name: str, default: int) -> int:
    """Read a positive integer from env, falling back to default."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


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

    # Shioaji API settings (Sinopac)
    shioaji_api_key_sim: str = field(default_factory=lambda: os.getenv("SHIOAJI_API_KEY_SIM", ""))
    shioaji_secret_key_sim: str = field(default_factory=lambda: os.getenv("SHIOAJI_SECRET_KEY_SIM", ""))
    shioaji_api_key_prod: str = field(default_factory=lambda: os.getenv("SHIOAJI_API_KEY_PROD", ""))
    shioaji_secret_key_prod: str = field(default_factory=lambda: os.getenv("SHIOAJI_SECRET_KEY_PROD", ""))
    
    shioaji_cert_path: str = field(default_factory=lambda: os.getenv("SHIOAJI_CERT_PATH", ""))
    shioaji_cert_password: str = field(default_factory=lambda: os.getenv("SHIOAJI_CERT_PASSWORD", ""))
    shioaji_person_id: str = field(default_factory=lambda: os.getenv("SHIOAJI_PERSON_ID", ""))
    
    shioaji_simulation: bool = field(
        default_factory=lambda: os.getenv("SHIOAJI_SIMULATION", "true").lower() == "true"
    )

    # ── News submodule settings ──────────────────────────────────────────────

    # Gemini API
    gemini_api_key: str = field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY", "")
    )
    news_summarizer_backend: str = field(
        default_factory=lambda: os.getenv("NEWS_SUMMARIZER_BACKEND", "gemini")
    )

    # News schedule (Asia/Taipei)
    news_start_hour: int = 8      # 排程開始時間
    news_end_hour: int = 15       # 排程結束時間（最後觸發在此小時）
    news_interval_minutes: int = 60

    # News fetch settings
    news_max_articles_per_category: int = 20
    news_request_timeout: int = 15        # 全文抓取逾時（秒）
    news_request_interval: float = 2.0   # 同網域請求間隔（秒）
    news_summarizer_timeout: int = 30     # 摘要 API 逾時（秒）
    news_max_run_minutes: int = 30        # 單次執行時間上限（分鐘）
    # 是否逐篇抓全文（極慢且非必要：摘要與分析皆用 RSS excerpt 即可）
    news_fetch_full_text: bool = field(
        default_factory=lambda: os.getenv("NEWS_FETCH_FULL_TEXT", "false").lower() == "true"
    )
    # 個股分類每檔最多抓幾篇（避免最愛太多時超慢）
    news_max_articles_per_stock: int = 5
    # News history settings
    news_retention_days: int = field(
        default_factory=lambda: _env_int("NEWS_RETENTION_DAYS", 30)
    )
    news_history_window_days: int = field(
        default_factory=lambda: _env_int("NEWS_HISTORY_WINDOW_DAYS", 7)
    )

    def get_shioaji_credentials(self) -> tuple[str, str]:
        """根據目前的模擬狀態回傳對應的 API Key 與 Secret."""
        if self.shioaji_simulation:
            return self.shioaji_api_key_sim, self.shioaji_secret_key_sim
        return self.shioaji_api_key_prod, self.shioaji_secret_key_prod

    def __post_init__(self):
        """Ensure directories exist after initialization."""
        # Create data directories
        data_path = Path(self.data_dir)
        for subdir in ["stocks", "intraday", "cache", "backup", "news"]:
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
