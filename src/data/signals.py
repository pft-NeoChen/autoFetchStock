"""Phase 3.6 signal stub with split sentiment/event labels.

UNUSED — not imported anywhere. Reserved for Phase 5 AI/event-detection
integration. Do NOT wire `compute_signal()` to a UI surface as-is: the
labels (`利多`, `爆量`, `成交量 vs 5日均 +180%` …) are hard-coded
narrative strings, not derived facts. Treat as a contract sketch only.
"""

from typing import Union

from src.models import RealtimeQuote, SignalEntry, StockInfo


def compute_signal(stock: Union[StockInfo, RealtimeQuote]) -> SignalEntry:
    """Build a deterministic signal from price movement.

    UNUSED stub: Phase 5 replaces this heuristic with AI/event-detection
    output. Hard-coded labels make this unsafe for production wiring.
    """
    stock_id = getattr(stock, "stock_id")
    pct_change = float(getattr(stock, "change_percent", 0.0))
    if pct_change >= 5:
        return SignalEntry(stock_id, "up", "利多", 9, "爆量", "成交量 vs 5日均 +180%")
    if pct_change <= -5:
        return SignalEntry(stock_id, "down", "利空", 8, "跳空", "跳空跌破 20MA")
    if pct_change >= 2:
        return SignalEntry(stock_id, "up", "利多", 7, "突破", "突破前高")
    return SignalEntry(stock_id, "neutral", "中性", 3, None, "")
