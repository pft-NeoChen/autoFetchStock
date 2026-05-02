"""
Chips KPI cards data source (Phase 3.5).

Provides the 4 KPI cards displayed in the bottom data row of the
Bloomberg-style layout (外資 / 投信 / 自營 / 融資). See
design/afs/layout-variants.jsx::ChipsKpi for the visual contract.

There is currently no fetcher in this project for institutional flow,
so values are stubbed deterministically based on the reference PNG.
Swap-out point: build a real fetcher hitting TWSE chip statistics or
Shioaji broker data and shape into `ChipKpiCard` entries here.
"""

from __future__ import annotations

from typing import List, Optional

from src.models import ChipKpiCard


# STUB: matches reference/04-layout-A.png bottom row.
_STUB_CARDS: List[ChipKpiCard] = [
    ChipKpiCard(
        key="foreign",
        label="外資",
        value_text="+12,485",
        direction="up",
        caption="連3買 · 5日 +18,420",
    ),
    ChipKpiCard(
        key="trust",
        label="投信",
        value_text="+822",
        direction="up",
        caption="連2買",
    ),
    ChipKpiCard(
        key="dealer",
        label="自營",
        value_text="-412",
        direction="down",
        caption="5日 -1,820",
    ),
    ChipKpiCard(
        key="margin",
        label="融資",
        value_text="-4.2%",
        direction="up",  # 融資減 = 籌碼改善 → 視為 up
        caption="月減 · 籌碼改善",
    ),
]


def build_chips_kpi(stock_id: Optional[str] = None) -> List[ChipKpiCard]:
    """Return the 4 KPI cards for a given stock. STUB until a real
    chip-flow fetcher exists."""
    return list(_STUB_CARDS)
