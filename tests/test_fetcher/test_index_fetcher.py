from types import SimpleNamespace

import pytest

from src.fetcher.index_fetcher import _snapshot_change


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
