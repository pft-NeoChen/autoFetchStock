"""
MarketStrip index fetcher (Phase 3.5 #4).

Two data sources:
  * Local Taiwan indices (加權 / 櫃買 / 台50) — Shioaji snapshots.
    Real-time tick during market hours; the user already pays the
    Shioaji login cost so there's no marginal latency.
  * Foreign references (USD/TWD, gold GC=F, WTI CL=F, VIX) — yfinance.
    These are 15-minute delayed and only used as macro context, so
    the polling interval is 30 s with an in-memory last-good cache.

Failure modes are isolated per field: a single bad index does not
blank the ribbon — the caller composes results, falling back to the
spec STUB on missing entries so the layout stays whole.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

from src.models import MarketIndexEntry

logger = logging.getLogger("autofetchstock.index_fetcher")


def _direction(change: float) -> str:
    if change > 0:
        return "up"
    if change < 0:
        return "down"
    return "flat"


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _snapshot_change(snap, contract, close: float) -> Tuple[float, float]:
    """Extract index change from Shioaji snapshot fields when available."""
    ref = (
        _to_float(getattr(contract, "reference", None))
        or _to_float(getattr(snap, "reference_price", None))
        or 0.0
    )
    snap_change = _to_float(getattr(snap, "change_price", None))
    snap_pct = _to_float(getattr(snap, "change_rate", None))

    if snap_change is not None:
        change = snap_change
    elif ref:
        change = close - ref
    elif snap_pct is not None and snap_pct != -100:
        previous = close / (1 + snap_pct / 100.0)
        change = close - previous
    else:
        change = 0.0

    if snap_pct is not None:
        pct = snap_pct
    elif ref:
        pct = change / ref * 100.0
    else:
        previous = close - change
        pct = change / previous * 100.0 if previous else 0.0

    return change, pct


# ── Local indices (Shioaji) ────────────────────────────────────────
# (label, contract_kind, market_or_none, symbol)
# contract_kind: "Indexs" | "Stocks" | "Futures"
_LOCAL_INDEX_DEFS: List[Tuple[str, str, Optional[str], str]] = [
    ("加權", "Indexs",  "TSE", "001"),
    ("櫃買", "Indexs",  "OTC", "101"),
    ("台50", "Stocks",  None,  "0050"),
    ("台指近",   "Futures", None, "TXFR1"),
]

# ── Foreign indices (yfinance) ─────────────────────────────────────
# (label, yfinance_symbol)
_FOREIGN_INDEX_DEFS: List[Tuple[str, str]] = [
    ("美元", "TWD=X"),
    ("金價", "GC=F"),
    ("WTI",  "CL=F"),
    ("VIX",  "^VIX"),
    ("S&P 500",  "^GSPC"),
    ("納斯達克", "^IXIC"),
    ("費半",     "^SOX"),
]


class IndexFetcher:
    """Composite fetcher for the MarketStrip ribbon."""

    FOREIGN_TTL = 30.0   # seconds — yfinance polled at the 30s callback rate
    # ^TWII minute-amount delta window. A single 30s callback won't span a
    # full minute, so we keep ~3 samples and pick the oldest within 90s.
    TWII_AMOUNT_WINDOW = 90.0

    # Streaming tick cache freshness window. Tick callbacks update entries
    # in real time; if the latest tick is older than this we fall back to
    # the `snapshots()` REST path so the ribbon stays accurate on illiquid
    # symbols or after a session drop.
    STREAM_CACHE_TTL = 30.0

    def __init__(self) -> None:
        self._foreign_cache: List[MarketIndexEntry] = []
        self._foreign_at: float = 0.0
        # Lazy-imported on first use; None signals yfinance isn't available
        # at runtime (e.g. dev env without the package installed).
        self._yf = None
        # Rolling log of (monotonic_ts, total_amount_TWD) for ^TWII.
        self._twii_amount_log: Deque[Tuple[float, float]] = deque(maxlen=8)
        # Streaming tick cache for local indices/futures.
        # Key = def_symbol (e.g. "001", "TXFR1"); value = (entry, monotonic_ts)
        self._stream_cache: Dict[str, Tuple[MarketIndexEntry, float]] = {}
        self._stream_lock = threading.RLock()
        self._subscribed: bool = False
        # Tick events arrive with the underlying contract's code (e.g. continuous
        # futures TXFR1 resolves to TXFL5/TXFM5 for the current month). Map the
        # delivered code back to the def symbol so cache lookups stay stable.
        self._code_to_def: Dict[str, str] = {}

    # ── Public ──────────────────────────────────────────────────────

    def fetch_local(self, shioaji_fetcher) -> List[MarketIndexEntry]:
        if not shioaji_fetcher or not getattr(shioaji_fetcher, "is_connected", False):
            return []
        api = getattr(shioaji_fetcher, "api", None)
        if api is None:
            return []

        # Streaming subscribe is idempotent; called every fetch in case the
        # Shioaji session reconnected and lost prior subscriptions.
        self.subscribe_streams(shioaji_fetcher)

        now = time.monotonic()
        out: List[MarketIndexEntry] = []
        for label, kind, market, sym in _LOCAL_INDEX_DEFS:
            # Fast path: streaming cache hit + fresh.
            with self._stream_lock:
                cached = self._stream_cache.get(sym)
            if cached and (now - cached[1]) < self.STREAM_CACHE_TTL:
                out.append(cached[0])
                continue

            # Cold path: snapshot REST.
            try:
                contract = self._resolve_contract(api, kind, market, sym)
                if contract is None:
                    logger.debug("Local index contract missing: %s/%s/%s", kind, market, sym)
                    continue
                snaps = api.snapshots([contract])
                if not snaps:
                    continue
                snap = snaps[0]
                close = float(getattr(snap, "close", 0) or 0)
                if close <= 0:
                    continue
                change, pct = _snapshot_change(snap, contract, close)
                direction_basis = change if change != 0 else pct
                # Baseline for the card's sub-line:
                #  * Futures — use the contract's `reference` (前一交易日結算價).
                #    `snap.open` for dual-session futures may return the
                #    day-session open even while the night session is active,
                #    yielding a confusing 14-hour delta.
                #  * Indexs / Stocks — single-session, so today's `snap.open`
                #    is the correct intraday baseline.
                if kind == "Futures":
                    open_price = (
                        _to_float(getattr(contract, "reference", None))
                        or _to_float(getattr(snap, "reference_price", None))
                        or 0.0
                    )
                else:
                    open_price = _to_float(getattr(snap, "open", None)) or 0.0
                entry = MarketIndexEntry(
                    label=label, symbol=sym,
                    value=close, change=change, pct=pct,
                    direction=_direction(direction_basis),
                    open_price=open_price,
                )
                out.append(entry)
                # Seed stream cache so subsequent ticks update an existing
                # entry instead of arriving cold.
                with self._stream_lock:
                    self._stream_cache[sym] = (entry, now)
                # Record ^TWII running total_amount (TWD) for the
                # `near-1-min trade amount` ribbon tail.
                if label == "加權":
                    amt = float(
                        getattr(snap, "total_amount", 0)
                        or getattr(snap, "amount", 0)
                        or 0
                    )
                    if amt > 0:
                        self._twii_amount_log.append((time.monotonic(), amt))
            except Exception as exc:
                logger.debug("Local index %s failed: %s", label, exc)
        return out

    # ── Streaming subscriptions ─────────────────────────────────────

    def subscribe_streams(self, shioaji_fetcher) -> None:
        """Subscribe to Shioaji tick streams for all local indices/futures.

        Idempotent: noop after first successful run. Tick callbacks update
        ``_stream_cache``; ``fetch_local`` reads from cache when fresh.
        """
        if self._subscribed:
            return
        api = getattr(shioaji_fetcher, "api", None)
        if api is None:
            return
        try:
            shioaji_fetcher.register_index_tick_handler(self._on_index_tick)
        except Exception as exc:
            logger.debug("register index tick handler failed: %s", exc)
            return

        ok = True
        for label, kind, market, sym in _LOCAL_INDEX_DEFS:
            try:
                contract = self._resolve_contract(api, kind, market, sym)
                if contract is None:
                    ok = False
                    continue
                # Remember code→def mapping. For Indexs/Stocks code == sym;
                # for Futures continuous contracts the alias (TXFR1) and the
                # underlying month code (TXFE6) are both legal — Shioaji
                # subscribes the alias but pushes ticks tagged with the
                # active month code. Pre-populate both directions.
                contract_code = getattr(contract, "code", None) or sym
                self._code_to_def[contract_code] = sym
                self._code_to_def[sym] = sym

                # For Futures, enumerate every month contract under the
                # TXF root and map them all to this def. This keeps the
                # mapping correct across month rollovers without a restart.
                if kind == "Futures":
                    root = sym[:3] if len(sym) > 3 else sym
                    try:
                        group = getattr(api.Contracts.Futures, root)
                        for c in group:
                            code = getattr(c, "code", None)
                            if code:
                                self._code_to_def[code] = sym
                    except (AttributeError, TypeError) as exc:
                        logger.debug("enumerate Futures.%s failed: %s", root, exc)

                shioaji_fetcher.subscribe_index_or_future(contract, kind)
                logger.info(
                    "IndexFetcher subscribe %s: def=%s code=%s",
                    label, sym, contract_code,
                )
            except Exception as exc:
                logger.debug("subscribe %s/%s failed: %s", kind, sym, exc)
                ok = False
        if ok:
            self._subscribed = True
            logger.info(
                "IndexFetcher: streaming subscriptions active, map_size=%d",
                len(self._code_to_def),
            )

    def _on_index_tick(
        self,
        symbol: str,
        close: float,
        reference: float,
        change_price: Optional[float],
        change_rate: Optional[float],
        total_amount: Optional[float],
    ) -> None:
        """Tick callback from ShioajiFetcher — refresh stream cache.

        ``symbol`` is the code carried on the tick (may be the underlying
        month code for continuous futures); we translate via ``_code_to_def``
        back to the def symbol so the cache key stays stable across rollovers.
        """
        if close <= 0:
            return
        def_symbol = self._code_to_def.get(symbol, symbol)
        # Resolve label from defs (linear scan over ~5 entries is fine).
        label: Optional[str] = None
        for lbl, _kind, _mkt, sym in _LOCAL_INDEX_DEFS:
            if sym == def_symbol:
                label = lbl
                break
        if label is None:
            logger.debug("index tick: unknown symbol %s (def=%s)", symbol, def_symbol)
            return

        if change_price is not None:
            change = change_price
        elif reference > 0:
            change = close - reference
        elif change_rate is not None and change_rate != -100:
            previous = close / (1 + change_rate / 100.0)
            change = close - previous
        else:
            change = 0.0

        if change_rate is not None:
            pct = change_rate
        elif reference > 0:
            pct = change / reference * 100.0
        else:
            previous = close - change
            pct = (change / previous * 100.0) if previous else 0.0

        direction_basis = change if change != 0 else pct
        with self._stream_lock:
            # Inherit open_price from any previously seeded entry (snapshot
            # path populates it; tick payloads don't carry session open).
            prev = self._stream_cache.get(def_symbol)
            open_price = prev[0].open_price if prev else 0.0
        entry = MarketIndexEntry(
            label=label, symbol=def_symbol,
            value=close, change=change, pct=pct,
            direction=_direction(direction_basis),
            open_price=open_price,
        )
        with self._stream_lock:
            self._stream_cache[def_symbol] = (entry, time.monotonic())

        if label == "加權" and total_amount and total_amount > 0:
            self._twii_amount_log.append((time.monotonic(), total_amount))

    def recent_twii_minute_amount(self) -> Optional[float]:
        """Return the ^TWII trade amount (in 元) accumulated over the
        most recent ~60s window. Returns None when fewer than two samples
        exist or when the spread between samples is outside the
        TWII_AMOUNT_WINDOW guardrail.
        """
        if len(self._twii_amount_log) < 2:
            return None
        latest_ts, latest_amt = self._twii_amount_log[-1]
        # Find the oldest sample still within the window.
        for ts, amt in self._twii_amount_log:
            dt = latest_ts - ts
            if dt <= 0:
                continue
            if dt > self.TWII_AMOUNT_WINDOW:
                continue
            delta = latest_amt - amt
            if delta < 0:
                # total_amount is monotonic intra-day; a drop means a
                # session boundary or stale Shioaji frame — skip.
                return None
            # Normalise to a per-minute rate to keep the label honest
            # whether dt was 30s or 90s.
            return delta * (60.0 / dt)
        return None

    def fetch_foreign(self) -> List[MarketIndexEntry]:
        now = time.time()
        if self._foreign_cache and now - self._foreign_at < self.FOREIGN_TTL:
            return list(self._foreign_cache)

        yf = self._get_yfinance()
        if yf is None:
            return list(self._foreign_cache)  # last-good or empty

        try:
            symbols = " ".join(sym for _, sym in _FOREIGN_INDEX_DEFS)
            tickers = yf.Tickers(symbols)
            data = tickers.history(period="2d", interval="1d", progress=False)
        except Exception as exc:
            logger.warning("yfinance batch fetch failed: %s", exc)
            return list(self._foreign_cache)

        out: List[MarketIndexEntry] = []
        for label, sym in _FOREIGN_INDEX_DEFS:
            try:
                closes = data["Close"][sym].dropna()
                if closes.empty:
                    continue
                last = float(closes.iloc[-1])
                prev = float(closes.iloc[-2]) if len(closes) >= 2 else last
                change = last - prev
                pct = (change / prev * 100.0) if prev else 0.0
                # Industry convention for foreign indices (daily bars) is
                # "change vs previous-session close" — Yahoo, Bloomberg,
                # Google all show this. Park `prev` in the open_price slot
                # so the card's sub-line renders the same comparison.
                # The session-open semantic only applies to local intraday
                # streams (TXFR1, 加權, 櫃買).
                out.append(MarketIndexEntry(
                    label=label, symbol=sym,
                    value=last, change=change, pct=pct,
                    direction=_direction(change),
                    open_price=prev,
                ))
            except Exception as exc:
                logger.debug("yfinance symbol %s parse failed: %s", sym, exc)

        if out:
            self._foreign_cache = out
            self._foreign_at = now
        return list(self._foreign_cache)

    # ── Internals ───────────────────────────────────────────────────

    def _resolve_contract(self, api, kind: str, market: Optional[str], symbol: str):
        if kind == "Stocks":
            try:
                return api.Contracts.Stocks[symbol]
            except (KeyError, AttributeError):
                return None
        if kind == "Indexs":
            try:
                indexs = api.Contracts.Indexs
                sub = getattr(indexs, market) if market else indexs
                return sub[symbol]
            except (KeyError, AttributeError):
                return None
        if kind == "Futures":
            try:
                futures = api.Contracts.Futures
                # Direct dict-style lookup first (TXFR1/TXFR2 continuous codes),
                # then attribute-style for TXF root + month suffix codes (e.g. TXF8).
                try:
                    return futures[symbol]
                except (KeyError, TypeError, AttributeError):
                    pass
                # TXF root → enumerate child contracts and match by code suffix.
                root = symbol[:3] if len(symbol) > 3 else symbol
                try:
                    group = getattr(futures, root)
                except AttributeError:
                    return None
                for c in group:
                    if getattr(c, "code", None) == symbol:
                        return c
                return None
            except (KeyError, AttributeError):
                return None
        return None

    def _get_yfinance(self):
        if self._yf is not None:
            return self._yf
        try:
            import yfinance as yf  # type: ignore
            self._yf = yf
            return yf
        except ImportError:
            logger.warning("yfinance not installed — foreign indices disabled")
            return None
