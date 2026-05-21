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

from src.models import BreadthSummary, IndustryPulseEntry, MarketIndexEntry

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

# ── Industry sub-indices (Shioaji Indexs.TSE / Indexs.OTC) ─────────
# Targets are resolved at runtime by scanning each market's Indexs group
# and matching ``contract.name`` against the keyword list. OTC subindex
# codes don't match TSE numbering and can renumber between sessions, so
# discovery beats hardcoded codes.
#   (display_label, market, list_of_name_keywords_any_of)
_INDUSTRY_TARGETS: List[Tuple[str, str, Tuple[str, ...]]] = [
    ("半導體", "TSE", ("半導體",)),
    ("通信",   "TSE", ("通信網路", "通信")),
    ("電零",   "TSE", ("電子零組件",)),
    ("半導體", "OTC", ("半導體",)),
    ("通信",   "OTC", ("通信網路", "通信")),
    ("電零",   "OTC", ("電子零組件",)),
]



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

    # Cold-start stagger: cap how many cold `snapshots()` calls we issue per
    # ribbon refresh tick (1s). 8 local indices + ~14 industries = 22 symbols
    # would burst past Shioaji's 50-per-5s quote-API limit if a busy moment
    # collides with `_scheduled_fetch` snapshots. Streaming ticks usually
    # warm the cache within 2~3s, so we trade a few seconds of cold-cell
    # values for headroom under the rate limit.
    COLD_BURST_MAX_PER_TICK: int = 4

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

        # Industry sub-index streaming. Keyed by (market, symbol).
        self._industry_cache: Dict[Tuple[str, str], Tuple[IndustryPulseEntry, float]] = {}
        self._industry_subscribed: bool = False
        # Map delivered tick code → (label, market, symbol) for industry routing.
        self._industry_code_map: Dict[str, Tuple[str, str, str]] = {}

        # Breadth (TWSE + TPEx) HTTP poll cache.
        self._breadth_cache: Dict[str, Tuple[BreadthSummary, float]] = {}
        self._breadth_lock = threading.RLock()

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
        cold_calls_this_tick = 0
        for label, kind, market, sym in _LOCAL_INDEX_DEFS:
            # Fast path: streaming cache hit + fresh.
            with self._stream_lock:
                cached = self._stream_cache.get(sym)
            if cached and (now - cached[1]) < self.STREAM_CACHE_TTL:
                out.append(cached[0])
                continue

            # Cap cold snapshot bursts per tick. Stale cache entries fall
            # through to be served next tick; brand-new cells get skipped
            # until the budget releases (stream ticks usually warm them
            # within 2~3s anyway).
            if cold_calls_this_tick >= self.COLD_BURST_MAX_PER_TICK:
                if cached:
                    out.append(cached[0])  # serve stale rather than gap
                continue
            cold_calls_this_tick += 1

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

        # Industry sub-index route — separate cache, separate model.
        ind = self._industry_code_map.get(symbol)
        if ind is not None:
            ind_label, ind_market, ind_sym = ind
            if change_rate is not None:
                pct = change_rate
            elif reference > 0:
                pct = (close - reference) / reference * 100.0
            else:
                pct = 0.0
            entry_i = IndustryPulseEntry(
                label=ind_label, market=ind_market, symbol=ind_sym,
                pct=pct, direction=_direction(pct),
            )
            self._industry_cache[(ind_market, ind_sym)] = (entry_i, time.monotonic())
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

    # ── Industry sub-index streaming ────────────────────────────────

    def _discover_industry_contracts(self, api) -> List[Tuple[str, str, str, object]]:
        """Resolve industry contracts by enumerating each market and matching
        ``contract.name`` against the keyword list. Returns list of
        (label, market, code, contract).
        """
        out: List[Tuple[str, str, str, object]] = []
        seen: set[Tuple[str, str]] = set()  # (label, market) — pick first match
        # Build per-market contract lists once.
        market_contracts: Dict[str, List[object]] = {}
        for market in ("TSE", "OTC"):
            try:
                sub = getattr(api.Contracts.Indexs, market, None)
                if sub is None:
                    continue
                market_contracts[market] = list(sub)
            except Exception as exc:
                logger.debug("enumerate Indexs.%s failed: %s", market, exc)
        for label, market, keywords in _INDUSTRY_TARGETS:
            if (label, market) in seen:
                continue
            contracts = market_contracts.get(market, [])
            for c in contracts:
                name = getattr(c, "name", None) or ""
                if not name:
                    continue
                if any(kw in name for kw in keywords):
                    code = getattr(c, "code", None)
                    if not code:
                        continue
                    out.append((label, market, code, c))
                    seen.add((label, market))
                    break
            else:
                logger.info(
                    "industry: no contract matched %s/%s keywords=%s",
                    market, label, keywords,
                )
        return out

    def subscribe_industries(self, shioaji_fetcher) -> None:
        """Subscribe Shioaji ticks for TSE/OTC industry sub-indices.

        Idempotent: noop after first successful run. Resolves codes by
        name-keyword discovery so Sinopac code renumbering doesn't break.
        """
        if self._industry_subscribed:
            return
        api = getattr(shioaji_fetcher, "api", None)
        if api is None:
            return
        try:
            shioaji_fetcher.register_index_tick_handler(self._on_index_tick)
        except Exception as exc:
            logger.debug("register index tick handler (industry) failed: %s", exc)
            return

        discovered = self._discover_industry_contracts(api)
        if not discovered:
            return  # leave _industry_subscribed False so we retry next tick
        for label, market, code, contract in discovered:
            try:
                self._industry_code_map[code] = (label, market, code)
                shioaji_fetcher.subscribe_index_or_future(contract, "Indexs")
                logger.info(
                    "IndexFetcher subscribe industry %s/%s code=%s name=%s",
                    market, label, code, getattr(contract, "name", "?"),
                )
            except Exception as exc:
                logger.debug("industry subscribe %s/%s failed: %s", market, label, exc)
        # Persist resolved (label, market, code) tuples for fetch_industries.
        self._industry_resolved = [(lbl, mkt, code) for lbl, mkt, code, _c in discovered]
        self._industry_subscribed = True

    def fetch_industries(self, shioaji_fetcher) -> List[IndustryPulseEntry]:
        """Return latest industry pulse entries (streaming-first, snapshot fallback)."""
        if not shioaji_fetcher or not getattr(shioaji_fetcher, "is_connected", False):
            return []
        api = getattr(shioaji_fetcher, "api", None)
        if api is None:
            return []
        self.subscribe_industries(shioaji_fetcher)

        resolved = getattr(self, "_industry_resolved", None) or []
        now = time.monotonic()
        out: List[IndustryPulseEntry] = []
        cold_calls_this_tick = 0
        for label, market, sym in resolved:
            key = (market, sym)
            cached = self._industry_cache.get(key)
            if cached and (now - cached[1]) < self.STREAM_CACHE_TTL:
                out.append(cached[0])
                continue
            if cold_calls_this_tick >= self.COLD_BURST_MAX_PER_TICK:
                if cached:
                    out.append(cached[0])
                continue
            cold_calls_this_tick += 1
            try:
                indexs = api.Contracts.Indexs
                sub = getattr(indexs, market, None)
                if sub is None:
                    continue
                try:
                    contract = sub[sym]
                except (KeyError, AttributeError):
                    continue
                snaps = api.snapshots([contract])
                if not snaps:
                    continue
                snap = snaps[0]
                close = float(getattr(snap, "close", 0) or 0)
                if close <= 0:
                    continue
                _change, pct = _snapshot_change(snap, contract, close)
                entry = IndustryPulseEntry(
                    label=label, market=market, symbol=sym,
                    pct=pct, direction=_direction(pct),
                )
                out.append(entry)
                self._industry_cache[key] = (entry, now)
            except Exception as exc:
                logger.debug("industry snapshot %s/%s/%s failed: %s", market, label, sym, exc)
        return out

    # ── Breadth (TWSE / TPEx HTTP poll) ─────────────────────────────

    BREADTH_TTL = 20.0   # seconds — public market-stats endpoints update slowly

    def fetch_breadth(self) -> Dict[str, BreadthSummary]:
        """Poll TWSE + TPEx market-statistic endpoints for advance/decline
        + limit-up/down counts. Cached for ``BREADTH_TTL`` seconds; on
        failure returns the last good value (or empty)."""
        now = time.monotonic()
        out: Dict[str, BreadthSummary] = {}
        for market in ("TSE", "OTC"):
            with self._breadth_lock:
                cached = self._breadth_cache.get(market)
            if cached and (now - cached[1]) < self.BREADTH_TTL:
                out[market] = cached[0]
                continue
            try:
                fresh = self._fetch_breadth_one(market)
            except Exception as exc:
                logger.debug("breadth fetch %s failed: %s", market, exc)
                fresh = None
            if fresh is not None:
                with self._breadth_lock:
                    self._breadth_cache[market] = (fresh, now)
                out[market] = fresh
            elif cached is not None:
                out[market] = cached[0]
        return out

    _BREADTH_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    }

    def _fetch_breadth_one(self, market: str) -> Optional[BreadthSummary]:
        try:
            import requests
        except ImportError:
            return None
        if market == "TSE":
            # Modern TWSE rwd JSON endpoint. Returns the MS-typed table set
            # whose 漲跌證券數合計 block carries breadth + limit counts.
            urls = [
                "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?response=json&type=MS",
            ]
        else:
            # TPEx summary endpoint exposes 上櫃股票 counts directly. Keep the
            # per-row quote endpoint as a fallback if the summary shape changes.
            urls = [
                "https://www.tpex.org.tw/web/stock/aftertrading/market_highlight/highlight_result.php?l=zh-tw&o=json",
                "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes",
            ]
        for url in urls:
            try:
                resp = requests.get(url, timeout=8.0, headers=self._BREADTH_HEADERS)
                if resp.status_code != 200:
                    logger.debug("breadth http %s status=%s", market, resp.status_code)
                    continue
                ctype = (resp.headers.get("content-type") or "").lower()
                if "json" not in ctype and not resp.text.lstrip().startswith(("{", "[")):
                    logger.debug("breadth http %s non-json content-type=%s", market, ctype)
                    continue
                payload = resp.json()
            except Exception as exc:
                logger.debug("breadth http %s: %s", market, exc)
                continue

            if market == "TSE":
                return _parse_twse_breadth(payload)
            parsed = _parse_tpex_breadth(payload)
            if parsed is not None:
                return parsed
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


# ── Breadth parsers ────────────────────────────────────────────────

def _parse_twse_breadth(payload: dict) -> Optional[BreadthSummary]:
    """Extract advance/decline + limit counts from TWSE rwd MI_INDEX response.

    Actual shape (type=MS):
      tables[N] = {
        title: "漲跌證券數合計",
        fields: ["類型", "整體市場", "股票"],
        data: [
          ["上漲(漲停)", "4,246(152)", "245(23)"],
          ["下跌(跌停)", "8,579(412)", "770(12)"],
          ["持平", "530", "56"],
          ...
        ]
      }
    We read the **股票** column (true equity breadth, excludes ETF/warrants).
    Fall back to 整體市場 when 股票 column missing.
    """
    if not isinstance(payload, dict):
        return None
    tables = payload.get("tables") or []
    if not isinstance(tables, list):
        return None

    for tbl in tables:
        if not isinstance(tbl, dict):
            continue
        title = tbl.get("title") or ""
        if "漲跌證券" not in title and "漲跌家數" not in title:
            continue
        fields = tbl.get("fields") or []
        rows = tbl.get("data") or []
        if not (isinstance(fields, list) and isinstance(rows, list) and rows):
            continue
        # Pick 股票 column index; fall back to 整體市場.
        col_idx = None
        for i, f in enumerate(fields):
            if isinstance(f, str) and "股票" in f:
                col_idx = i
                break
        if col_idx is None:
            for i, f in enumerate(fields):
                if isinstance(f, str) and "整體市場" in f:
                    col_idx = i
                    break
        if col_idx is None or col_idx < 1:
            col_idx = 1

        adv = dec = unch = lim_up = lim_down = 0
        for row in rows:
            if not isinstance(row, list) or len(row) <= col_idx:
                continue
            name = str(row[0])
            val = str(row[col_idx])
            if "上漲" in name:
                adv, lim_up = _split_paren_pair(val)
            elif "下跌" in name:
                dec, lim_down = _split_paren_pair(val)
            elif "持平" in name or "平盤" in name:
                unch = _digit(val)
        if adv == 0 and dec == 0 and unch == 0:
            continue
        return BreadthSummary(
            market="TSE",
            advancers=adv, decliners=dec, unchanged=unch,
            limit_up=lim_up, limit_down=lim_down,
        )
    return None


def _split_paren_pair(text: str) -> Tuple[int, int]:
    """Parse '500(2)' style values into (outer, inner)."""
    text = (text or "").strip()
    if "(" in text and ")" in text:
        outer, _, rest = text.partition("(")
        inner = rest.split(")", 1)[0]
        return _digit(outer), _digit(inner)
    return _digit(text), 0


def _parse_tpex_breadth(payload) -> Optional[BreadthSummary]:
    """Extract TPEx advance/decline + limit counts.

    Preferred endpoint shape:
      tables[0] = {
        title: "上櫃股票當日彙總資訊",
        fields: [..., "上漲家數", "漲停家數", "下跌家數", "跌停家數", "平盤家數", ...],
        data: [["887", ..., "231", "23", "596", "19", "51", "9"]]
      }

    Fallback endpoint returns per-security quote rows; aggregate Change.
    """
    summary = _parse_tpex_market_highlight(payload)
    if summary is not None:
        return summary
    return _parse_tpex_quote_breadth(payload)


def _parse_tpex_market_highlight(payload) -> Optional[BreadthSummary]:
    if not isinstance(payload, dict):
        return None
    tables = payload.get("tables") or []
    if not isinstance(tables, list):
        return None

    for tbl in tables:
        if not isinstance(tbl, dict):
            continue
        fields = tbl.get("fields") or []
        rows = tbl.get("data") or []
        if not (isinstance(fields, list) and isinstance(rows, list) and rows):
            continue
        row = rows[0]
        if not isinstance(row, list):
            continue
        idx = {str(name): i for i, name in enumerate(fields)}
        required = ("上漲家數", "漲停家數", "下跌家數", "跌停家數", "平盤家數")
        if not all(name in idx and idx[name] < len(row) for name in required):
            continue
        return BreadthSummary(
            market="OTC",
            advancers=_digit(row[idx["上漲家數"]]),
            decliners=_digit(row[idx["下跌家數"]]),
            unchanged=_digit(row[idx["平盤家數"]]),
            limit_up=_digit(row[idx["漲停家數"]]),
            limit_down=_digit(row[idx["跌停家數"]]),
        )
    return None


def _parse_tpex_quote_breadth(payload) -> Optional[BreadthSummary]:
    """TPEx quote fallback: aggregate per-row Change values client-side."""
    if not isinstance(payload, list):
        return None
    adv = dec = unch = 0
    lim_up = lim_down = 0
    for row in payload:
        if not isinstance(row, dict):
            continue
        chg_raw = (
            row.get("Change")
            or row.get("change")
            or row.get("漲跌")
            or row.get("ChangePrice")
        )
        chg = _to_float(chg_raw)
        if chg is None:
            continue
        close = _to_float(row.get("Close") or row.get("close"))
        # Approx pct from Change/prev_close where prev_close = Close - Change.
        # TPEx openapi doesn't expose today's limit prices (NextLimitUp is for
        # the NEXT session). ±9.5% threshold covers the canonical ±10% band;
        # the small handful of widened-band stocks gets miscounted but the
        # macro signal stays right.
        pct_intraday = None
        if close is not None and (close - chg) > 0:
            pct_intraday = chg / (close - chg) * 100.0
        if chg > 0:
            adv += 1
            if pct_intraday is not None and pct_intraday >= 9.5:
                lim_up += 1
        elif chg < 0:
            dec += 1
            if pct_intraday is not None and pct_intraday <= -9.5:
                lim_down += 1
        else:
            unch += 1
    if adv == dec == unch == 0:
        return None
    return BreadthSummary(
        market="OTC",
        advancers=adv, decliners=dec, unchanged=unch,
        limit_up=lim_up, limit_down=lim_down,
    )


def _digit(value) -> int:
    if value is None:
        return 0
    s = str(value).replace(",", "").strip()
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return 0
