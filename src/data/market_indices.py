"""
Market index strip data source (Phase 3.5).

The redesigned UI ships a 28-pixel global ribbon below the header showing
seven major market indices (`MarketStrip` per design/afs/atoms.jsx). The
authoritative real source is yfinance, which is **not** currently in the
project requirements. To keep the visual contract intact while the
backend integration is deferred, this module exposes deterministic
stub data matching the reference PNG values exactly.

Swap-out point for the real implementation:
    * Add `yfinance` to requirements.txt
    * Replace `_STUB_ENTRIES` with a function that calls
      `yfinance.Tickers([...]).history(period='1d', interval='1m')`
      and computes change / pct from the latest two bars.
    * Cache the result for 30 s (the dedicated dcc.Interval already
      fires at 30 s — caching is belt-and-braces in case the callback
      runs on multiple workers in the future).
"""

from __future__ import annotations

from typing import List

from src.models import MarketIndexEntry


# STUB: deterministic values mirroring reference/04-layout-A.png and
# atoms.jsx::MarketStrip. Update when wiring real yfinance data.
_STUB_ENTRIES: List[MarketIndexEntry] = [
    MarketIndexEntry(label="加權", symbol="^TWII",   value=21485.62, change=128.40, pct=0.60,  direction="up"),
    MarketIndexEntry(label="櫃買", symbol="^TWOII",  value=248.91,   change=1.85,   pct=0.75,  direction="up"),
    MarketIndexEntry(label="台50", symbol="0050.TW", value=195.20,   change=1.40,   pct=0.72,  direction="up"),
    MarketIndexEntry(label="美元", symbol="DX-Y.NYB",value=31.485,   change=-0.025, pct=-0.08, direction="down"),
    MarketIndexEntry(label="金價", symbol="GC=F",    value=7182.0,   change=22.0,   pct=0.31,  direction="up"),
    MarketIndexEntry(label="WTI",  symbol="CL=F",    value=82.35,    change=-0.42,  pct=-0.51, direction="down"),
    MarketIndexEntry(label="VIX",  symbol="^VIX",    value=14.82,    change=-0.21,  pct=-1.40, direction="down"),
]


def fetch_market_strip() -> List[MarketIndexEntry]:
    """Return current MarketStrip rows. STUB until yfinance is wired in."""
    return list(_STUB_ENTRIES)


def market_strip_tail() -> str:
    """Right-aligned summary string (近 1 分鐘成交)."""
    # STUB: real value would come from ^TWII volume delta.
    return "近1分鐘成交 28.4 億"
