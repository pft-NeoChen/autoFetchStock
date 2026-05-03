"""TWSE Investment Info Center fundamentals fetcher.

Source: https://wwwc.twse.com.tw/rwd/zh/IIH/company/financial?code=<stock_id>
Returns last-known EPS, gross margin, and P/E data. Missing or unsupported
stocks return an empty snapshot so the UI can render stable `--` cells.
"""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from src.models import FundamentalsSnapshot

logger = logging.getLogger("autofetchstock.data.fundamentals")

TWSE_IIH_FINANCIAL_URL = "https://wwwc.twse.com.tw/rwd/zh/IIH/company/financial"
REQUEST_TIMEOUT = 8
CACHE_TTL_SECONDS = 6 * 60 * 60

_CACHE: Dict[str, Tuple[float, FundamentalsSnapshot]] = {}


def get_fundamentals(stock_id: Optional[str]) -> FundamentalsSnapshot:
    """Fetch a compact fundamentals snapshot for one stock.

    Network errors and no-data responses intentionally degrade to an empty
    snapshot instead of hiding the strip.
    """
    if not stock_id:
        return FundamentalsSnapshot()

    stock_id = str(stock_id)
    cached = _CACHE.get(stock_id)
    now = time.time()
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    snapshot = FundamentalsSnapshot()
    try:
        response = requests.get(
            TWSE_IIH_FINANCIAL_URL,
            params={"code": stock_id},
            timeout=REQUEST_TIMEOUT,
            headers={
                "Accept": "application/json",
                "Referer": f"https://wwwc.twse.com.tw/IIH2/zh/company/financial.html?code={stock_id}",
                "User-Agent": "autoFetchStock/0.1",
            },
        )
        response.raise_for_status()
        payload = response.json()
        snapshot = _parse_twse_iih_financial(payload)
    except (ValueError, requests.RequestException) as exc:
        logger.debug("fundamentals fetch failed for %s: %s", stock_id, exc)

    _CACHE[stock_id] = (now, snapshot)
    return snapshot


def _parse_twse_iih_financial(payload: Dict[str, Any]) -> FundamentalsSnapshot:
    info = payload.get("info") or {}
    if info.get("status") != "success":
        return FundamentalsSnapshot()

    chart = payload.get("chart") or {}
    eps_chart = chart.get("eps") or {}
    profit_chart = chart.get("profit") or {}
    pe_chart = chart.get("pe") or {}

    eps_values = _first_series_data(eps_chart)
    gross_values = _series_data_by_name(profit_chart, "毛利率") or _series_data_at(profit_chart, 0)
    pe_values = _series_data_by_name(pe_chart, "本益比") or _series_data_at(pe_chart, 0)

    eps_q = _last_number(eps_values)
    prev_year_eps = _nth_from_end(eps_values, 5)
    gross_margin = _last_number(gross_values)
    prev_gross_margin = _nth_from_end(gross_values, 2)
    pe = _last_number(pe_values)
    pe_avg = _avg([v for v in pe_values if _to_float(v) and _to_float(v) > 0])

    eps_yoy = None
    if eps_q is not None and prev_year_eps not in (None, 0):
        eps_yoy = (eps_q - prev_year_eps) / abs(prev_year_eps) * 100

    gm_delta = None
    if gross_margin is not None and prev_gross_margin is not None:
        gm_delta = gross_margin - prev_gross_margin

    return FundamentalsSnapshot(
        eps_q=eps_q,
        eps_yoy=eps_yoy,
        gross_margin=gross_margin,
        gm_delta=gm_delta,
        pe=pe,
        pe_avg=pe_avg,
        eps_period=str(eps_chart.get("date") or ""),
        gross_margin_period=str(profit_chart.get("date") or ""),
        pe_period=str(pe_chart.get("date") or ""),
    )


def _first_series_data(chart: Dict[str, Any]) -> List[Any]:
    return _series_data_at(chart, 0)


def _series_data_at(chart: Dict[str, Any], index: int) -> List[Any]:
    series = chart.get("series") or []
    if len(series) <= index:
        return []
    data = series[index].get("data") if isinstance(series[index], dict) else []
    return data if isinstance(data, list) else []


def _series_data_by_name(chart: Dict[str, Any], name: str) -> List[Any]:
    for item in chart.get("series") or []:
        if not isinstance(item, dict):
            continue
        if item.get("name") == name:
            data = item.get("data")
            return data if isinstance(data, list) else []
    return []


def _last_number(values: List[Any]) -> Optional[float]:
    for value in reversed(values):
        parsed = _to_float(value)
        if parsed is not None:
            return parsed
    return None


def _nth_from_end(values: List[Any], n: int) -> Optional[float]:
    found = 0
    for value in reversed(values):
        parsed = _to_float(value)
        if parsed is None:
            continue
        found += 1
        if found == n:
            return parsed
    return None


def _avg(values: List[Any]) -> Optional[float]:
    parsed = [_to_float(v) for v in values]
    nums = [v for v in parsed if v is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def _to_float(value: Any) -> Optional[float]:
    if value in (None, "", "--", "-"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
