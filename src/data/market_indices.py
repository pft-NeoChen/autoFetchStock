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

from typing import Dict, List, Optional

from src.models import BreadthSummary, IndustryPulseEntry, MarketIndexEntry


# STUB fallback — matches reference/04-layout-A.png + atoms.jsx exactly.
# Order is the on-screen order; do not reorder without updating the spec.
_STUB_ENTRIES: List[MarketIndexEntry] = [
    MarketIndexEntry(label="加權",      symbol="^TWII",   value=21485.62, change=128.40, pct=0.60,  direction="up",   open_price=21420.0),
    MarketIndexEntry(label="櫃買",      symbol="^TWOII",  value=248.91,   change=1.85,   pct=0.75,  direction="up",   open_price=247.50),
    MarketIndexEntry(label="台50",      symbol="0050.TW", value=195.20,   change=1.40,   pct=0.72,  direction="up",   open_price=194.10),
    MarketIndexEntry(label="台指近",    symbol="TXFR1",   value=21480.0,  change=120.0,  pct=0.56,  direction="up",   open_price=21400.0),
    MarketIndexEntry(label="美元",      symbol="TWD=X",   value=31.485,   change=-0.025, pct=-0.08, direction="down", open_price=31.510),
    MarketIndexEntry(label="金價",      symbol="GC=F",    value=7182.0,   change=22.0,   pct=0.31,  direction="up",   open_price=7165.0),
    MarketIndexEntry(label="WTI",       symbol="CL=F",    value=82.35,    change=-0.42,  pct=-0.51, direction="down", open_price=82.70),
    MarketIndexEntry(label="VIX",       symbol="^VIX",    value=14.82,    change=-0.21,  pct=-1.40, direction="down", open_price=15.00),
    MarketIndexEntry(label="S&P 500",   symbol="^GSPC",   value=5234.18,  change=12.45,  pct=0.24,  direction="up",   open_price=5225.00),
    MarketIndexEntry(label="納斯達克",  symbol="^IXIC",   value=16384.47, change=-48.32, pct=-0.29, direction="down", open_price=16420.00),
    MarketIndexEntry(label="費半",      symbol="^SOX",    value=4982.10,  change=22.85,  pct=0.46,  direction="up",   open_price=4965.00),
]

# Labels carried by the original header strip (no row movement requested).
HEADER_LABELS = {"台50", "美元", "金價", "WTI", "VIX"}
# Below-chart strip — row 1 = TWSE-session indices, row 2 = others.
BELOW_ROW1_LABELS = ["加權", "櫃買", "台指近"]
BELOW_ROW2_LABELS = ["S&P 500", "納斯達克", "費半"]


def split_strip_entries(
    entries: List[MarketIndexEntry],
) -> tuple[List[MarketIndexEntry], List[MarketIndexEntry], List[MarketIndexEntry]]:
    """Partition the 12-entry payload into (header, below_row1, below_row2)."""
    by_label = {e.label: e for e in entries}
    header = [e for e in entries if e.label in HEADER_LABELS]
    row1 = [by_label[lbl] for lbl in BELOW_ROW1_LABELS if lbl in by_label]
    row2 = [by_label[lbl] for lbl in BELOW_ROW2_LABELS if lbl in by_label]
    return header, row1, row2


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


# ── Industry pulse + breadth composers ─────────────────────────────

INDUSTRY_LABELS = ["半導體", "通信", "電零"]
INDUSTRY_MARKET_ORDER = ["TSE", "OTC"]  # TSE first per spec


def fetch_industry_pulse(
    shioaji_fetcher=None,
    index_fetcher=None,
) -> List[IndustryPulseEntry]:
    """Return industry pulse entries in display order: TSE 半導體/通信/電零,
    then OTC 半導體/通信/電零. Missing entries are silently skipped — the
    UI renders only what we have.
    """
    if index_fetcher is None or shioaji_fetcher is None:
        return []
    try:
        raw = index_fetcher.fetch_industries(shioaji_fetcher)
    except Exception:
        return []
    by_key: Dict[tuple, IndustryPulseEntry] = {(e.market, e.label): e for e in raw}
    ordered: List[IndustryPulseEntry] = []
    for market in INDUSTRY_MARKET_ORDER:
        for label in INDUSTRY_LABELS:
            entry = by_key.get((market, label))
            if entry is not None:
                ordered.append(entry)
    return ordered


def fetch_breadth_summary(index_fetcher=None) -> Dict[str, BreadthSummary]:
    """Return {market: BreadthSummary} for TSE + OTC. Empty when no fetcher."""
    if index_fetcher is None:
        return {}
    try:
        return index_fetcher.fetch_breadth()
    except Exception:
        return {}


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
