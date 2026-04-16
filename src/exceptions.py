"""
Custom exception classes for autoFetchStock.

This module defines all custom exceptions used throughout the application,
organized by the requirements they address:

- AutoFetchStockError: Base exception class
- ConnectionTimeoutError: TWSE API connection timeout (REQ-100)
- InvalidDataError: API returned unexpected data format (REQ-101)
- StockNotFoundError: Stock not found in TWSE database (REQ-102)
- DataCorruptedError: Local JSON file corrupted (REQ-103)
- ServiceUnavailableError: TWSE API consecutive failures (REQ-104)
- DiskSpaceError: Insufficient disk space (REQ-105)
- SchedulerTaskError: Scheduler task execution error (REQ-106)
"""


class AutoFetchStockError(Exception):
    """
    Base exception class for all autoFetchStock errors.

    All custom exceptions in this application inherit from this class,
    allowing for easy catching of all application-specific errors.
    """

    def __init__(self, message: str = "An error occurred in autoFetchStock"):
        self.message = message
        super().__init__(self.message)


class ConnectionTimeoutError(AutoFetchStockError):
    """
    TWSE API connection timeout error (REQ-100).

    Raised when:
    - HTTP request to TWSE API exceeds the timeout limit (default: 10 seconds)
    - Network connectivity issues prevent reaching the API

    Handling:
    - Display "網路連線逾時，請稍後再試" message
    - Auto-retry once after 30 seconds
    """

    def __init__(self, message: str = "網路連線逾時，請稍後再試", url: str = None, timeout: int = None):
        self.url = url
        self.timeout = timeout
        detail = f" (URL: {url}, timeout: {timeout}s)" if url else ""
        super().__init__(f"{message}{detail}")


class InvalidDataError(AutoFetchStockError):
    """
    API returned unexpected data format error (REQ-101).

    Raised when:
    - TWSE API returns data in an unexpected format
    - Required fields are missing from the response
    - Data validation fails (e.g., invalid OHLC values)

    Handling:
    - Discard the current data
    - Log error details
    - Display "資料格式異常，已略過本次更新" warning message
    """

    def __init__(self, message: str = "資料格式異常，已略過本次更新", field: str = None, value=None):
        self.field = field
        self.value = value
        detail = f" (field: {field}, value: {value})" if field else ""
        super().__init__(f"{message}{detail}")


class StockNotFoundError(AutoFetchStockError):
    """
    Stock not found in TWSE database error (REQ-102).

    Raised when:
    - User-entered stock code does not exist
    - User-entered stock name has no matches

    Handling:
    - Display "查無此股票，請確認輸入內容" error message
    """

    def __init__(self, message: str = "查無此股票，請確認輸入內容", stock_id: str = None, keyword: str = None):
        self.stock_id = stock_id
        self.keyword = keyword
        identifier = stock_id or keyword
        detail = f" ({identifier})" if identifier else ""
        super().__init__(f"{message}{detail}")


class DataCorruptedError(AutoFetchStockError):
    """
    Local JSON file corrupted error (REQ-103).

    Raised when:
    - JSON file cannot be parsed (syntax error)
    - JSON structure does not match expected schema
    - Data integrity check fails

    Handling:
    - Backup the corrupted file to data/backup/
    - Create a new empty JSON file
    - Display "歷史資料載入失敗，已重新建立資料檔" warning message
    """

    def __init__(self, message: str = "歷史資料載入失敗，已重新建立資料檔", file_path: str = None, reason: str = None):
        self.file_path = file_path
        self.reason = reason
        detail = f" (file: {file_path})" if file_path else ""
        reason_detail = f" - {reason}" if reason else ""
        super().__init__(f"{message}{detail}{reason_detail}")


class ServiceUnavailableError(AutoFetchStockError):
    """
    TWSE API consecutive failures error (REQ-104).

    Raised when:
    - TWSE API fails 3 consecutive times
    - Indicates potential API unavailability or network issues

    Handling:
    - Pause automatic scheduled fetching
    - Display "資料來源暫時無法存取，自動更新已暫停" warning message
    - Allow manual retry later
    """

    def __init__(
        self,
        message: str = "資料來源暫時無法存取，自動更新已暫停",
        failures: int = None,
        consecutive_failures: int = None,
    ):
        resolved_failures = (
            consecutive_failures
            if consecutive_failures is not None
            else failures
        )
        self.failures = resolved_failures
        self.consecutive_failures = resolved_failures
        detail = f" (連續失敗 {resolved_failures} 次)" if resolved_failures else ""
        super().__init__(f"{message}{detail}")


class DiskSpaceError(AutoFetchStockError):
    """
    Insufficient disk space error (REQ-105).

    Raised when:
    - Available disk space falls below minimum threshold (default: 100MB)
    - Before attempting to write data to disk

    Handling:
    - Stop all data write operations
    - Display "磁碟空間不足，請清理磁碟後重試" error message
    """

    def __init__(self, message: str = "磁碟空間不足，請清理磁碟後重試", available_mb: float = None, required_mb: float = None):
        self.available_mb = available_mb
        self.required_mb = required_mb
        detail = f" (可用: {available_mb:.1f}MB, 需要: {required_mb:.1f}MB)" if available_mb is not None else ""
        super().__init__(f"{message}{detail}")


class SchedulerTaskError(AutoFetchStockError):
    """
    Scheduler task execution error (REQ-106).

    Raised when:
    - An unexpected exception occurs during scheduled task execution
    - Used to wrap other exceptions that occur within scheduler jobs

    Handling:
    - Catch exception and log full stack trace
    - Continue scheduler operation (do not interrupt other tasks)
    - Record error for debugging
    """

    def __init__(self, message: str = "排程任務執行錯誤", task_id: str = None, original_error: Exception = None):
        self.task_id = task_id
        self.original_error = original_error
        detail = f" (task: {task_id})" if task_id else ""
        error_detail = f" - {type(original_error).__name__}: {original_error}" if original_error else ""
        super().__init__(f"{message}{detail}{error_detail}")


class RateLimitError(AutoFetchStockError):
    """
    API rate limit exceeded error.

    Raised when:
    - Requests are sent too frequently to TWSE API
    - Need to wait before making another request

    Handling:
    - Wait for the specified interval before retrying
    """

    def __init__(self, message: str = "請求過於頻繁，請稍後再試", wait_seconds: float = None):
        self.wait_seconds = wait_seconds
        detail = f" (請等待 {wait_seconds:.1f} 秒)" if wait_seconds else ""
        super().__init__(f"{message}{detail}")


class NewsFetchError(AutoFetchStockError):
    """
    News source fetch failure.

    Raised when:
    - RSS feed parsing fails completely (not a single-article fallback)
    - HTTP error on a news source URL

    Handling:
    - Log error and skip the source
    - Increment consecutive failure counter
    """

    def __init__(
        self,
        message: str = "新聞來源抓取失敗",
        source_url: str = None,
        reason: str = None,
    ):
        self.source_url = source_url
        self.reason = reason
        detail = f" (url: {source_url})" if source_url else ""
        super().__init__(f"{message}{detail}")


class SummarizationError(AutoFetchStockError):
    """
    News summarization API failure.

    Raised when:
    - Gemini API initialization fails
    - API quota exceeded
    - gemini-cli subprocess returns non-zero exit code

    Handling:
    - Set summary_failed=True on affected articles
    - Log full error details
    - Continue processing other articles
    """

    def __init__(
        self,
        message: str = "新聞摘要失敗",
        article_title: str = None,
        reason: str = None,
    ):
        self.article_title = article_title
        self.reason = reason
        detail = f": {reason}" if reason else ""
        super().__init__(f"{message}{detail}")
