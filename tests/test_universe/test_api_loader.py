"""R3a — Universe API loader tests (V2 §0.2).

TDD for TWSE / TPEx OpenAPI loaders that build full listed + delisted
universe (replacing the hand-picked 39-stock list).
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from src.universe.api_loader import (
    DelistedRecord,
    fetch_tpex_listed,
    fetch_twse_delisted,
    fetch_twse_listed,
    parse_minguo_date,
)
from src.universe.filter import StockMeta


pytestmark = pytest.mark.unit


# ── parse_minguo_date ───────────────────────────────────────────────────────


def test_parse_minguo_date_full_form() -> None:
    assert parse_minguo_date("115/03/27") == date(2026, 3, 27)


def test_parse_minguo_date_compact_form() -> None:
    assert parse_minguo_date("1150523") == date(2026, 5, 23)


def test_parse_minguo_date_invalid_returns_none() -> None:
    assert parse_minguo_date("") is None
    assert parse_minguo_date("garbage") is None


# ── fetch_twse_listed ───────────────────────────────────────────────────────


_TWSE_LISTED_FIXTURE = [
    {
        "出表日期": "1150523",
        "公司代號": "1101",
        "公司名稱": "臺灣水泥股份有限公司",
        "公司簡稱": "台泥",
        "外國企業註冊地國": "－ ",
        "產業別": "01",
        "上市日期": "19620209",
    },
    {
        "出表日期": "1150523",
        "公司代號": "2330",
        "公司名稱": "台灣積體電路製造股份有限公司",
        "公司簡稱": "台積電",
        "外國企業註冊地國": "－ ",
        "產業別": "24",
        "上市日期": "19940905",
    },
]


def test_fetch_twse_listed_returns_stock_meta(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_get_json(url: str, *, timeout: float = 10.0):
        captured["url"] = url
        return _TWSE_LISTED_FIXTURE

    monkeypatch.setattr("src.universe.api_loader._get_json", fake_get_json)
    result = fetch_twse_listed()
    assert isinstance(result, list)
    assert all(isinstance(s, StockMeta) for s in result)
    ids = {s.stock_id for s in result}
    assert ids == {"1101", "2330"}
    by_id = {s.stock_id: s for s in result}
    assert by_id["2330"].listing_date == date(1994, 9, 5)
    assert "台積電" in by_id["2330"].name
    assert captured["url"].startswith("https://openapi.twse.com.tw/")


def test_fetch_twse_listed_skips_records_with_invalid_dates(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.universe.api_loader._get_json",
        lambda url, **kw: [
            {"公司代號": "1101", "公司名稱": "ok", "上市日期": "19620209"},
            {"公司代號": "9999", "公司名稱": "bad-date", "上市日期": "INVALID"},
            {"公司代號": "", "公司名稱": "missing-id", "上市日期": "19990101"},
        ],
    )
    result = fetch_twse_listed()
    ids = {s.stock_id for s in result}
    assert ids == {"1101"}  # bad-date dropped, empty id dropped


# ── fetch_tpex_listed ───────────────────────────────────────────────────────


def test_fetch_tpex_listed_returns_stock_meta(monkeypatch) -> None:
    fixture = [
        {
            "Date": "1150523",
            "SecuritiesCompanyCode": "1240",
            "CompanyName": "茂生農經股份有限公司",
            "CompanyAbbreviation": "茂生農經",
            "SecuritiesIndustryCode": "33",
        }
    ]
    monkeypatch.setattr(
        "src.universe.api_loader._get_json", lambda url, **kw: fixture
    )
    result = fetch_tpex_listed()
    assert len(result) == 1
    assert result[0].stock_id == "1240"
    assert "茂生" in result[0].name


# ── fetch_twse_delisted ─────────────────────────────────────────────────────


def test_fetch_twse_delisted_returns_delisted_records(monkeypatch) -> None:
    fixture = [
        {"DelistingDate": "115/03/27", "Company": "晶睿", "Code": "3454"},
        {"DelistingDate": "114/10/01", "Company": "京城銀", "Code": "2809"},
    ]
    monkeypatch.setattr(
        "src.universe.api_loader._get_json", lambda url, **kw: fixture
    )
    result = fetch_twse_delisted()
    assert isinstance(result, list)
    assert all(isinstance(r, DelistedRecord) for r in result)
    by_id = {r.stock_id: r for r in result}
    assert by_id["3454"].delisting_date == date(2026, 3, 27)
    assert by_id["3454"].name == "晶睿"


def test_fetch_twse_delisted_skips_invalid(monkeypatch) -> None:
    fixture = [
        {"DelistingDate": "115/03/27", "Company": "ok", "Code": "3454"},
        {"DelistingDate": "INVALID", "Company": "bad", "Code": "9998"},
        {"DelistingDate": "115/01/01", "Company": "no-code", "Code": ""},
    ]
    monkeypatch.setattr(
        "src.universe.api_loader._get_json", lambda url, **kw: fixture
    )
    result = fetch_twse_delisted()
    assert {r.stock_id for r in result} == {"3454"}


# ── _get_json HTTP error path ───────────────────────────────────────────────


def test_fetch_twse_listed_returns_empty_on_http_failure(monkeypatch) -> None:
    def _raise(url, **kw):
        raise RuntimeError("simulated http failure")

    monkeypatch.setattr("src.universe.api_loader._get_json", _raise)
    assert fetch_twse_listed() == []
