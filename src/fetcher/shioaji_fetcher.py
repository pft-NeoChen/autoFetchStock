"""
Shioaji (Sinopac) API fetcher implementation for real-time streaming data.
"""

import json
import os
import threading
import time
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime, date, time as dtime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import shioaji as sj
from shioaji.constant import QuoteVersion

from src.config import AppConfig, get_logger
from src.models import (
    RealtimeQuote,
    IntradayTick,
    DailyOHLC,
    PriceDirection,
    MinuteKBar,
)

logger = get_logger("autofetchstock.fetcher")

_TZ_TAIPEI = ZoneInfo("Asia/Taipei")
_TZ_UTC = timezone.utc

_TS_DEBUG_ENABLED = os.environ.get("SHIOAJI_TS_DEBUG", "").lower() in ("1", "true", "yes")
_TS_DEBUG_MAX = 50
_TS_DEBUG_PATH = Path("logs/ts_debug.jsonl")

_TZ_STATE_LOCK = threading.Lock()
_TZ_STATE: Dict[str, Any] = {
    "total": 0,
    "by_source": {"datetime_aware": 0, "datetime_naive": 0, "epoch": 0, "string": 0},
    "debug_written": 0,
}


def get_tz_stats() -> Dict[str, Any]:
    """Snapshot of timezone-normalization counters (read-only)."""
    with _TZ_STATE_LOCK:
        return {
            "total": _TZ_STATE["total"],
            "by_source": dict(_TZ_STATE["by_source"]),
            "debug_written": _TZ_STATE["debug_written"],
        }


def _record_ts_debug(raw: Any, corrected: Optional[datetime], source: str) -> None:
    """Increment counters and (optionally) append a JSONL diagnostic row."""
    with _TZ_STATE_LOCK:
        _TZ_STATE["total"] += 1
        _TZ_STATE["by_source"][source] = _TZ_STATE["by_source"].get(source, 0) + 1
        if not _TS_DEBUG_ENABLED or _TZ_STATE["debug_written"] >= _TS_DEBUG_MAX:
            return
        _TZ_STATE["debug_written"] += 1
        try:
            _TS_DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "logged_at": datetime.now(_TZ_TAIPEI).isoformat(),
                "source_type": source,
                "raw_repr": repr(raw),
                "corrected": corrected.isoformat() if corrected else None,
            }
            with open(_TS_DEBUG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.debug("ts_debug write failed: %s", exc)


def _to_float_or_none(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
        self._subscription_failures: Dict[str, set[str]] = {}
        self._active_streams: Dict[str, set[str]] = {}
        self._subscription_lock = threading.RLock()
        self._last_quotes: Dict[str, RealtimeQuote] = {}  # Cache for latest quotes
        self._last_bidask: Dict[str, dict] = {}  # Cache for latest bid/ask five-level data
        self._quote_subscribed: set[str] = set()  # Stocks with QuoteType.Quote subscription
        self._on_quote_callback: Optional[Callable[[RealtimeQuote], None]] = None
        self._on_tick_callback: Optional[Callable[[IntradayTick], None]] = None
        # MarketStrip — symbol→reference cache and tick handler for index/future streams.
        self._index_subscribed: set[str] = set()
        self._index_reference: Dict[str, float] = {}
        self._index_tick_handler: Optional[Callable[[str, float, float, Optional[float], Optional[float], Optional[float]], None]] = None
        
        self._initialized = True
        logger.info(f"ShioajiFetcher initialized (Simulation: {self.config.shioaji_simulation})")

    @staticmethod
    def _normalize_datetime(value: Any) -> Optional[datetime]:
        """Normalize Shioaji timestamp fields to Asia/Taipei naive datetimes.

        Shioaji SDK 1.3.2 yields timestamps in three flavours:
        * `datetime` with `tzinfo` set — already correct; just convert.
        * `datetime` naive — SDK internally uses `utcfromtimestamp(ns/1e9)`
          which strips tz, so the literal HH:MM is UTC. Re-attach UTC and
          convert to Asia/Taipei.
        * `int` / `float` epoch (s or ns) — same UTC re-interpretation.

        All branches funnel through `zoneinfo.ZoneInfo("Asia/Taipei")` so
        results are stable regardless of system TZ (Docker UTC vs host TPE).
        """
        if value is None:
            return None

        parsed: Optional[datetime] = None
        source: Optional[str] = None

        if isinstance(value, datetime):
            if value.tzinfo is not None:
                source = "datetime_aware"
                parsed = value.astimezone(_TZ_TAIPEI).replace(tzinfo=None)
            else:
                source = "datetime_naive"
                parsed = (
                    value.replace(tzinfo=_TZ_UTC)
                    .astimezone(_TZ_TAIPEI)
                    .replace(tzinfo=None)
                )
        elif isinstance(value, (int, float)):
            if value > 0:
                source = "epoch"
                seconds = value / 1_000_000_000 if value > 10_000_000_000 else value
                try:
                    parsed = (
                        datetime.fromtimestamp(seconds, tz=_TZ_UTC)
                        .astimezone(_TZ_TAIPEI)
                        .replace(tzinfo=None)
                    )
                except (OSError, OverflowError, ValueError):
                    pass
        elif isinstance(value, str) and value:
            source = "string"
            try:
                parsed_str = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed_str.tzinfo is not None:
                    parsed = parsed_str.astimezone(_TZ_TAIPEI).replace(tzinfo=None)
                else:
                    parsed = (
                        parsed_str.replace(tzinfo=_TZ_UTC)
                        .astimezone(_TZ_TAIPEI)
                        .replace(tzinfo=None)
                    )
            except ValueError:
                pass

        if parsed is not None and source is not None:
            _record_ts_debug(value, parsed, source)
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
            self.api.quote.set_on_bidask_stk_v1_callback(self._handle_bidask)
            self.api.quote.set_event_callback(self._handle_event)
            self.api.set_session_down_callback(self._handle_session_down)

            # MarketStrip — FOP tick stream for TXF futures used by the
            # below-chart strip (台指近 / 台指近全). Failure tolerated:
            # IndexFetcher falls back to snapshots() if no ticks land.
            try:
                self.api.quote.set_on_tick_fop_v1_callback(self._handle_fop_tick)
            except Exception as exc:
                logger.debug("set_on_tick_fop_v1_callback unavailable: %s", exc)
            
            self.is_connected = True
            return True
        except Exception as e:
            logger.error(f"Shioaji login failed: {str(e)}")
            self.is_connected = False
            return False

    def logout(self):
        """Log out from Shioaji API."""
        if self.is_connected:
            try:
                self.set_active_quote(None)
            except Exception as exc:
                logger.debug(f"clear Quote subs on logout failed: {exc}")
            self.api.logout()
            self.is_connected = False
            logger.info("Shioaji logged out.")

    @staticmethod
    def _extract_stock_id_from_topic(info: str) -> Optional[str]:
        """Extract a stock code from Shioaji event topic text."""
        for part in reversed(str(info or "").split("/")):
            if part.isdigit() and len(part) == 4:
                return part
        return None

    @staticmethod
    def _stream_kind_from_topic(info: str) -> str:
        """Map Shioaji topic prefixes to the stream state we care about."""
        topic = str(info or "")
        prefix = topic.split("/", 1)[0]
        if prefix in {"TIC", "MKT"}:
            return "tick"
        if prefix in {"QUO", "QUT"}:
            return "bidask"
        return "unknown"

    def _handle_event(
        self,
        resp_code: int,
        event_code: int,
        info: str,
        event: str,
    ) -> None:
        """Track Shioaji quote session events for subscription fallback."""
        stock_id = self._extract_stock_id_from_topic(info)
        stream_kind = self._stream_kind_from_topic(info)

        if event_code == 4:
            if stock_id and stream_kind != "unknown":
                with self._subscription_lock:
                    self._subscription_failures.setdefault(stock_id, set()).add(
                        stream_kind
                    )
                    active = self._active_streams.get(stock_id)
                    if active:
                        active.discard(stream_kind)
                logger.warning(
                    "Shioaji subscription rejected for %s (%s): resp=%s info=%s event=%s",
                    stock_id,
                    stream_kind,
                    resp_code,
                    info,
                    event,
                )
            else:
                logger.warning(
                    "Shioaji subscription event error: resp=%s code=%s info=%s event=%s",
                    resp_code,
                    event_code,
                    info,
                    event,
                )
            return

        if event_code == 16 and stock_id and stream_kind != "unknown":
            with self._subscription_lock:
                self._active_streams.setdefault(stock_id, set()).add(stream_kind)
                failures = self._subscription_failures.get(stock_id)
                if failures:
                    failures.discard(stream_kind)
                    if not failures:
                        self._subscription_failures.pop(stock_id, None)
            logger.debug(
                "Shioaji subscription confirmed for %s (%s): info=%s",
                stock_id,
                stream_kind,
                info,
            )
            return

        if event_code in {1, 2}:
            self.is_connected = False
            logger.warning(
                "Shioaji quote session down: resp=%s code=%s info=%s event=%s",
                resp_code,
                event_code,
                info,
                event,
            )
        elif event_code in {0, 13}:
            self.is_connected = True
            logger.info(
                "Shioaji quote session connected: info=%s event=%s",
                info,
                event,
            )
        else:
            logger.debug(
                "Shioaji quote event: resp=%s code=%s info=%s event=%s",
                resp_code,
                event_code,
                info,
                event,
            )

    def _handle_session_down(self) -> None:
        """Mark the Shioaji session as disconnected when the SDK reports it."""
        self.is_connected = False
        with self._subscription_lock:
            self._active_streams.clear()
        logger.warning("Shioaji quote session down")

    def subscribe(self, stock_id: str) -> bool:
        """Subscribe to real-time quotes and ticks for a stock."""
        if not self.is_connected:
            logger.warning(f"Cannot subscribe to {stock_id}: Not connected.")
            return False

        with self._subscription_lock:
            if (
                stock_id in self._subscriptions
                and "tick" not in self._subscription_failures.get(stock_id, set())
            ):
                logger.debug(f"Stock {stock_id} already subscribed to Shioaji")
                return True

        try:
            contract = self.api.Contracts.Stocks[stock_id]
            if not contract:
                logger.error(f"Stock contract not found: {stock_id}")
                return False

            # Store metadata for callback use
            with self._subscription_lock:
                self._subscriptions[stock_id] = {
                    "contract": contract,
                    "name": contract.name,
                    "reference": getattr(contract, "reference", 0),
                }
                self._subscription_failures.pop(stock_id, None)
            
            # Subscribe to tick data and five-level bid/ask. Tick keeps the
            # realtime quote cache current; BidAsk feeds order-book display.
            logger.info(f"Subscribing to {stock_id} ({contract.name})...")
            self.api.quote.subscribe(
                contract,
                quote_type=sj.constant.QuoteType.Tick,
                version=QuoteVersion.v1,
            )
            self.api.quote.subscribe(
                contract,
                quote_type=sj.constant.QuoteType.BidAsk,
                version=QuoteVersion.v1,
            )
            
            logger.info(
                f"Subscribed to Shioaji streaming for {stock_id} ({contract.name})"
            )
            return True
        except Exception as e:
            logger.error(f"Error subscribing to {stock_id}: {str(e)}")
            with self._subscription_lock:
                self._subscription_failures.setdefault(stock_id, set()).add("tick")
            return False

    def unsubscribe(self, stock_id: str):
        """Unsubscribe from a stock."""
        with self._subscription_lock:
            sub_info = self._subscriptions.pop(stock_id, None)
            self._subscription_failures.pop(stock_id, None)
            self._active_streams.pop(stock_id, None)

        if sub_info:
            contract = sub_info["contract"]
            self.api.quote.unsubscribe(
                contract,
                quote_type=sj.constant.QuoteType.Tick,
                version=QuoteVersion.v1,
            )
            self.api.quote.unsubscribe(
                contract,
                quote_type=sj.constant.QuoteType.BidAsk,
                version=QuoteVersion.v1,
            )
            
            # Remove from cache
            self._last_quotes.pop(stock_id, None)
            self._last_bidask.pop(stock_id, None)

            # Also drop any Quote (snapshot) subscription tied to this stock.
            if stock_id in self._quote_subscribed:
                try:
                    self.api.quote.unsubscribe(
                        contract,
                        quote_type=sj.constant.QuoteType.Quote,
                        version=QuoteVersion.v1,
                    )
                except Exception as exc:
                    logger.debug(f"Quote unsubscribe failed for {stock_id}: {exc}")
                self._quote_subscribed.discard(stock_id)

            logger.info(f"Unsubscribed from {stock_id}")

    def subscribe_quote(self, stock_id: str) -> bool:
        """Subscribe to QuoteType.Quote (1Hz snapshot) for one stock.

        Keeps `_last_quotes[stock_id].timestamp` advancing even when the
        stock has no trades, so the stale-data alert (5s threshold) does
        not fire on illiquid names. Idempotent.
        """
        if not self.is_connected:
            logger.warning(f"Cannot subscribe Quote for {stock_id}: Not connected.")
            return False

        with self._subscription_lock:
            if stock_id in self._quote_subscribed:
                return True
            sub_info = self._subscriptions.get(stock_id)

        try:
            contract = (sub_info or {}).get("contract") if sub_info else None
            if contract is None:
                contract = self.api.Contracts.Stocks[stock_id]
                if not contract:
                    logger.error(f"Stock contract not found for Quote sub: {stock_id}")
                    return False

            self.api.quote.subscribe(
                contract,
                quote_type=sj.constant.QuoteType.Quote,
                version=QuoteVersion.v1,
            )
            with self._subscription_lock:
                self._quote_subscribed.add(stock_id)
            logger.info(f"Subscribed Quote snapshot stream for {stock_id}")
            return True
        except Exception as exc:
            logger.error(f"Quote subscribe failed for {stock_id}: {exc}")
            return False

    def unsubscribe_quote(self, stock_id: str) -> None:
        """Drop QuoteType.Quote subscription for one stock. Idempotent."""
        with self._subscription_lock:
            if stock_id not in self._quote_subscribed:
                return
            sub_info = self._subscriptions.get(stock_id)

        contract = (sub_info or {}).get("contract") if sub_info else None
        if contract is None:
            try:
                contract = self.api.Contracts.Stocks[stock_id]
            except Exception:
                contract = None

        if contract is not None:
            try:
                self.api.quote.unsubscribe(
                    contract,
                    quote_type=sj.constant.QuoteType.Quote,
                    version=QuoteVersion.v1,
                )
            except Exception as exc:
                logger.debug(f"Quote unsubscribe failed for {stock_id}: {exc}")

        with self._subscription_lock:
            self._quote_subscribed.discard(stock_id)
        logger.info(f"Unsubscribed Quote snapshot stream for {stock_id}")

    def set_active_quote(self, stock_id: Optional[str]) -> None:
        """Ensure only ``stock_id`` (if any) has a QuoteType.Quote subscription.

        Caller passes the currently selected stock. Any previously active
        Quote subscriptions on other stocks are dropped, so total snapshot
        traffic stays at ~1 msg/s regardless of watchlist size.
        Pass ``None`` to clear all Quote subs (e.g. on logout).
        """
        with self._subscription_lock:
            previous = set(self._quote_subscribed)

        for prev in previous:
            if prev != stock_id:
                self.unsubscribe_quote(prev)

        if stock_id:
            self.subscribe_quote(stock_id)

    def get_last_quote(self, stock_id: str) -> Optional[RealtimeQuote]:
        """Get the last received quote for a stock."""
        return self._last_quotes.get(stock_id)

    def get_last_bidask(self, stock_id: str) -> Optional[dict]:
        """Get the last received bid/ask five-level data for a stock."""
        return self._last_bidask.get(stock_id)
        
    # ── MarketStrip: index / futures streaming ─────────────────────

    def register_index_tick_handler(self, handler: Callable) -> None:
        """Register IndexFetcher's tick callback. Called on every tick from
        subscribed Indexs (stk callback) or Futures (fop callback).

        Signature: (symbol, close, reference, change_price, change_rate, total_amount).
        """
        self._index_tick_handler = handler

    def subscribe_index_or_future(self, contract, kind: str) -> None:
        """Subscribe to a tick stream for an index or futures contract.

        Idempotent per contract code. Failures are logged at debug and
        tolerated — the IndexFetcher's snapshot fallback covers gaps.
        """
        code = getattr(contract, "code", None)
        if not code:
            return
        if code in self._index_subscribed:
            return
        try:
            # Cache reference price so the tick handler can compute change/pct
            # when the tick payload itself doesn't carry it.
            ref = float(getattr(contract, "reference", 0) or 0)
            if ref > 0:
                self._index_reference[code] = ref
            # Also map continuous-contract aliases (TXFR1) → reference, so
            # ticks delivered under either code path route correctly.
            for alias in (getattr(contract, "symbol", None), getattr(contract, "category", None)):
                if alias and isinstance(alias, str):
                    self._index_subscribed.add(alias)
                    if ref > 0:
                        self._index_reference[alias] = ref

            self.api.quote.subscribe(
                contract,
                quote_type=sj.constant.QuoteType.Tick,
                version=QuoteVersion.v1,
            )
            self._index_subscribed.add(code)
            logger.info(
                f"MarketStrip: subscribed {kind}/{code} ref={ref}"
            )
        except Exception as exc:
            logger.debug(f"MarketStrip subscribe {kind}/{code} failed: {exc}")

    def _handle_fop_tick(self, exchange, tick):
        """FOP tick callback — route to index/future stream cache."""
        try:
            code = getattr(tick, "code", None)
            if not code or self._index_tick_handler is None:
                return
            close = float(getattr(tick, "close", 0) or 0)
            if close <= 0:
                return
            reference = self._index_reference.get(code, 0.0)
            logger.debug(
                f"FOP tick: code={code} close={close} ref={reference}"
            )
            self._index_tick_handler(
                code, close, reference,
                _to_float_or_none(getattr(tick, "price_chg", None)),
                _to_float_or_none(getattr(tick, "pct_chg", None)),
                _to_float_or_none(getattr(tick, "total_amount", None)),
            )
        except Exception as exc:
            logger.debug(f"_handle_fop_tick failed: {exc}")

    def is_subscribed(self, stock_id: str) -> bool:
        """Check if stock is currently subscribed."""
        with self._subscription_lock:
            if stock_id not in self._subscriptions:
                return False
            failures = self._subscription_failures.get(stock_id, set())
            return "tick" not in failures

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

    # ── Volume Spike Detection: 1-minute K bar fetch ───────────────────────

    TRADING_START: dtime = dtime(9, 0)
    TRADING_END: dtime = dtime(13, 30)

    def fetch_minute_kbars(
        self,
        stock_id: str,
        target_date: date,
        start_time: Optional[dtime] = None,
        end_time: Optional[dtime] = None,
    ) -> List[MinuteKBar]:
        """
        Fetch 1-minute K bars for a single trading day.

        Primary path: Shioaji `api.kbars(contract, start, end)`.
        Fallback: aggregate from `api.ticks()` if kbars fails or returns empty.

        Bars outside the trading session [09:00, 13:30] (or the
        explicit start_time/end_time window) are filtered out.
        """
        if not self.is_connected:
            logger.warning("fetch_minute_kbars called while disconnected")
            return []

        start_t = start_time or self.TRADING_START
        end_t = end_time or self.TRADING_END

        bars: List[MinuteKBar] = []
        try:
            bars = self._fetch_minute_kbars_via_kbars_api(stock_id, target_date)
        except Exception as exc:
            logger.warning(
                "Shioaji kbars failed for %s on %s: %s — falling back to ticks",
                stock_id, target_date, exc,
            )

        if not bars:
            try:
                ticks = self._fetch_ticks_for_date(stock_id, target_date)
                if ticks:
                    bars = self._aggregate_from_ticks(stock_id, target_date, ticks)
            except Exception as exc:
                logger.error(
                    "Tick fallback failed for %s on %s: %s",
                    stock_id, target_date, exc,
                )
                return []

        return [b for b in bars if start_t <= b.timestamp.time() <= end_t]

    def _fetch_minute_kbars_via_kbars_api(
        self, stock_id: str, target_date: date
    ) -> List[MinuteKBar]:
        """Call Shioaji kbars API and convert to MinuteKBar list."""
        import pandas as pd

        contract = self.api.Contracts.Stocks[stock_id]
        if not contract:
            logger.error("Stock contract not found: %s", stock_id)
            return []

        date_str = target_date.strftime("%Y-%m-%d")
        kbars = self.api.kbars(contract, start=date_str, end=date_str)
        if not kbars or not getattr(kbars, "ts", None):
            return []

        df = pd.DataFrame({**kbars})
        if df.empty:
            return []

        bars: List[MinuteKBar] = []
        for _, row in df.iterrows():
            ts_local = self._normalize_datetime(row["ts"])
            if ts_local is None or ts_local.date() != target_date:
                continue
            volume = int(row.get("Volume", 0) or 0)
            amount = float(row.get("Amount", 0) or 0)
            close_px = float(row["Close"])
            vwap = (amount / (volume * 1000)) if volume > 0 else close_px
            bars.append(MinuteKBar(
                stock_id=stock_id,
                timestamp=ts_local.replace(tzinfo=_TZ_TAIPEI),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=close_px,
                volume=volume,
                amount=amount,
                tick_count=0,  # Shioaji kbars does not provide tick count
                vwap=vwap,
            ))

        bars.sort(key=lambda b: b.timestamp)
        return bars

    def _fetch_ticks_for_date(
        self, stock_id: str, target_date: date
    ) -> List[IntradayTick]:
        """
        Pull historical ticks via Shioaji `api.ticks()` for fallback aggregation.
        """
        contract = self.api.Contracts.Stocks[stock_id]
        if not contract:
            return []

        date_str = target_date.strftime("%Y-%m-%d")
        raw = self.api.ticks(contract, date=date_str)
        if not raw or not getattr(raw, "ts", None):
            return []

        ticks: List[IntradayTick] = []
        ts_list = list(raw.ts)
        close_list = list(getattr(raw, "close", []))
        volume_list = list(getattr(raw, "volume", []))
        bid_volume = list(getattr(raw, "bid_volume", []))
        ask_volume = list(getattr(raw, "ask_volume", []))
        tick_type = list(getattr(raw, "tick_type", []))

        accumulated = 0
        for i, raw_ts in enumerate(ts_list):
            ts_local = self._normalize_datetime(raw_ts)
            if ts_local is None or ts_local.date() != target_date:
                continue
            try:
                price = float(close_list[i])
                vol = int(volume_list[i])
            except (IndexError, TypeError, ValueError):
                continue
            if vol < 0 or price <= 0:
                continue
            accumulated += vol

            tt = tick_type[i] if i < len(tick_type) else 0
            bv = float(bid_volume[i]) if i < len(bid_volume) else 0.0
            av = float(ask_volume[i]) if i < len(ask_volume) else 0.0
            buy_vol = float(vol) if tt == 1 else (av if av else 0.0)
            sell_vol = float(vol) if tt == 2 else (bv if bv else 0.0)

            ticks.append(IntradayTick(
                time=ts_local.time().replace(microsecond=0),
                price=price,
                volume=vol,
                buy_volume=buy_vol,
                sell_volume=sell_vol,
                accumulated_volume=accumulated,
                timestamp=ts_local.replace(tzinfo=_TZ_TAIPEI),
                is_odd=False,
            ))
        return ticks

    def _aggregate_from_ticks(
        self,
        stock_id: str,
        target_date: date,
        ticks: List[IntradayTick],
    ) -> List[MinuteKBar]:
        """
        Bucket regular-lot ticks into 1-minute K bars.

        Odd-lot ticks (`is_odd=True`) are skipped: their `volume` is in
        shares not lots, mixing them would corrupt the volume baseline.
        """
        if not ticks:
            return []

        buckets: Dict[tuple, List[IntradayTick]] = {}
        for tick in ticks:
            if getattr(tick, "is_odd", False):
                continue
            if tick.volume <= 0 or tick.price <= 0:
                continue
            key = (tick.time.hour, tick.time.minute)
            buckets.setdefault(key, []).append(tick)

        bars: List[MinuteKBar] = []
        for (hour, minute), group in sorted(buckets.items()):
            group.sort(key=lambda t: (t.time, t.accumulated_volume))
            prices = [t.price for t in group]
            volume = sum(t.volume for t in group)
            amount = sum(t.price * t.volume * 1000 for t in group)
            close_px = prices[-1]
            vwap = (amount / (volume * 1000)) if volume > 0 else close_px
            ts = datetime(
                target_date.year, target_date.month, target_date.day,
                hour, minute, tzinfo=_TZ_TAIPEI,
            )
            bars.append(MinuteKBar(
                stock_id=stock_id,
                timestamp=ts,
                open=prices[0],
                high=max(prices),
                low=min(prices),
                close=close_px,
                volume=volume,
                amount=amount,
                tick_count=len(group),
                vwap=vwap,
            ))
        return bars

    def _handle_quote(self, exchange, quote):
        """Callback handler for Shioaji Quote updates."""
        try:
            stock_id = quote.code

            # MarketStrip — Indexs quote events may arrive on the stk channel
            # depending on Shioaji version. Route to the index handler and
            # bail before the stock-specific code path (reference lookup,
            # bid/ask extraction) executes.
            if stock_id in self._index_subscribed and self._index_tick_handler is not None:
                try:
                    close = float(getattr(quote, "close", 0) or 0)
                    if close > 0:
                        reference = self._index_reference.get(stock_id, 0.0)
                        self._index_tick_handler(
                            stock_id, close, reference,
                            _to_float_or_none(getattr(quote, "price_chg", None)),
                            _to_float_or_none(getattr(quote, "pct_chg", None)),
                            _to_float_or_none(getattr(quote, "total_amount", None)),
                        )
                except Exception as exc:
                    logger.debug(f"index quote route failed for {stock_id}: {exc}")
                return
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

    def _handle_bidask(self, exchange, bidask):
        """Callback handler for Shioaji BidAsk updates."""
        try:
            stock_id = bidask.code
            bid_prices = [float(p) for p in getattr(bidask, "bid_price", []) or []]
            bid_volumes = [int(v) for v in getattr(bidask, "bid_volume", []) or []]
            ask_prices = [float(p) for p in getattr(bidask, "ask_price", []) or []]
            ask_volumes = [int(v) for v in getattr(bidask, "ask_volume", []) or []]

            if not bid_prices and not ask_prices:
                return

            self._last_bidask[stock_id] = {
                "bid_price": bid_prices,
                "bid_volume": bid_volumes,
                "ask_price": ask_prices,
                "ask_volume": ask_volumes,
                "bid_side_total_vol": int(
                    getattr(bidask, "bid_side_total_vol", 0) or 0
                ),
                "ask_side_total_vol": int(
                    getattr(bidask, "ask_side_total_vol", 0) or 0
                ),
            }

            cached_quote = self._last_quotes.get(stock_id)
            if cached_quote:
                if bid_prices:
                    cached_quote.best_bid = bid_prices[0]
                if ask_prices:
                    cached_quote.best_ask = ask_prices[0]

        except Exception as e:
            logger.error(f"Error handling shioaji bidask: {str(e)}")

    def _cache_quote_from_tick(self, tick, sub_info: dict, timestamp: datetime) -> None:
        """Refresh the realtime quote cache from a Shioaji tick event."""
        stock_id = tick.code
        stock_name = sub_info.get("name", "")
        reference = sub_info.get("reference", 0) or 0
        contract = sub_info.get("contract")
        limit_up = float(getattr(contract, "limit_up", 0)) if contract else 0.0
        limit_down = float(getattr(contract, "limit_down", 0)) if contract else 0.0

        current_price = float(tick.close)
        if hasattr(tick, "price_chg"):
            change = float(getattr(tick, "price_chg", 0) or 0)
        elif reference > 0:
            change = current_price - float(reference)
        else:
            change = 0.0

        if hasattr(tick, "pct_chg"):
            change_percent = float(getattr(tick, "pct_chg", 0) or 0)
        elif reference > 0:
            change_percent = (change / float(reference)) * 100
        else:
            change_percent = 0.0

        if change > 0:
            direction = PriceDirection.UP
        elif change < 0:
            direction = PriceDirection.DOWN
        else:
            direction = PriceDirection.FLAT

        bidask = self._last_bidask.get(stock_id, {})
        bid_prices = bidask.get("bid_price") or []
        ask_prices = bidask.get("ask_price") or []

        self._last_quotes[stock_id] = RealtimeQuote(
            stock_id=stock_id,
            stock_name=stock_name,
            current_price=current_price,
            open_price=float(getattr(tick, "open", current_price) or current_price),
            high_price=float(getattr(tick, "high", current_price) or current_price),
            low_price=float(getattr(tick, "low", current_price) or current_price),
            previous_close=float(reference),
            change_amount=change,
            change_percent=change_percent,
            direction=direction,
            total_volume=int(getattr(tick, "total_volume", 0) or 0),
            tick_volume=int(getattr(tick, "volume", 0) or 0),
            best_bid=float(bid_prices[0]) if bid_prices else 0.0,
            best_ask=float(ask_prices[0]) if ask_prices else 0.0,
            timestamp=timestamp,
            limit_up_price=limit_up,
            limit_down_price=limit_down,
            is_simtrade=bool(getattr(tick, "simtrade", False)),
        )

    def _handle_tick(self, exchange, tick):
        """Callback handler for Shioaji Tick updates."""
        # logger.info(f"Raw Tick: code={tick.code}, type={tick.tick_type}, vol={tick.volume}, odd={tick.intraday_odd}")

        # MarketStrip — Indexs (TSE 001 / OTC 101) tick events ride the stk
        # channel. Route to IndexFetcher's cache and bail out before stock
        # tick processing (which assumes Stocks-shaped fields like tick_type).
        code = getattr(tick, "code", None)
        if code and code in self._index_subscribed and self._index_tick_handler is not None:
            try:
                close = float(getattr(tick, "close", 0) or 0)
                if close > 0:
                    reference = self._index_reference.get(code, 0.0)
                    self._index_tick_handler(
                        code, close, reference,
                        _to_float_or_none(getattr(tick, "price_chg", None)),
                        _to_float_or_none(getattr(tick, "pct_chg", None)),
                        _to_float_or_none(getattr(tick, "total_amount", None)),
                    )
            except Exception as exc:
                logger.debug(f"index tick route failed for {code}: {exc}")
            return

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
            self._cache_quote_from_tick(tick, sub_info, corrected_dt)
            
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

    def set_callbacks(
        self,
        on_quote: Optional[Callable] = None,
        on_tick: Optional[Callable] = None,
    ):
        """Set external callbacks for data processing."""
        self._on_quote_callback = on_quote
        self._on_tick_callback = on_tick
