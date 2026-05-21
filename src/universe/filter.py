"""TASK-U01 placeholder — implementation lands in GREEN."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class StockMeta:
    stock_id: str
    name: str
    listing_date: date
    is_etn: bool = False
    is_warning: bool = False
    is_disposition: bool = False
    is_full_delivery: bool = False
    is_warrant: bool = False


def filter_universe(
    target_date: date,
    candidates: list[str],
    daily_data: dict[str, pd.DataFrame],
    stock_meta: dict[str, StockMeta],
) -> list[str]:
    raise NotImplementedError("TASK-U01 GREEN not implemented yet")
