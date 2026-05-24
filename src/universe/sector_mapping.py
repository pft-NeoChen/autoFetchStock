"""TASK-S2-SECTOR — real TWSE industry classification helpers.

Replaces the 2-digit-prefix heuristic in ``src/signals/sector_neutral.infer_sector``
with the official TWSE industry label extracted from the C_public.jsp ISIN page.

API
---
- ``parse_twse_sectors_html(html) -> dict[stock_id, industry]``
- ``fetch_twse_sectors(cache_path) -> dict[stock_id, industry]``
  Fetches the TWSE page, parses it, and persists the mapping to ``cache_path``.
- ``load_sector_mapping(cache_path, *, refresh=False) -> dict[stock_id, industry]``
  Cache-first loader; falls back to ``fetch_twse_sectors`` when missing or
  when ``refresh`` is true.
- ``get_sector(stock_id, mapping) -> str`` — lookup with ``"unknown"`` fallback.

Reference: STRATEGY_REVIEW.md §E.2
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import requests


__all__ = [
    "TWSE_ISIN_URL",
    "fetch_twse_sectors",
    "get_sector",
    "load_sector_mapping",
    "parse_twse_sectors_html",
]


TWSE_ISIN_URL = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
DEFAULT_TIMEOUT = 30.0
UNKNOWN_SECTOR = "unknown"

logger = logging.getLogger("autofetchstock.universe.sector_mapping")


# ── parsing ────────────────────────────────────────────────────────────────


_ROW_PATTERN = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL_PATTERN = re.compile(r"<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_STOCK_CELL_PATTERN = re.compile(r"^\s*(\d{4,6})\s*[　\s]+(.+?)\s*$")


def parse_twse_sectors_html(html: str) -> dict[str, str]:
    """Parse the TWSE C_public.jsp HTML into ``{stock_id: industry}``.

    The page exposes a table whose rows contain a leading placeholder cell,
    a combined "code+name" cell, ISIN, listing date, market, industry,
    CFI code, and remarks. Header / non-stock rows are skipped automatically.
    """
    mapping: dict[str, str] = {}
    for row_html in _ROW_PATTERN.findall(html):
        cells = [_strip_tags(c).strip() for c in _CELL_PATTERN.findall(row_html)]
        if len(cells) < 6:
            continue
        stock_cell = cells[1]
        match = _STOCK_CELL_PATTERN.match(stock_cell)
        if not match:
            continue
        stock_id = match.group(1)
        industry = cells[5]
        if not industry:
            continue
        mapping[stock_id] = industry
    return mapping


# ── HTTP + cache ───────────────────────────────────────────────────────────


def fetch_twse_sectors(cache_path: Path) -> dict[str, str]:
    """Fetch the TWSE page, parse it, and write the mapping to ``cache_path``."""
    logger.info("fetching TWSE sector mapping from %s", TWSE_ISIN_URL)
    response = requests.get(TWSE_ISIN_URL, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    mapping = parse_twse_sectors_html(response.text)
    _persist(cache_path, mapping)
    logger.info("fetched %d sector mappings", len(mapping))
    return mapping


def load_sector_mapping(
    cache_path: Path,
    *,
    refresh: bool = False,
) -> dict[str, str]:
    """Return the sector mapping, fetching it when missing or ``refresh`` set."""
    if refresh or not cache_path.exists():
        return fetch_twse_sectors(cache_path)
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("cache %s unreadable (%s); refetching", cache_path, exc)
        return fetch_twse_sectors(cache_path)


def get_sector(stock_id: str, mapping: dict[str, str]) -> str:
    """Look up ``stock_id``; missing or empty inputs return ``"unknown"``."""
    if not stock_id:
        return UNKNOWN_SECTOR
    return mapping.get(str(stock_id), UNKNOWN_SECTOR)


# ── internals ──────────────────────────────────────────────────────────────


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def _persist(cache_path: Path, mapping: dict[str, str]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
