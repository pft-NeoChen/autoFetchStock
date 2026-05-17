from types import SimpleNamespace

import pytest

from src.fetcher.index_fetcher import (
    _parse_tpex_breadth,
    _parse_twse_breadth,
    _snapshot_change,
)


def test_snapshot_change_prefers_shioaji_change_fields_without_reference():
    snap = SimpleNamespace(change_price=123.45, change_rate=0.58)
    contract = SimpleNamespace()

    change, pct = _snapshot_change(snap, contract, close=21500.0)

    assert change == pytest.approx(123.45)
    assert pct == pytest.approx(0.58)


def test_snapshot_change_falls_back_to_reference_price():
    snap = SimpleNamespace(reference_price=21400.0)
    contract = SimpleNamespace()

    change, pct = _snapshot_change(snap, contract, close=21507.0)

    assert change == pytest.approx(107.0)
    assert pct == pytest.approx(0.5)


def test_parse_twse_breadth_uses_stock_column_not_overall_market():
    payload = {
        "tables": [
            {
                "title": "漲跌證券數合計",
                "fields": ["類型", "整體市場", "股票"],
                "data": [
                    ["上漲(漲停)", "4,246(152)", "245(23)"],
                    ["下跌(跌停)", "8,579(412)", "770(12)"],
                    ["持平", "530", "56"],
                ],
            }
        ]
    }

    breadth = _parse_twse_breadth(payload)

    assert breadth is not None
    assert breadth.market == "TSE"
    assert breadth.advancers == 245
    assert breadth.limit_up == 23
    assert breadth.decliners == 770
    assert breadth.limit_down == 12
    assert breadth.unchanged == 56


def test_parse_tpex_breadth_uses_market_highlight_summary():
    payload = {
        "tables": [
            {
                "title": "上櫃股票當日彙總資訊",
                "fields": [
                    "上櫃家數",
                    "總資本額(佰萬元)",
                    "總市值(佰萬元)",
                    "本日總成交值(佰萬元)",
                    "本日總成交股數(張數)",
                    "收市指數",
                    "指數漲跌",
                    "上漲家數",
                    "漲停家數",
                    "下跌家數",
                    "跌停家數",
                    "平盤家數",
                    "未成交(含暫停交易)家數",
                ],
                "data": [
                    [
                        "887",
                        "835,248",
                        "11,207,562",
                        "319,154",
                        "1,539,121",
                        "411.18",
                        "-15.39",
                        "231",
                        "23",
                        "596",
                        "19",
                        "51",
                        "9",
                    ]
                ],
            }
        ]
    }

    breadth = _parse_tpex_breadth(payload)

    assert breadth is not None
    assert breadth.market == "OTC"
    assert breadth.advancers == 231
    assert breadth.limit_up == 23
    assert breadth.decliners == 596
    assert breadth.limit_down == 19
    assert breadth.unchanged == 51
