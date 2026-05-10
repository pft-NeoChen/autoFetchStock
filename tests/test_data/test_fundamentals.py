"""Tests for fundamentals parsing."""

from src.data.fundamentals import (
    _parse_mops_compare_data,
    _parse_tpex_pe_payload,
    _parse_twse_iih_financial,
)


def test_parse_twse_iih_financial_extracts_latest_snapshot():
    payload = {
        "info": {"status": "success"},
        "chart": {
            "eps": {
                "date": "2025Q4",
                "series": [{"name": "EPS", "data": [10.0, 8.0, 9.0, 12.0, 15.0]}],
            },
            "profit": {
                "date": "2025Q4",
                "series": [
                    {"name": "毛利率", "data": [40.0, 42.5]},
                    {"name": "稅後純益率", "data": [20.0, 22.0]},
                ],
            },
            "pe": {
                "date": "202604",
                "series": [{"name": "本益比", "data": [12.0, 18.0, 24.0]}],
            },
        },
    }

    snapshot = _parse_twse_iih_financial(payload)

    assert snapshot.eps_q == 15.0
    assert snapshot.eps_yoy == 50.0
    assert snapshot.gross_margin == 42.5
    assert snapshot.gm_delta == 2.5
    assert snapshot.pe == 24.0
    assert snapshot.pe_avg == 18.0
    assert snapshot.eps_period == "2025Q4"


def test_parse_twse_iih_financial_returns_empty_snapshot_on_error_status():
    snapshot = _parse_twse_iih_financial({"info": {"status": "error"}})

    assert snapshot.eps_q is None
    assert snapshot.gross_margin is None
    assert snapshot.pe is None


def test_parse_mops_compare_data_maps_indexed_points_to_categories():
    values, cats = _parse_mops_compare_data(
        {
            "xaxisList": ["2025Q3", "2025Q4", "2026Q1"],
            "graphData": [
                {
                    "data": [
                        [0, 1.2, "A"],
                        [2, 3.4, "A"],
                    ]
                }
            ],
        }
    )

    assert cats == ["2025Q3", "2025Q4", "2026Q1"]
    assert values == [1.2, None, 3.4]


def test_parse_tpex_pe_payload_extracts_target_stock():
    pe, period = _parse_tpex_pe_payload(
        {
            "tables": [
                {
                    "data": [
                        ["2330", "台積電", "25.1", "", "", "", "", "115Q1"],
                        ["3081", "聯亞", "344.28", "", "", "", "", "115Q1"],
                    ]
                }
            ]
        },
        "3081",
    )

    assert pe == 344.28
    assert period == "115Q1"
