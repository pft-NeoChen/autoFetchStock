"""
TWSE chip-flow fetcher (Phase 3.5 #3).

Pulls the daily 三大法人買賣超 (T86) snapshot from TWSE's open data
endpoint, parses the variable column ordering by field-name lookup,
and returns a dict keyed by stock id.

`/fund/T86` accepts `selectType=ALL` and returns ~1700 rows per day in
a single response. We deliberately keep just one HTTP call per day —
the per-stock data set is tiny (a few KB) once stored locally.

Rate limiting mirrors `DataFetcher`: 3 s minimum gap between requests
and a 10 s timeout. The TWSE site publishes T86 after market close
(usually 16:30 Asia/Taipei); calling earlier on a trading day, or on
a weekend / holiday, returns an empty `data` array. The fetcher
exposes a `latest_available()` helper that walks back day-by-day up
to seven calendar days to find the most recent non-empty snapshot.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger("autofetchstock.chips_fetcher")


# Field aliases — TWSE has reshuffled / renamed these columns multiple
# times; we resolve each logical field via a list of acceptable header
# strings. Every key MUST resolve for a row to count as parsed.
_FIELD_ALIASES: Dict[str, List[str]] = {
    "stock_id":     ["證券代號"],
    "stock_name":   ["證券名稱"],
    "foreign_net":  [
        "外陸資買賣超股數(不含外資自營商)",
        "外資買賣超股數",
    ],
    "trust_net":    ["投信買賣超股數"],
    "dealer_net":   [
        "自營商買賣超股數",
        "自營商買賣超股數(自行買賣)",
    ],
    "all_net":      ["三大法人買賣超股數"],
}


# Margin trading (MI_MARGN) field aliases. TWSE has historically split the
# day's payload into a "融資" (margin) block and "融券" (short) block. We
# capture both balance pairs so the 籌碼 KPI cards (融資 + 融券) and the
# advisor canvas chip indicator can show real numbers.
_MARGIN_FIELD_ALIASES: Dict[str, List[str]] = {
    "stock_id":         ["股票代號", "證券代號"],
    "stock_name":       ["股票名稱", "證券名稱"],
    "margin_balance":   [
        "融資今日餘額",
        "今日餘額",
    ],
    "margin_prev":      [
        "融資前日餘額",
        "前日餘額",
    ],
    "short_balance":    [
        "融券今日餘額",
    ],
    "short_prev":       [
        "融券前日餘額",
    ],
}


class ChipsFetcher:
    """Daily institutional flow (三大法人買賣超) fetcher."""

    T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
    MARGIN_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
    REQUEST_INTERVAL = 3.0
    CONNECTION_TIMEOUT = 10

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; autoFetchStock/0.1; "
            "https://github.com/pft-NeoChen/autoFetchStock)"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    }

    def __init__(self) -> None:
        self._last_request_at: float = 0.0

    # ── Public API ──────────────────────────────────────────────────

    def fetch_t86(self, target_date: date) -> Optional[Dict[str, dict]]:
        """Fetch the T86 snapshot for `target_date`.

        Returns a dict keyed by stock id:
            { "2330": {"stock_name": "台積電",
                       "foreign_net": 12485, "trust_net": 822,
                       "dealer_net": -412, "all_net": 12895}, ... }

        Returns None on network/parse failure. Returns {} when TWSE
        accepted the request but had no data for that date (weekend,
        holiday, or pre-publish on a trading day).
        """
        params = {
            "response": "json",
            "date": target_date.strftime("%Y%m%d"),
            "selectType": "ALL",
        }
        self._respect_rate_limit()
        payload = self._get_json(self.T86_URL, params, target_date, label="T86")
        if payload is None:
            return None

        if (payload.get("stat") or "").upper() != "OK":
            logger.debug("T86 stat not OK on %s: %s", target_date, payload.get("stat"))
            return {}

        fields = payload.get("fields") or []
        rows = payload.get("data") or []
        if not fields or not rows:
            return {}

        index_map = self._resolve_field_indices(fields)
        if not index_map:
            logger.warning("T86 schema unrecognised on %s, headers=%r", target_date, fields)
            return None

        out: Dict[str, dict] = {}
        for row in rows:
            try:
                rec = self._parse_row(row, index_map)
            except Exception as exc:
                logger.debug("T86 row parse skipped: %s", exc)
                continue
            if rec is None:
                continue
            out[rec["stock_id"]] = rec
        return out

    def fetch_margin(self, target_date: date) -> Optional[Dict[str, dict]]:
        """Fetch the MI_MARGN (融資/融券) snapshot for `target_date`.

        Returns a dict keyed by stock id:
            { "2330": {"stock_name": "台積電",
                       "margin_balance": 12345,
                       "margin_prev":    12500}, ... }

        `margin_balance` and `margin_prev` are in 張 (TWSE native unit
        for this endpoint). Returns None on network/parse failure;
        returns {} when TWSE accepted the request but had no data.
        """
        params = {
            "response": "json",
            "date": target_date.strftime("%Y%m%d"),
            "selectType": "ALL",
        }
        self._respect_rate_limit()
        payload = self._get_json(self.MARGIN_URL, params, target_date, label="MI_MARGN")
        if payload is None:
            return None

        if (payload.get("stat") or "").upper() != "OK":
            logger.debug("MI_MARGN stat not OK on %s: %s", target_date, payload.get("stat"))
            return {}

        # MI_MARGN ships a multi-table envelope ("tables") or a flat
        # ("fields"/"data") shape depending on TWSE's deploy state.
        per_stock = self._select_margin_table(payload)
        if per_stock is None:
            logger.warning("MI_MARGN per-stock table not found on %s", target_date)
            return None

        fields, rows = per_stock
        index_map = self._resolve_field_indices_for(fields, _MARGIN_FIELD_ALIASES)
        if not index_map:
            logger.warning("MI_MARGN schema unrecognised on %s, headers=%r", target_date, fields)
            return None

        out: Dict[str, dict] = {}
        for row in rows:
            try:
                rec = self._parse_margin_row(row, index_map)
            except Exception as exc:
                logger.debug("MI_MARGN row parse skipped: %s", exc)
                continue
            if rec is None:
                continue
            out[rec["stock_id"]] = rec
        return out

    def latest_available(
        self,
        on_or_before: Optional[date] = None,
        max_lookback_days: int = 7,
    ) -> Optional[tuple[date, Dict[str, dict]]]:
        """Walk back day-by-day to find the most recent non-empty T86.

        Useful at startup when we don't know whether today/yesterday
        was a trading day.
        """
        cur = on_or_before or date.today()
        for _ in range(max_lookback_days + 1):
            snap = self.fetch_t86(cur)
            if snap:
                return cur, snap
            cur -= timedelta(days=1)
        return None

    # ── Internals ───────────────────────────────────────────────────

    def _get_json(
        self,
        url: str,
        params: Dict[str, str],
        target_date: date,
        *,
        label: str,
    ) -> Optional[dict]:
        """GET an endpoint expecting JSON. Returns the parsed payload, or
        None on failure.

        Catchup loops walk backwards through weekends + holidays + days
        TWSE temporarily WAFs out (HTML 307). Those are expected — log
        them at DEBUG so production logs stay readable. Reserve WARNING
        for genuinely unexpected transport failures (timeouts, 5xx, DNS).
        """
        try:
            r = requests.get(
                url,
                params=params,
                timeout=self.CONNECTION_TIMEOUT,
                headers=self.HEADERS,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            logger.warning("%s fetch failed (%s): %s", label, target_date, exc)
            return None

        # WAF block / weekend redirect — TWSE returns 307 + an HTML page
        # explaining the request was refused. Not actionable here; log at
        # debug so the catchup loop doesn't spam warnings.
        if r.status_code in (301, 302, 303, 307, 308):
            logger.debug(
                "%s redirected (%s, status=%d, ct=%s) — likely WAF / weekend",
                label, target_date, r.status_code, r.headers.get("Content-Type", ""),
            )
            return None

        if r.status_code >= 500:
            logger.warning("%s upstream %d (%s)", label, r.status_code, target_date)
            return None
        if r.status_code >= 400:
            logger.debug("%s client %d (%s)", label, r.status_code, target_date)
            return None

        ct = (r.headers.get("Content-Type") or "").lower()
        if "json" not in ct:
            logger.debug(
                "%s non-JSON response (%s, ct=%s, head=%r)",
                label, target_date, ct, r.text[:64],
            )
            return None

        try:
            return r.json()
        except ValueError as exc:
            logger.debug("%s invalid JSON (%s): %s", label, target_date, exc)
            return None

    def _respect_rate_limit(self) -> None:
        elapsed = time.time() - self._last_request_at
        if elapsed < self.REQUEST_INTERVAL:
            time.sleep(self.REQUEST_INTERVAL - elapsed)
        self._last_request_at = time.time()

    def _resolve_field_indices(self, fields: List[str]) -> Optional[Dict[str, int]]:
        return self._resolve_field_indices_for(fields, _FIELD_ALIASES)

    def _resolve_field_indices_for(
        self,
        fields: List[str],
        aliases: Dict[str, List[str]],
    ) -> Optional[Dict[str, int]]:
        # Normalise — TWSE sometimes prefixes nbsp / wraps headers in HTML.
        cleaned = [self._clean_header(f) for f in fields]
        out: Dict[str, int] = {}
        required = {"stock_id", "stock_name"}
        # T86 needs all three flow columns; MI_MARGN needs the balance cols.
        if aliases is _FIELD_ALIASES:
            required |= {"foreign_net", "trust_net", "dealer_net"}
        elif aliases is _MARGIN_FIELD_ALIASES:
            required |= {"margin_balance", "margin_prev"}
        for key, candidates in aliases.items():
            idx = next((cleaned.index(c) for c in candidates if c in cleaned), -1)
            if idx < 0:
                if key in required:
                    return None
                continue
            out[key] = idx
        return out

    def _select_margin_table(self, payload: dict):
        """Return (fields, rows) for the per-stock margin table.

        Handles both the new multi-table envelope and the legacy flat
        shape. Picks the table whose fields include 股票代號 + 融資今日餘額.
        """
        candidates: List[Tuple[List[str], list]] = []
        for tbl in payload.get("tables") or []:
            f = tbl.get("fields") or []
            d = tbl.get("data") or []
            if f and d:
                candidates.append((f, d))
        flat_fields = payload.get("fields")
        flat_data = payload.get("data")
        if flat_fields and flat_data:
            candidates.append((flat_fields, flat_data))
        for fields, rows in candidates:
            cleaned = [self._clean_header(f) for f in fields]
            has_id = any(c in cleaned for c in ("股票代號", "證券代號"))
            has_bal = any(c in cleaned for c in ("融資今日餘額", "今日餘額"))
            if has_id and has_bal:
                return fields, rows
        return None

    @staticmethod
    def _parse_margin_row(row: List, idx: Dict[str, int]) -> Optional[dict]:
        def cell(key: str) -> Optional[str]:
            i = idx.get(key, -1)
            if i < 0 or i >= len(row):
                return None
            return row[i]

        sid = (cell("stock_id") or "").strip()
        if not sid:
            return None

        def to_int(s: Optional[str]) -> int:
            if s is None:
                return 0
            try:
                return int(str(s).replace(",", "").replace(" ", "").strip() or 0)
            except (TypeError, ValueError):
                return 0

        return {
            "stock_id":       sid,
            "stock_name":     (cell("stock_name") or "").strip(),
            "margin_balance": to_int(cell("margin_balance")),
            "margin_prev":    to_int(cell("margin_prev")),
            "short_balance":  to_int(cell("short_balance")),
            "short_prev":     to_int(cell("short_prev")),
        }

    @staticmethod
    def _clean_header(s: str) -> str:
        return (s or "").replace("　", "").replace("\xa0", "").strip()

    @staticmethod
    def _parse_row(row: List, idx: Dict[str, int]) -> Optional[dict]:
        def cell(key: str) -> Optional[str]:
            i = idx.get(key, -1)
            if i < 0 or i >= len(row):
                return None
            return row[i]

        sid = (cell("stock_id") or "").strip()
        if not sid:
            return None
        name = (cell("stock_name") or "").strip()

        def to_int(s: Optional[str]) -> int:
            if s is None:
                return 0
            try:
                return int(str(s).replace(",", "").replace(" ", "").strip() or 0)
            except (TypeError, ValueError):
                return 0

        return {
            "stock_id":    sid,
            "stock_name":  name,
            "foreign_net": to_int(cell("foreign_net")),
            "trust_net":   to_int(cell("trust_net")),
            "dealer_net":  to_int(cell("dealer_net")),
            "all_net":     to_int(cell("all_net")),
        }
