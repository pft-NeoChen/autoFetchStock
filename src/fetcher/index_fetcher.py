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


# ── Local indices (Shioaji) ────────────────────────────────────────
# (label, contract_kind, market_or_none, symbol)
_LOCAL_INDEX_DEFS: List[Tuple[str, str, Optional[str], str]] = [
    ("加權", "Indexs", "TSE", "001"),
    ("櫃買", "Indexs", "OTC", "101"),
    ("台50", "Stocks", None,  "0050"),
]

# ── Foreign indices (yfinance) ─────────────────────────────────────
# (label, yfinance_symbol)
_FOREIGN_INDEX_DEFS: List[Tuple[str, str]] = [
    ("美元", "TWD=X"),
    ("金價", "GC=F"),
    ("WTI",  "CL=F"),
    ("VIX",  "^VIX"),
]


class IndexFetcher:
    """Composite fetcher for the MarketStrip ribbon."""

    FOREIGN_TTL = 30.0   # seconds — yfinance polled at the 30s callback rate
    # ^TWII minute-amount delta window. A single 30s callback won't span a
    # full minute, so we keep ~3 samples and pick the oldest within 90s.
    TWII_AMOUNT_WINDOW = 90.0

    def __init__(self) -> None:
        self._foreign_cache: List[MarketIndexEntry] = []
        self._foreign_at: float = 0.0
        # Lazy-imported on first use; None signals yfinance isn't available
        # at runtime (e.g. dev env without the package installed).
        self._yf = None
        # Rolling log of (monotonic_ts, total_amount_TWD) for ^TWII.
        self._twii_amount_log: Deque[Tuple[float, float]] = deque(maxlen=8)

    # ── Public ──────────────────────────────────────────────────────

    def fetch_local(self, shioaji_fetcher) -> List[MarketIndexEntry]:
        if not shioaji_fetcher or not getattr(shioaji_fetcher, "is_connected", False):
            return []
        api = getattr(shioaji_fetcher, "api", None)
        if api is None:
            return []

        out: List[MarketIndexEntry] = []
        for label, kind, market, sym in _LOCAL_INDEX_DEFS:
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
                # Reference attribute lives on the contract for indices and on
                # the snapshot for stocks; try both.
                ref = float(
                    getattr(contract, "reference", 0)
                    or getattr(snap, "reference_price", 0)
                    or 0
                )
                if close <= 0:
                    continue
                change = close - ref if ref else 0.0
                pct = (change / ref * 100.0) if ref else 0.0
                out.append(MarketIndexEntry(
                    label=label, symbol=sym,
                    value=close, change=change, pct=pct,
                    direction=_direction(change),
                ))
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
                out.append(MarketIndexEntry(
                    label=label, symbol=sym,
                    value=last, change=change, pct=pct,
                    direction=_direction(change),
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
