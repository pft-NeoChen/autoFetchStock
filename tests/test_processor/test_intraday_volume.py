"""
Unit tests for intraday volume preparation.
"""

from datetime import time

from src.models import IntradayTick
from src.processor.data_processor import DataProcessor


def _tick(
    at: time,
    volume: int,
    accumulated_volume: int = 0,
    is_odd: bool = False,
) -> IntradayTick:
    return IntradayTick(
        time=at,
        price=100.0,
        volume=volume,
        buy_volume=float(volume),
        sell_volume=0.0,
        accumulated_volume=accumulated_volume,
        is_odd=is_odd,
    )


def test_prepare_intraday_data_derives_accumulated_volume_from_shioaji_ticks():
    processor = DataProcessor()

    df = processor.prepare_intraday_data([
        _tick(time(9, 0, 1), 10),
        _tick(time(9, 0, 2), 5),
        _tick(time(9, 0, 3), 7),
    ])

    assert df["accumulated_volume"].tolist() == [10.0, 15.0, 22.0]


def test_prepare_intraday_data_uses_source_accumulated_volume_as_anchor():
    processor = DataProcessor()

    df = processor.prepare_intraday_data([
        _tick(time(9, 0, 1), 10),
        _tick(time(9, 0, 2), 0, accumulated_volume=100),
        _tick(time(9, 0, 3), 5),
    ])

    assert df["accumulated_volume"].tolist() == [10.0, 100.0, 105.0]


def test_prepare_intraday_data_normalizes_odd_lot_before_accumulating():
    processor = DataProcessor()

    df = processor.prepare_intraday_data([
        _tick(time(9, 0, 1), 500, is_odd=True),
        _tick(time(9, 0, 2), 2),
    ])

    assert df["tick_vol_calc"].tolist() == [0.5, 2.0]
    assert df["accumulated_volume"].tolist() == [0.5, 2.5]


def test_prepare_intraday_data_normalizes_odd_lot_source_accumulated_volume():
    processor = DataProcessor()

    df = processor.prepare_intraday_data([
        _tick(time(9, 0, 1), 500, accumulated_volume=1500, is_odd=True),
    ])

    assert df["accumulated_volume"].tolist() == [1.5]
