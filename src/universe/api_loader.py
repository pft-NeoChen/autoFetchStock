"""R3a — TWSE / TPEx OpenAPI loaders for full listed + delisted universe.

V2 §0.2 calls for a survivorship-bias-free universe. The first version
relied on a hand-picked 39-stock list; this loader pulls the live
listed-company directory plus the historical delisted record so the
universe filter can run over the full TWSE+TPEx market.

Endpoints (probed 2026-05-24):
* TWSE listed     — ``https://openapi.twse.com.tw/v1/opendata/t187ap03_L``
* TWSE 終止上市    — ``https://openapi.twse.com.tw/v1/company/suspendListingCsvAndHtml``
* TPEx listed     — ``https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O``
* TPEx 終止上櫃    — **no public endpoint** (skip; document caveat)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, List, Optional

import requests

from src.universe.filter import StockMeta

__all__ = [
    "DelistedRecord",
    "TWSE_DELISTED_URL",
    "TWSE_LISTED_URL",
    "TPEX_LISTED_URL",
    "fetch_tpex_listed",
    "fetch_twse_delisted",
    "fetch_twse_listed",
    "parse_minguo_date",
]


logger = logging.getLogger("autofetchstock.universe.api_loader")

TWSE_LISTED_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TWSE_DELISTED_URL = "https://openapi.twse.com.tw/v1/company/suspendListingCsvAndHtml"
TPEX_LISTED_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"


@dataclass(frozen=True)
class DelistedRecord:
    stock_id: str
    name: str
    delisting_date: date


def parse_minguo_date(raw: Any) -> Optional[date]:
    """Parse Taiwan ROC-calendar date strings to ``datetime.date``.

    Supports the two TWSE OpenAPI shapes:
    * ``"115/03/27"`` (slash-separated)
    * ``"1150523"`` (7-digit compact: YYYMMDD where YYY = ROC year)

    ROC year + 1911 = AD year. Returns ``None`` on parse failure.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        if "/" in s:
            year_str, month_str, day_str = s.split("/")
            year = int(year_str) + 1911
            return date(year, int(month_str), int(day_str))
        if len(s) == 7 and s.isdigit():
            year = int(s[:3]) + 1911
            return date(year, int(s[3:5]), int(s[5:7]))
        if len(s) == 8 and s.isdigit():
            # Already in AD form (e.g. "19940905" from 上市日期).
            return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except (ValueError, IndexError):
        return None
    return None


def _get_json(url: str, *, timeout: float = 10.0) -> Any:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _safe_fetch(url: str) -> List[Any]:
    try:
        data = _get_json(url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("universe fetch failed (%s): %s", url, exc)
        return []
    return data if isinstance(data, list) else []


def fetch_twse_listed() -> List[StockMeta]:
    """Return all currently-listed TWSE common stocks as ``StockMeta``."""
    out: List[StockMeta] = []
    for row in _safe_fetch(TWSE_LISTED_URL):
        if not isinstance(row, dict):
            continue
        sid = str(row.get("公司代號") or "").strip()
        if not sid:
            continue
        listing = parse_minguo_date(row.get("上市日期"))
        if listing is None:
            continue
        # Prefer 簡稱 (e.g. "台積電") over full name for downstream readability;
        # filter rules check name contains "-KY" / "F-" which both forms preserve.
        name = str(row.get("公司簡稱") or row.get("公司名稱") or "").strip()
        out.append(StockMeta(stock_id=sid, name=name, listing_date=listing))
    return out


def fetch_tpex_listed() -> List[StockMeta]:
    """Return all currently-listed TPEx common stocks as ``StockMeta``."""
    out: List[StockMeta] = []
    for row in _safe_fetch(TPEX_LISTED_URL):
        if not isinstance(row, dict):
            continue
        sid = str(row.get("SecuritiesCompanyCode") or "").strip()
        if not sid:
            continue
        listing = parse_minguo_date(row.get("Date"))
        # TPEx Date is the publication date, not listing date; we treat it as
        # an availability proxy. Bail if unparsable.
        if listing is None:
            continue
        name = str(
            row.get("CompanyAbbreviation") or row.get("CompanyName") or ""
        ).strip()
        out.append(StockMeta(stock_id=sid, name=name, listing_date=listing))
    return out


def fetch_twse_delisted() -> List[DelistedRecord]:
    """Return TWSE 終止上市 records (公開 endpoint)."""
    out: List[DelistedRecord] = []
    for row in _safe_fetch(TWSE_DELISTED_URL):
        if not isinstance(row, dict):
            continue
        sid = str(row.get("Code") or "").strip()
        if not sid:
            continue
        d = parse_minguo_date(row.get("DelistingDate"))
        if d is None:
            continue
        name = str(row.get("Company") or "").strip()
        out.append(DelistedRecord(stock_id=sid, name=name, delisting_date=d))
    return out
