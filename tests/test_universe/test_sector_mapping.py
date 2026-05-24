"""TASK-S2-SECTOR — RED tests for src/universe/sector_mapping.py.

The implementation module does NOT exist yet.  pytest collection will raise
ImportError, confirming the RED state required before writing the module.

Seven tests:
  1. parse_twse_sectors_html — parse stock_id -> industry from TWSE C_public.jsp sample
  2. fetch_twse_sectors — HTTP path (mock requests.get)
  3. load_sector_mapping — cache hit (no network call)
  4. load_sector_mapping — cache miss -> fetch + persist
  5. load_sector_mapping(refresh=True) — force re-fetch even when cache exists
  6. get_sector — missing stock_id returns "unknown"
  7. integration — sector_neutralize works with real mapping (semiconductor + cement groups)

Reference: STRATEGY_REVIEW.md §E.2
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.universe.sector_mapping import (
    TWSE_ISIN_URL,
    fetch_twse_sectors,
    get_sector,
    load_sector_mapping,
    parse_twse_sectors_html,
)
from src.signals.sector_neutral import sector_neutralize


# ── sample HTML fixture ───────────────────────────────────────────────────────
# Minimal excerpt that mimics the real TWSE C_public.jsp table structure.
# The real page has <tr> rows where column 0 is a combined "股票代號 公司名稱"
# cell and column 3 (index 3) is the industry name.
_SAMPLE_HTML = """\
<html><body>
<table>
  <tr><td>　</td><td>有價證券代號及名稱</td><td>國際證券辨識號碼</td><td>上市日期</td><td>市場別</td><td>產業別</td><td>CFICode</td><td>備註</td></tr>
  <tr><td>　</td><td>2330　台積電</td><td>TW0002330008</td><td>1994/09/05</td><td>上市</td><td>半導體業</td><td>ESVUFR</td><td></td></tr>
  <tr><td>　</td><td>2454　聯發科</td><td>TW0002454008</td><td>2001/07/23</td><td>上市</td><td>半導體業</td><td>ESVUFR</td><td></td></tr>
  <tr><td>　</td><td>1101　台泥</td><td>TW0001101004</td><td>1962/02/09</td><td>上市</td><td>水泥工業</td><td>ESVUFR</td><td></td></tr>
  <tr><td>　</td><td>1102　亞泥</td><td>TW0001102002</td><td>1962/06/08</td><td>上市</td><td>水泥工業</td><td>ESVUFR</td><td></td></tr>
  <tr><td>　</td><td>6505　台塑化</td><td>TW0006505000</td><td>1994/12/28</td><td>上市</td><td>油電燃氣業</td><td>ESVUFR</td><td></td></tr>
</table>
</body></html>
"""

_EXPECTED_MAPPING = {
    "2330": "半導體業",
    "2454": "半導體業",
    "1101": "水泥工業",
    "1102": "水泥工業",
    "6505": "油電燃氣業",
}


# ── Test 1: parse HTML sample ─────────────────────────────────────────────────

def test_parse_twse_sectors_html():
    """parse_twse_sectors_html 從 TWSE C_public.jsp HTML 樣本中擷取 stock_id → industry。"""
    mapping = parse_twse_sectors_html(_SAMPLE_HTML)

    assert isinstance(mapping, dict)
    assert mapping["2330"] == "半導體業"
    assert mapping["2454"] == "半導體業"
    assert mapping["1101"] == "水泥工業"
    assert mapping["1102"] == "水泥工業"
    assert mapping["6505"] == "油電燃氣業"
    # Only numeric stock ids should be included (header row excluded)
    assert all(sid.isdigit() for sid in mapping)


# ── Test 2: fetch_twse_sectors via HTTP (mock) ────────────────────────────────

def test_fetch_twse_sectors_http(tmp_path: Path):
    """fetch_twse_sectors 透過 HTTP 取得資料並回傳 mapping（mock requests.get）。"""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.text = _SAMPLE_HTML

    cache_path = tmp_path / "sector_map.json"

    with patch("requests.get", return_value=mock_response) as mock_get:
        result = fetch_twse_sectors(cache_path, sources=(TWSE_ISIN_URL,))

    mock_get.assert_called_once()
    assert result["2330"] == "半導體業"
    assert result["1101"] == "水泥工業"
    # 結果應持久化到 cache_path
    assert cache_path.exists()
    persisted = json.loads(cache_path.read_text(encoding="utf-8"))
    assert persisted["2330"] == "半導體業"


# ── Test 3: load_sector_mapping — cache hit ───────────────────────────────────

def test_load_sector_mapping_cache_hit(tmp_path: Path):
    """load_sector_mapping 命中快取時不發出任何 HTTP 請求。"""
    cache_path = tmp_path / "sector_map.json"
    cache_path.write_text(
        json.dumps(_EXPECTED_MAPPING, ensure_ascii=False), encoding="utf-8"
    )

    with patch("requests.get") as mock_get:
        result = load_sector_mapping(cache_path)

    mock_get.assert_not_called()
    assert result == _EXPECTED_MAPPING


# ── Test 4: load_sector_mapping — cache miss -> fetch + persist ───────────────

def test_load_sector_mapping_cache_miss(tmp_path: Path):
    """load_sector_mapping 快取不存在時自動 fetch 並持久化。"""
    cache_path = tmp_path / "sector_map.json"
    assert not cache_path.exists()

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.text = _SAMPLE_HTML

    with patch("requests.get", return_value=mock_response):
        result = load_sector_mapping(cache_path)

    assert result["2330"] == "半導體業"
    # 持久化確認
    assert cache_path.exists()


# ── Test 5: load_sector_mapping(refresh=True) ─────────────────────────────────

def test_load_sector_mapping_force_refresh(tmp_path: Path):
    """load_sector_mapping(refresh=True) 即使快取存在也強制重新 fetch。"""
    cache_path = tmp_path / "sector_map.json"
    # 預先寫入過時快取
    stale = {"9999": "舊產業"}
    cache_path.write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.text = _SAMPLE_HTML

    with patch("requests.get", return_value=mock_response) as mock_get:
        result = load_sector_mapping(
            cache_path, refresh=True, sources=(TWSE_ISIN_URL,)
        )

    mock_get.assert_called_once()
    # 舊 key 不再存在，新資料已取代
    assert "9999" not in result
    assert result["2330"] == "半導體業"


# ── Test 6: get_sector — missing -> "unknown" ─────────────────────────────────

def test_get_sector_missing_returns_unknown():
    """get_sector 在 mapping 中查無 stock_id 時回傳 'unknown'。"""
    mapping: dict[str, str] = {"2330": "半導體業"}

    assert get_sector("2330", mapping) == "半導體業"
    assert get_sector("0000", mapping) == "unknown"
    assert get_sector("", mapping) == "unknown"


# ── Test 7: integration — sector_neutralize with real mapping ─────────────────

def test_sector_neutralize_with_real_mapping():
    """整合測試：sector_neutralize 接受真實 mapping 結構，半導體與水泥各自中性化正確。

    構造一個 (date, stock_id) MultiIndex 的 feature Series，
    驗證同 sector 內的殘差加總為 0（均值已移除）。
    """
    # 建立兩個日期、四檔股票的 feature
    dates = pd.to_datetime(["2024-01-02", "2024-01-02", "2024-01-02", "2024-01-02"])
    stock_ids = ["2330", "2454", "1101", "1102"]
    values = [0.10, 0.06, 0.03, 0.01]  # 半導體 mean=0.08, 水泥 mean=0.02

    idx = pd.MultiIndex.from_arrays([dates, stock_ids], names=["date", "stock_id"])
    feature = pd.Series(values, index=idx, name="mom")

    # 使用 get_sector 搭配真實 mapping 建立 sectors Series
    mapping = {
        "2330": "半導體業",
        "2454": "半導體業",
        "1101": "水泥工業",
        "1102": "水泥工業",
    }
    sectors = feature.index.get_level_values("stock_id").map(
        lambda sid: get_sector(sid, mapping)
    )
    sectors = pd.Series(sectors.values, index=idx, name="sector")

    neutralized = sector_neutralize(feature, sectors)

    # 同 sector 殘差加總應為 0（floating point tolerance）
    semi_mask = sectors == "半導體業"
    cement_mask = sectors == "水泥工業"

    assert abs(neutralized[semi_mask].sum()) < 1e-10, "半導體業殘差加總不為 0"
    assert abs(neutralized[cement_mask].sum()) < 1e-10, "水泥工業殘差加總不為 0"

    # 個別值驗證
    assert abs(neutralized.loc[("2024-01-02", "2330")] - 0.02) < 1e-10
    assert abs(neutralized.loc[("2024-01-02", "2454")] - (-0.02)) < 1e-10
    assert abs(neutralized.loc[("2024-01-02", "1101")] - 0.01) < 1e-10
    assert abs(neutralized.loc[("2024-01-02", "1102")] - (-0.01)) < 1e-10
