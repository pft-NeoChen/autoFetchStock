"""
Unit tests for intraday tick storage.
"""

import json
from datetime import date

from src.storage.data_storage import DataStorage


def test_load_intraday_data_skips_ticks_from_different_timestamp_date(tmp_path):
    storage = DataStorage(data_dir=str(tmp_path))
    file_path = tmp_path / "intraday" / "2330_20260508.json"
    file_path.write_text(
        json.dumps(
            {
                "stock_id": "2330",
                "stock_name": "台積電",
                "date": "2026-05-08",
                "previous_close": 1000,
                "ticks": [
                    {
                        "time": "09:00:01",
                        "price": 1005,
                        "volume": 1,
                        "buy_volume": 1,
                        "sell_volume": 0,
                        "accumulated_volume": 1,
                        "timestamp": "2026-05-08T09:00:01",
                    },
                    {
                        "time": "14:30:00",
                        "price": 1000,
                        "volume": 10,
                        "buy_volume": 0,
                        "sell_volume": 0,
                        "accumulated_volume": 100,
                        "timestamp": "2026-05-07T14:30:00",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = storage.load_intraday_data("2330", date(2026, 5, 8))

    assert loaded is not None
    assert [tick.time.isoformat() for tick in loaded.ticks] == ["09:00:01"]
