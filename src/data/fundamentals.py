"""TWSE Investment Info Center fundamentals fetcher.

Source: https://wwwc.twse.com.tw/rwd/zh/IIH/company/financial?code=<stock_id>
Returns last-known EPS, gross margin, and P/E data. Missing or unsupported
stocks return an empty snapshot so the UI can render stable `--` cells.
"""

import logging
import time
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

from src.models import FundamentalsSnapshot

logger = logging.getLogger("autofetchstock.data.fundamentals")

TWSE_IIH_FINANCIAL_URL = "https://wwwc.twse.com.tw/rwd/zh/IIH/company/financial"
MOPS_COMPARE_DATA_URL = "https://mopsfin.twse.com.tw/compare/data"
TPEX_DAILY_PE_URL = "https://www.tpex.org.tw/web/stock/aftertrading/peratio_analysis/pera_result.php"
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

    if not _has_fundamental_values(snapshot):
        snapshot = _fetch_mops_fundamentals(stock_id)

    if snapshot.pe is None:
        pe, pe_period = _fetch_tpex_pe(stock_id)
        if pe is not None:
            snapshot = FundamentalsSnapshot(
                eps_q=snapshot.eps_q,
                eps_yoy=snapshot.eps_yoy,
                gross_margin=snapshot.gross_margin,
                gm_delta=snapshot.gm_delta,
                pe=pe,
                pe_avg=snapshot.pe_avg,
                eps_period=snapshot.eps_period,
                gross_margin_period=snapshot.gross_margin_period,
                pe_period=pe_period,
            )

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

    eps_cats = _categories_or_empty(eps_chart)
    profit_cats = _categories_or_empty(profit_chart)
    pe_cats = _categories_or_empty(pe_chart)

    # IIH fills the unreported current quarter with 0 — skip zeros so the
    # "latest reported quarter" label/value stay aligned (上一季回退邏輯).
    eps_q, eps_idx = _last_nonzero_with_index(eps_values)
    gross_margin, gm_idx = _last_nonzero_with_index(gross_values)
    pe, pe_idx = _last_nonzero_with_index(pe_values)

    pe_avg = _avg([v for v in pe_values if (_to_float(v) or 0) > 0])

    # YoY: same quarter one year ago = picked_idx - 4 in quarterly cats.
    prev_year_eps = None
    if eps_idx is not None and eps_idx - 4 >= 0:
        prev_year_eps = _to_float(eps_values[eps_idx - 4])
    eps_yoy = None
    if eps_q is not None and prev_year_eps not in (None, 0):
        eps_yoy = (eps_q - prev_year_eps) / abs(prev_year_eps) * 100

    # GM delta: previous quarter (idx - 1) for QoQ change.
    prev_gross_margin = None
    if gm_idx is not None and gm_idx - 1 >= 0:
        prev_gross_margin = _to_float(gross_values[gm_idx - 1])
    gm_delta = None
    if gross_margin is not None and prev_gross_margin is not None:
        gm_delta = gross_margin - prev_gross_margin

    eps_period = eps_cats[eps_idx] if (eps_idx is not None and eps_idx < len(eps_cats)) else str(eps_chart.get("date") or "")
    gm_period = profit_cats[gm_idx] if (gm_idx is not None and gm_idx < len(profit_cats)) else str(profit_chart.get("date") or "")
    pe_period = pe_cats[pe_idx] if (pe_idx is not None and pe_idx < len(pe_cats)) else str(pe_chart.get("date") or "")

    return FundamentalsSnapshot(
        eps_q=eps_q,
        eps_yoy=eps_yoy,
        gross_margin=gross_margin,
        gm_delta=gm_delta,
        pe=pe,
        pe_avg=pe_avg,
        eps_period=str(eps_period),
        gross_margin_period=str(gm_period),
        pe_period=str(pe_period),
    )


def _fetch_mops_fundamentals(stock_id: str) -> FundamentalsSnapshot:
    """Fallback fundamentals source covering TWSE + TPEX companies."""
    try:
        eps_payload = _post_mops_compare_data(stock_id, "EPS", "元")
        gross_payload = _post_mops_compare_data(stock_id, "GrossMargin", "%")
    except (ValueError, requests.RequestException) as exc:
        logger.debug("MOPS fundamentals fetch failed for %s: %s", stock_id, exc)
        return FundamentalsSnapshot()

    eps_values, eps_cats = _parse_mops_compare_data(eps_payload)
    gross_values, gross_cats = _parse_mops_compare_data(gross_payload)

    eps_q, eps_idx = _last_nonzero_with_index(eps_values)
    gross_margin, gm_idx = _last_nonzero_with_index(gross_values)

    prev_year_eps = None
    if eps_idx is not None and eps_idx - 4 >= 0:
        prev_year_eps = _to_float(eps_values[eps_idx - 4])
    eps_yoy = None
    if eps_q is not None and prev_year_eps not in (None, 0):
        eps_yoy = (eps_q - prev_year_eps) / abs(prev_year_eps) * 100

    prev_gross_margin = None
    if gm_idx is not None and gm_idx - 1 >= 0:
        prev_gross_margin = _to_float(gross_values[gm_idx - 1])
    gm_delta = None
    if gross_margin is not None and prev_gross_margin is not None:
        gm_delta = gross_margin - prev_gross_margin

    eps_period = eps_cats[eps_idx] if (eps_idx is not None and eps_idx < len(eps_cats)) else ""
    gm_period = gross_cats[gm_idx] if (gm_idx is not None and gm_idx < len(gross_cats)) else ""

    return FundamentalsSnapshot(
        eps_q=eps_q,
        eps_yoy=eps_yoy,
        gross_margin=gross_margin,
        gm_delta=gm_delta,
        eps_period=str(eps_period),
        gross_margin_period=str(gm_period),
    )


def _post_mops_compare_data(stock_id: str, compare_item: str, ylabel: str) -> Dict[str, Any]:
    response = requests.post(
        MOPS_COMPARE_DATA_URL,
        data={
            "compareItem": compare_item,
            "quarter": "true",
            "ylabel": ylabel,
            "ys": "0",
            "revenue": "false",
            "bcodeAvg": "false",
            "companyAvg": "false",
            "qnumber": "",
            "companyId": stock_id,
        },
        timeout=REQUEST_TIMEOUT,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": "https://mopsfin.twse.com.tw/",
            "User-Agent": "autoFetchStock/0.1",
        },
    )
    response.raise_for_status()
    return response.json()


def _parse_mops_compare_data(payload: Dict[str, Any]) -> Tuple[List[Any], List[str]]:
    cats = payload.get("xaxisList") or []
    values: List[Any] = [None] * len(cats)
    graph_data = payload.get("graphData") or []
    if not graph_data:
        return values, [str(c) for c in cats]

    for point in graph_data[0].get("data") or []:
        if not isinstance(point, list) or len(point) < 2:
            continue
        try:
            idx = int(point[0])
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(values):
            values[idx] = point[1]
    return values, [str(c) for c in cats]


def _fetch_tpex_pe(stock_id: str, max_lookback_days: int = 10) -> Tuple[Optional[float], str]:
    cur = date.today()
    for _ in range(max_lookback_days + 1):
        try:
            response = requests.get(
                TPEX_DAILY_PE_URL,
                params={"l": "zh-tw", "d": _roc_date(cur), "c": "", "s": "0,asc,0"},
                timeout=REQUEST_TIMEOUT,
                headers={
                    "Accept": "application/json",
                    "Referer": "https://www.tpex.org.tw/zh-tw/mainboard/trading/info/daily-pe.html",
                    "User-Agent": "autoFetchStock/0.1",
                },
            )
            response.raise_for_status()
            pe, period = _parse_tpex_pe_payload(response.json(), stock_id)
            if pe is not None:
                return pe, period
        except (ValueError, requests.RequestException) as exc:
            logger.debug("TPEX PE fetch failed for %s on %s: %s", stock_id, cur, exc)
        cur -= timedelta(days=1)
    return None, ""


def _parse_tpex_pe_payload(payload: Dict[str, Any], stock_id: str) -> Tuple[Optional[float], str]:
    tables = payload.get("tables") or []
    if not tables:
        return None, ""
    rows = tables[0].get("data") or []
    for row in rows:
        if not isinstance(row, list) or len(row) < 8:
            continue
        if str(row[0]).strip() != stock_id:
            continue
        return _to_float(row[2]), str(row[7]).strip()
    return None, ""


def _has_fundamental_values(snapshot: FundamentalsSnapshot) -> bool:
    return any(
        value is not None
        for value in (snapshot.eps_q, snapshot.gross_margin, snapshot.pe)
    )


def _roc_date(d: date) -> str:
    return f"{d.year - 1911}/{d.month:02d}/{d.day:02d}"


def _categories_or_empty(chart: Dict[str, Any]) -> List[str]:
    cats = chart.get("categories") or []
    return [str(c) for c in cats] if isinstance(cats, list) else []


def _last_nonzero_with_index(values: List[Any]) -> Tuple[Optional[float], Optional[int]]:
    for i in range(len(values) - 1, -1, -1):
        v = _to_float(values[i])
        if v is None or v == 0:
            continue
        return v, i
    return None, None


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
