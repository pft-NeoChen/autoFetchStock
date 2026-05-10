"""TWSE Investment Info Center fundamentals fetcher.

Source: https://wwwc.twse.com.tw/rwd/zh/IIH/company/financial?code=<stock_id>
Returns last-known EPS, gross margin, and P/E data. Missing or unsupported
stocks return an empty snapshot so the UI can render stable `--` cells.

Phase 7.4 — disk-backed cache so app restarts (typical: close after market,
reopen pre-open next day) don't trigger 5-8s blocking re-fetches on first
stock switch. Cache TTL = 18h (covers overnight); a 16:35 scheduler warmup
refreshes favorites after market close. ``stale_fallback`` is returned when
the network call fails so the UI never blank-screens just because a
single endpoint is flaky.
"""

import json
import logging
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from src.models import FundamentalsSnapshot

logger = logging.getLogger("autofetchstock.data.fundamentals")

TWSE_IIH_FINANCIAL_URL = "https://wwwc.twse.com.tw/rwd/zh/IIH/company/financial"
MOPS_COMPARE_DATA_URL = "https://mopsfin.twse.com.tw/compare/data"
TPEX_DAILY_PE_URL = "https://www.tpex.org.tw/web/stock/aftertrading/peratio_analysis/pera_result.php"
REQUEST_TIMEOUT = 8
CACHE_TTL_SECONDS = 18 * 60 * 60          # disk + memory TTL (covers overnight)
STALE_FALLBACK_MAX_SECONDS = 7 * 24 * 60 * 60  # how long to honor stale disk on net failure

_CACHE: Dict[str, Tuple[float, FundamentalsSnapshot]] = {}
_DISK_CACHE_DIR: Optional[Path] = None
_DISK_LOCK = threading.Lock()
_TZ_TAIPEI = timezone(timedelta(hours=8))


def configure_disk_cache(data_dir: str) -> None:
    """Wire up disk-backed cache. Called once during app bootstrap."""
    global _DISK_CACHE_DIR
    path = Path(data_dir) / "cache" / "fundamentals"
    path.mkdir(parents=True, exist_ok=True)
    _DISK_CACHE_DIR = path
    logger.info("fundamentals disk cache enabled: %s", path)


def _disk_path(stock_id: str) -> Optional[Path]:
    if _DISK_CACHE_DIR is None:
        return None
    safe = "".join(ch for ch in stock_id if ch.isalnum()) or "unknown"
    return _DISK_CACHE_DIR / f"{safe}.json"


def _load_from_disk(stock_id: str, *, allow_stale: bool = False) -> Optional[Tuple[float, FundamentalsSnapshot]]:
    path = _disk_path(stock_id)
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ts = float(data["ts"])
        snap_dict = data["snapshot"]
    except (json.JSONDecodeError, KeyError, OSError, TypeError, ValueError) as exc:
        logger.debug("fundamentals disk cache read failed [%s]: %s", stock_id, exc)
        return None
    age = time.time() - ts
    if not allow_stale and age >= CACHE_TTL_SECONDS:
        return None
    if allow_stale and age >= STALE_FALLBACK_MAX_SECONDS:
        return None
    try:
        snapshot = FundamentalsSnapshot(
            eps_q=snap_dict.get("eps_q"),
            eps_yoy=snap_dict.get("eps_yoy"),
            gross_margin=snap_dict.get("gross_margin"),
            gm_delta=snap_dict.get("gm_delta"),
            pe=snap_dict.get("pe"),
            pe_avg=snap_dict.get("pe_avg"),
            eps_period=str(snap_dict.get("eps_period") or ""),
            gross_margin_period=str(snap_dict.get("gross_margin_period") or ""),
            pe_period=str(snap_dict.get("pe_period") or ""),
        )
    except (TypeError, ValueError) as exc:
        logger.debug("fundamentals disk cache decode failed [%s]: %s", stock_id, exc)
        return None
    return ts, snapshot


def _save_to_disk(stock_id: str, ts: float, snapshot: FundamentalsSnapshot) -> None:
    path = _disk_path(stock_id)
    if path is None:
        return
    payload = {
        "ts": ts,
        "snapshot": {
            "eps_q": snapshot.eps_q,
            "eps_yoy": snapshot.eps_yoy,
            "gross_margin": snapshot.gross_margin,
            "gm_delta": snapshot.gm_delta,
            "pe": snapshot.pe,
            "pe_avg": snapshot.pe_avg,
            "eps_period": snapshot.eps_period,
            "gross_margin_period": snapshot.gross_margin_period,
            "pe_period": snapshot.pe_period,
        },
    }
    with _DISK_LOCK:
        try:
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            logger.debug("fundamentals disk cache write failed [%s]: %s", stock_id, exc)


def is_disk_cache_fresh(stock_id: str) -> bool:
    """Phase 7.4 — used by app bootstrap catchup to decide which favorites need refetch."""
    return _load_from_disk(stock_id) is not None


def warmup(stock_id: str, *, force: bool = False) -> bool:
    """Pre-fill cache for ``stock_id``. Returns True when network was hit.

    ``force=True`` bypasses fresh-cache short-circuit so the daily 16:35
    job replaces yesterday's data even if TTL technically still valid.
    """
    if not stock_id:
        return False
    if not force and _has_fresh_cache(stock_id):
        return False
    snapshot = _fetch_network(stock_id)
    if snapshot is not None:
        ts = time.time()
        _CACHE[stock_id] = (ts, snapshot)
        _save_to_disk(stock_id, ts, snapshot)
        return True
    return False


def _has_fresh_cache(stock_id: str) -> bool:
    cached = _CACHE.get(stock_id)
    now = time.time()
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return True
    return _load_from_disk(stock_id) is not None


def get_fundamentals(stock_id: Optional[str]) -> FundamentalsSnapshot:
    """Fetch a compact fundamentals snapshot for one stock.

    Cache layers (in order):
      1. process-level ``_CACHE`` (sub-millisecond)
      2. disk cache at ``data/cache/fundamentals/{stock_id}.json`` (TTL 18h)
      3. network (IIH + MOPS + TPEX, 5-8s blocking)

    Network failures fall back to stale disk cache (≤7 days old) so the
    UI keeps showing last-known values instead of `--`.
    """
    if not stock_id:
        return FundamentalsSnapshot()

    stock_id = str(stock_id)
    now = time.time()

    cached = _CACHE.get(stock_id)
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    disk = _load_from_disk(stock_id)
    if disk is not None:
        _CACHE[stock_id] = disk
        return disk[1]

    snapshot = _fetch_network(stock_id)
    if snapshot is None:
        stale = _load_from_disk(stock_id, allow_stale=True)
        if stale is not None:
            logger.info("fundamentals network failed for %s, using stale disk cache", stock_id)
            _CACHE[stock_id] = stale
            return stale[1]
        return FundamentalsSnapshot()

    _CACHE[stock_id] = (now, snapshot)
    _save_to_disk(stock_id, now, snapshot)
    return snapshot


def _fetch_network(stock_id: str) -> Optional[FundamentalsSnapshot]:
    """Hit IIH + MOPS + TPEX. Returns None when no endpoint produced any value."""
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
        logger.debug("fundamentals IIH fetch failed for %s: %s", stock_id, exc)

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

    if not _has_fundamental_values(snapshot):
        return None
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
