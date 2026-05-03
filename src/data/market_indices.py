"""
Market index strip composer (Phase 3.5 #4).

Combines the live entries fetched by `IndexFetcher` (Shioaji for the
3 local indices, yfinance for the 4 foreign) into the 7-row payload
consumed by the MarketStrip ribbon. Per-field STUB fallback ensures
the ribbon stays whole when any single source misses.

The STUB values double as the spec's frozen reference fixture
(matches `design/afs/atoms.jsx::MarketStrip` and reference PNG).
"""

from __future__ import annotations

from typing import List, Optional

from src.models import MarketIndexEntry


# STUB fallback — matches reference/04-layout-A.png + atoms.jsx exactly.
# Order is the on-screen order; do not reorder without updating the spec.
_STUB_ENTRIES: List[MarketIndexEntry] = [
    MarketIndexEntry(label="加權", symbol="^TWII",   value=21485.62, change=128.40, pct=0.60,  direction="up"),
    MarketIndexEntry(label="櫃買", symbol="^TWOII",  value=248.91,   change=1.85,   pct=0.75,  direction="up"),
    MarketIndexEntry(label="台50", symbol="0050.TW", value=195.20,   change=1.40,   pct=0.72,  direction="up"),
    MarketIndexEntry(label="美元", symbol="TWD=X",   value=31.485,   change=-0.025, pct=-0.08, direction="down"),
    MarketIndexEntry(label="金價", symbol="GC=F",    value=7182.0,   change=22.0,   pct=0.31,  direction="up"),
    MarketIndexEntry(label="WTI",  symbol="CL=F",    value=82.35,    change=-0.42,  pct=-0.51, direction="down"),
    MarketIndexEntry(label="VIX",  symbol="^VIX",    value=14.82,    change=-0.21,  pct=-1.40, direction="down"),
]


def fetch_market_strip(
    shioaji_fetcher=None,
    index_fetcher=None,
) -> List[MarketIndexEntry]:
    """Return the 7 ribbon rows in display order.

    When `index_fetcher` is None the function returns the spec STUB
    intact — useful at app startup before Shioaji has logged in.
    """
    if index_fetcher is None:
        return list(_STUB_ENTRIES)

    by_label: dict[str, MarketIndexEntry] = {}
    try:
        for e in index_fetcher.fetch_local(shioaji_fetcher):
            by_label[e.label] = e
    except Exception:
        pass
    try:
        for e in index_fetcher.fetch_foreign():
            by_label[e.label] = e
    except Exception:
        pass

    return [by_label.get(stub.label, stub) for stub in _STUB_ENTRIES]


def market_strip_tail(index_fetcher=None) -> str:
    """Right-aligned summary string (近 1 分鐘 ^TWII 成交額).

    When `index_fetcher` is supplied and has accumulated at least two
    snapshot samples, returns a live per-minute amount in 億 (TWD).
    Falls back to the spec STUB string otherwise so the ribbon never
    blank-screens before the first sample lands.
    """
    if index_fetcher is not None:
        try:
            amt = index_fetcher.recent_twii_minute_amount()
        except Exception:
            amt = None
        if amt is not None and amt > 0:
            return f"近1分鐘成交 {amt / 1e8:.1f} 億"
    return "近1分鐘成交 28.4 億"
