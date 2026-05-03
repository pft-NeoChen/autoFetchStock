"""Tests for TWSE fundamentals parsing."""

from src.data.fundamentals import _parse_twse_iih_financial


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
