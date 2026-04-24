"""
Data storage for autoFetchStock.

This module handles all local JSON file operations:
- Directory structure initialization
- Atomic file writes (temp file + replace)
- Daily OHLC data persistence
- Intraday tick data persistence
- Data integrity validation
- Disk space monitoring
- Corrupted file backup
"""

import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

from src.models import (
    DailyOHLC,
    IntradayTick,
    StockDailyFile,
    StockIntradayFile,
)
from src.exceptions import (
    DataCorruptedError,
    DiskSpaceError,
)

logger = logging.getLogger("autofetchstock.storage")


class DataStorage:
    """
    Local JSON file storage manager.

    Implements REQ-003 (local JSON), REQ-070 (file per stock),
    REQ-071 (data fields), REQ-072 (append mode), REQ-073 (history load),
    REQ-084 (atomic write), REQ-103 (corrupted backup), REQ-105 (disk space).
    """

    DEFAULT_DATA_DIR: str = "data"
    MIN_DISK_SPACE_MB: int = 100

    # Subdirectory names
    STOCKS_DIR: str = "stocks"
    INTRADAY_DIR: str = "intraday"
    CACHE_DIR: str = "cache"
    BACKUP_DIR: str = "backup"
    NEWS_DIR: str = "news"

    def __init__(self, data_dir: str = None):
        """
        Initialize storage with directory structure.

        Args:
            data_dir: Base data directory path (default: "data")
        """
        self._data_dir = Path(data_dir or self.DEFAULT_DATA_DIR)
        self._init_directories()
        logger.info(f"DataStorage initialized at {self._data_dir}")

    def _init_directories(self) -> None:
        """Create all required subdirectories."""
        subdirs = [
            self.STOCKS_DIR,
            self.INTRADAY_DIR,
            self.CACHE_DIR,
            self.BACKUP_DIR,
            self.NEWS_DIR,
        ]

        for subdir in subdirs:
            path = self._data_dir / subdir
            path.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Ensured directory: {path}")

    @property
    def stocks_dir(self) -> Path:
        """Get stocks data directory path."""
        return self._data_dir / self.STOCKS_DIR

    @property
    def intraday_dir(self) -> Path:
        """Get intraday data directory path."""
        return self._data_dir / self.INTRADAY_DIR

    @property
    def cache_dir(self) -> Path:
        """Get cache directory path."""
        return self._data_dir / self.CACHE_DIR

    @property
    def backup_dir(self) -> Path:
        """Get backup directory path."""
        return self._data_dir / self.BACKUP_DIR

    @property
    def news_dir(self) -> Path:
        """Get news data directory path."""
        return self._data_dir / self.NEWS_DIR

    def save_favorites(self, favorites: List[Dict[str, str]]) -> bool:
        """
        Save favorites list to cache.

        Args:
            favorites: List of dicts with 'id' and 'name'

        Returns:
            True if successful
        """
        file_path = self.cache_dir / "favorites.json"
        try:
            self._atomic_write(file_path, {"favorites": favorites})
            return True
        except Exception as e:
            logger.error(f"Failed to save favorites: {e}")
            return False

    def load_favorites(self) -> List[Dict[str, str]]:
        """
        Load favorites list from cache.

        Returns:
            List of favorites
        """
        file_path = self.cache_dir / "favorites.json"
        data = self._load_json_file(file_path)
        if data and "favorites" in data:
            return data["favorites"]
        return []

    def save_stock_list_cache(self, stock_list: List[Dict[str, str]]) -> bool:
        """
        Save stock list to persistent cache.

        Args:
            stock_list: List of dicts with stock info

        Returns:
            True if successful
        """
        file_path = self.cache_dir / "stock_list.json"
        try:
            self._atomic_write(file_path, {
                "timestamp": datetime.now().isoformat(),
                "stocks": stock_list
            })
            return True
        except Exception as e:
            logger.error(f"Failed to save stock list cache: {e}")
            return False

    def load_stock_list_cache(self) -> Tuple[Optional[List[Dict[str, str]]], Optional[datetime]]:
        """
        Load stock list from persistent cache.

        Returns:
            Tuple of (list of stocks, timestamp)
        """
        file_path = self.cache_dir / "stock_list.json"
        data = self._load_json_file(file_path)
        
        if data and "stocks" in data:
            timestamp = None
            if "timestamp" in data:
                try:
                    timestamp = datetime.fromisoformat(data["timestamp"])
                except ValueError:
                    pass
            return data["stocks"], timestamp
            
        return None, None

    def save_daily_data(
        self,
        stock_id: str,
        stock_name: str,
        records: List[DailyOHLC]
    ) -> bool:
        """
        Save daily OHLC data in append mode (REQ-072).

        Existing records with matching dates will not be duplicated.
        Uses atomic write for safety (REQ-084).

        Args:
            stock_id: Stock ID (e.g., "2330")
            stock_name: Stock name (e.g., "台積電")
            records: List of DailyOHLC to save

        Returns:
            True if successful

        Raises:
            DiskSpaceError: Insufficient disk space (REQ-105)
        """
        if not records:
            logger.warning(f"No records to save for {stock_id}")
            return True

        # Check disk space first
        self._check_disk_space()

        file_path = self.stocks_dir / f"{stock_id}.json"

        # Load existing data
        existing_data = self._load_json_file(file_path)
        if existing_data:
            existing_records = existing_data.get("daily_data", [])
            existing_dates = {r["date"] for r in existing_records}
        else:
            existing_records = []
            existing_dates = set()

        # Append new records (skip duplicates)
        new_count = 0
        for record in records:
            date_str = record.date.isoformat() if isinstance(record.date, date) else str(record.date)
            if date_str not in existing_dates:
                existing_records.append({
                    "date": date_str,
                    "open": record.open,
                    "high": record.high,
                    "low": record.low,
                    "close": record.close,
                    "volume": record.volume,
                    "turnover": record.turnover,
                    "timestamp": record.timestamp.isoformat() if record.timestamp else datetime.now().isoformat(),
                })
                existing_dates.add(date_str)
                new_count += 1

        # Sort by date
        existing_records.sort(key=lambda x: x["date"])

        # Prepare file data
        file_data = {
            "stock_id": stock_id,
            "stock_name": stock_name,
            "last_updated": datetime.now().isoformat(),
            "daily_data": existing_records,
        }

        # Atomic write
        self._atomic_write(file_path, file_data)
        logger.info(f"Saved {new_count} new daily records for {stock_id} (total: {len(existing_records)})")
        return True

    def load_daily_data(self, stock_id: str) -> Optional[StockDailyFile]:
        """
        Load daily OHLC history for a stock (REQ-073).

        Args:
            stock_id: Stock ID

        Returns:
            StockDailyFile if exists, None otherwise

        Raises:
            DataCorruptedError: File corrupted (auto-backup then raise)
        """
        file_path = self.stocks_dir / f"{stock_id}.json"

        if not file_path.exists():
            logger.debug(f"No daily data file for {stock_id}")
            return None

        data = self._load_json_file(file_path)
        if data is None:
            # File exists but couldn't be loaded - corrupted
            self._backup_corrupted_file(file_path)
            raise DataCorruptedError(
                file_path=str(file_path),
                reason="JSON 解析失敗"
            )

        # Validate structure
        if not self._validate_daily_file_structure(data):
            self._backup_corrupted_file(file_path)
            raise DataCorruptedError(
                file_path=str(file_path),
                reason="資料結構不完整"
            )

        # Convert to dataclass
        daily_records = []
        for record in data.get("daily_data", []):
            try:
                daily_records.append(DailyOHLC(
                    date=date.fromisoformat(record["date"]) if isinstance(record["date"], str) else record["date"],
                    open=float(record["open"]),
                    high=float(record["high"]),
                    low=float(record["low"]),
                    close=float(record["close"]),
                    volume=int(record["volume"]),
                    turnover=float(record.get("turnover", 0)),
                    timestamp=datetime.fromisoformat(record["timestamp"]) if record.get("timestamp") else None,
                ))
            except (ValueError, KeyError) as e:
                logger.warning(f"Skipping invalid record: {e}")
                continue

        return StockDailyFile(
            stock_id=data["stock_id"],
            stock_name=data.get("stock_name", ""),
            last_updated=datetime.fromisoformat(data["last_updated"]) if data.get("last_updated") else datetime.now(),
            daily_data=daily_records,
        )

    def save_intraday_data(
        self,
        stock_id: str,
        stock_name: str,
        trade_date: date,
        previous_close: float,
        ticks: List[IntradayTick]
    ) -> bool:
        """
        Save intraday tick data in append mode.

        Args:
            stock_id: Stock ID
            stock_name: Stock name
            trade_date: Trading date
            previous_close: Previous day's close price
            ticks: List of IntradayTick to save

        Returns:
            True if successful

        Raises:
            DiskSpaceError: Insufficient disk space
        """
        if not ticks:
            logger.warning(f"No intraday ticks to save for {stock_id}")
            return True

        # Check disk space
        self._check_disk_space()

        date_str = trade_date.isoformat() if isinstance(trade_date, date) else str(trade_date)
        file_path = self.intraday_dir / f"{stock_id}_{date_str.replace('-', '')}.json"

        # Load existing data
        existing_data = self._load_json_file(file_path)
        if existing_data:
            existing_ticks = existing_data.get("ticks", [])
            existing_times = {t["time"] for t in existing_ticks}
        else:
            existing_ticks = []
            existing_times = set()

        # Append new ticks
        new_count = 0
        for tick in ticks:
            time_str = tick.time.isoformat() if hasattr(tick.time, "isoformat") else str(tick.time)
            if time_str not in existing_times:
                existing_ticks.append({
                    "time": time_str,
                    "price": tick.price,
                    "volume": tick.volume,
                    "buy_volume": tick.buy_volume,
                    "sell_volume": tick.sell_volume,
                    "accumulated_volume": tick.accumulated_volume,
                    "timestamp": tick.timestamp.isoformat() if tick.timestamp else datetime.now().isoformat(),
                    "is_odd": getattr(tick, "is_odd", False),
                })
                existing_times.add(time_str)
                new_count += 1

        # Sort by time
        existing_ticks.sort(key=lambda x: x["time"])

        # Prepare file data
        file_data = {
            "stock_id": stock_id,
            "stock_name": stock_name,
            "date": date_str,
            "previous_close": previous_close,
            "ticks": existing_ticks,
        }

        # Atomic write
        self._atomic_write(file_path, file_data)
        logger.info(f"Saved {new_count} new intraday ticks for {stock_id} (total: {len(existing_ticks)})")
        return True

    def load_intraday_data(
        self,
        stock_id: str,
        trade_date: date
    ) -> Optional[StockIntradayFile]:
        """
        Load intraday tick data for a specific date.

        Args:
            stock_id: Stock ID
            trade_date: Trading date

        Returns:
            StockIntradayFile if exists, None otherwise
        """
        date_str = trade_date.isoformat() if isinstance(trade_date, date) else str(trade_date)
        file_path = self.intraday_dir / f"{stock_id}_{date_str.replace('-', '')}.json"

        if not file_path.exists():
            logger.debug(f"No intraday data file for {stock_id} on {date_str}")
            return None

        data = self._load_json_file(file_path)
        if data is None:
            return None

        # Convert to dataclass
        ticks = []
        for tick in data.get("ticks", []):
            try:
                from datetime import time as time_type
                time_value = tick["time"]
                if isinstance(time_value, str):
                    time_value = time_type.fromisoformat(time_value)

                ticks.append(IntradayTick(
                    time=time_value,
                    price=float(tick["price"]),
                    volume=int(tick["volume"]),
                    buy_volume=int(tick.get("buy_volume", 0)),
                    sell_volume=int(tick.get("sell_volume", 0)),
                    accumulated_volume=int(tick.get("accumulated_volume", 0)),
                    timestamp=datetime.fromisoformat(tick["timestamp"]) if tick.get("timestamp") else None,
                ))
            except (ValueError, KeyError) as e:
                logger.warning(f"Skipping invalid tick: {e}")
                continue

        return StockIntradayFile(
            stock_id=data["stock_id"],
            stock_name=data.get("stock_name", ""),
            date=date.fromisoformat(data["date"]) if isinstance(data.get("date"), str) else trade_date,
            previous_close=float(data.get("previous_close", 0)),
            ticks=ticks,
        )

    def _atomic_write(self, file_path: Path, data: Dict[str, Any]) -> None:
        """
        Write data to file atomically (REQ-084).

        Uses temp file + os.replace() for atomic operation.

        Args:
            file_path: Target file path
            data: Data dict to write as JSON
        """
        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file in same directory (same filesystem for atomic rename)
        fd, temp_path = tempfile.mkstemp(
            suffix=".tmp",
            dir=file_path.parent
        )

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            # Atomic replace
            os.replace(temp_path, file_path)
            logger.debug(f"Atomic write completed: {file_path}")

        except Exception as e:
            # Clean up temp file on failure
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            logger.error(f"Atomic write failed: {e}")
            raise

    def _load_json_file(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """
        Load and parse JSON file.

        Args:
            file_path: Path to JSON file

        Returns:
            Parsed dict or None if file doesn't exist or is invalid
        """
        if not file_path.exists():
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error in {file_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error reading {file_path}: {e}")
            return None

    def _check_disk_space(self) -> None:
        """
        Check available disk space (REQ-105).

        Raises:
            DiskSpaceError: If available space < MIN_DISK_SPACE_MB
        """
        try:
            stat = shutil.disk_usage(self._data_dir)
            available_mb = stat.free / (1024 * 1024)

            if available_mb < self.MIN_DISK_SPACE_MB:
                logger.error(f"Low disk space: {available_mb:.1f}MB available")
                raise DiskSpaceError(
                    available_mb=available_mb,
                    required_mb=self.MIN_DISK_SPACE_MB
                )

        except OSError as e:
            logger.warning(f"Could not check disk space: {e}")
            # Don't raise - allow operation to continue

    def _backup_corrupted_file(self, file_path: Path) -> str:
        """
        Backup corrupted file to backup directory (REQ-103).

        Args:
            file_path: Path to corrupted file

        Returns:
            Backup file path
        """
        if not file_path.exists():
            return ""

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{file_path.stem}_{timestamp}_corrupted{file_path.suffix}"
        backup_path = self.backup_dir / backup_name

        try:
            shutil.move(str(file_path), str(backup_path))
            logger.warning(f"Backed up corrupted file: {file_path} -> {backup_path}")
            return str(backup_path)
        except Exception as e:
            logger.error(f"Failed to backup corrupted file: {e}")
            return ""

    def _validate_daily_file_structure(self, data: Dict[str, Any]) -> bool:
        """
        Validate daily data file structure.

        Args:
            data: Loaded JSON data

        Returns:
            True if structure is valid
        """
        required_fields = ["stock_id", "daily_data"]
        if not all(field in data for field in required_fields):
            return False

        if not isinstance(data.get("daily_data"), list):
            return False

        # Validate each record has required OHLC fields
        for record in data["daily_data"]:
            if not isinstance(record, dict):
                return False
            ohlc_fields = ["date", "open", "high", "low", "close", "volume"]
            if not all(field in record for field in ohlc_fields):
                return False

        return True

    def _validate_json_integrity(self, data: Dict[str, Any]) -> bool:
        """
        General JSON data structure validation.

        Args:
            data: Data dict to validate

        Returns:
            True if valid
        """
        if not isinstance(data, dict):
            return False

        if "stock_id" not in data:
            return False

        return True

    def get_available_stocks(self) -> List[str]:
        """
        Get list of stock IDs with saved data.

        Returns:
            List of stock IDs
        """
        stocks = []
        for file_path in self.stocks_dir.glob("*.json"):
            stock_id = file_path.stem
            stocks.append(stock_id)
        return sorted(stocks)

    def delete_daily_data(self, stock_id: str) -> bool:
        """
        Delete daily data file for a stock.

        Args:
            stock_id: Stock ID

        Returns:
            True if deleted, False if not found
        """
        file_path = self.stocks_dir / f"{stock_id}.json"
        if file_path.exists():
            file_path.unlink()
            logger.info(f"Deleted daily data for {stock_id}")
            return True
        return False

    def clear_intraday_data(self, days_to_keep: int = 7) -> int:
        """
        Clean up old intraday data files.

        Args:
            days_to_keep: Number of days to retain

        Returns:
            Number of files deleted
        """
        from datetime import timedelta

        cutoff_date = date.today() - timedelta(days=days_to_keep)
        deleted_count = 0

        for file_path in self.intraday_dir.glob("*.json"):
            try:
                # Extract date from filename (e.g., 2330_20260202.json)
                parts = file_path.stem.split("_")
                if len(parts) >= 2:
                    date_str = parts[-1]
                    file_date = date(
                        int(date_str[:4]),
                        int(date_str[4:6]),
                        int(date_str[6:8])
                    )
                    if file_date < cutoff_date:
                        file_path.unlink()
                        deleted_count += 1
            except (ValueError, IndexError):
                continue

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old intraday files")
        return deleted_count

    # ── News storage methods ─────────────────────────────────────────────────

    def save_news(self, run_result: "NewsRunResult") -> None:
        """
        Save a news run result to daily JSON and update latest.json.

        Appends the run to data/news/YYYYMMDD.json (NewsDailyFile format)
        and overwrites data/news/latest.json with the most recent run.

        Args:
            run_result: Completed NewsRunResult from NewsProcessor

        Raises:
            DiskSpaceError: Insufficient disk space
        """
        self._check_disk_space()

        date_str = run_result.run_at.strftime("%Y%m%d")
        daily_path = self.news_dir / f"{date_str}.json"

        # Load existing daily file or create new one
        existing_data = self._load_json_file(daily_path)
        if existing_data and "runs" in existing_data:
            daily_dict = existing_data
        else:
            daily_dict = {
                "date": date_str,
                "runs": [],
            }

        # Append this run
        daily_dict["runs"].append(run_result.to_dict())

        # Write daily file atomically
        self._atomic_write(daily_path, daily_dict)
        logger.info(
            f"Saved news run at {run_result.run_at.isoformat()} "
            f"to {daily_path.name}"
        )

        # Update latest.json with this run
        latest_path = self.news_dir / "latest.json"
        self._atomic_write(latest_path, run_result.to_dict())
        logger.debug("Updated news latest.json")

    def load_news(self, date_str: str) -> "Optional[NewsDailyFile]":
        """
        Load news daily file for a given date.

        Args:
            date_str: Date in YYYYMMDD format

        Returns:
            NewsDailyFile if the file exists, None otherwise
        """
        from src.news.news_models import NewsDailyFile

        daily_path = self.news_dir / f"{date_str}.json"
        data = self._load_json_file(daily_path)
        if data is None:
            logger.debug(f"No news file for date {date_str}")
            return None

        try:
            return NewsDailyFile.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to parse news daily file {daily_path}: {e}")
            return None

    def load_latest_news(self) -> "Optional[NewsRunResult]":
        """
        Load the most recent news run result.

        Returns:
            NewsRunResult from latest.json, or None if not found
        """
        from src.news.news_models import NewsRunResult

        latest_path = self.news_dir / "latest.json"
        data = self._load_json_file(latest_path)
        if data is None:
            logger.debug("No latest news file found")
            return None

        try:
            return NewsRunResult.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to parse latest news file: {e}")
            return None
