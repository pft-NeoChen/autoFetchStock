from datetime import date
import threading

from src.app.app_controller import AppController


class _InlineThread:
    def __init__(self, target, *args, **kwargs):
        self._target = target

    def start(self):
        self._target()


class _FakeChipsStorage:
    def __init__(self, snapshot_date, t86_snapshot, margin_snapshot=None):
        self.snapshot_date = snapshot_date
        self.t86_snapshot = dict(t86_snapshot)
        self.margin_snapshot = dict(margin_snapshot or {"3081": {"stock_id": "3081"}})
        self.saved_t86 = None
        self.saved_margin = None

    def latest_snapshot_date(self):
        return self.snapshot_date

    def latest_margin_date(self):
        return self.snapshot_date

    def load_t86_day(self, snapshot_date):
        assert snapshot_date == self.snapshot_date
        return dict(self.t86_snapshot)

    def save_t86_snapshot(self, snapshot_date, t86_by_stock):
        assert snapshot_date == self.snapshot_date
        self.saved_t86 = dict(t86_by_stock)
        return True

    def load_margin_day(self, snapshot_date):
        assert snapshot_date == self.snapshot_date
        return dict(self.margin_snapshot)

    def save_margin_snapshot(self, snapshot_date, margin_by_stock):
        assert snapshot_date == self.snapshot_date
        self.saved_margin = dict(margin_by_stock)
        return True


class _FakeChipsFetcher:
    def __init__(self, tpex_rows=None, tpex_margin_rows=None):
        self.tpex_rows = tpex_rows
        self.tpex_margin_rows = tpex_margin_rows
        self.requested_date = None
        self.requested_margin_date = None

    def fetch_tpex_t86(self, target_date):
        self.requested_date = target_date
        return dict(self.tpex_rows)

    def fetch_tpex_margin(self, target_date):
        self.requested_margin_date = target_date
        return dict(self.tpex_margin_rows)


def test_startup_repairs_existing_t86_snapshot_missing_tpex_rows(monkeypatch):
    monkeypatch.setattr(threading, "Thread", _InlineThread)
    snapshot_date = date(2026, 5, 8)
    controller = AppController.__new__(AppController)
    controller.chips_storage = _FakeChipsStorage(
        snapshot_date,
        {
            "2330": {
                "stock_id": "2330",
                "stock_name": "台積電",
                "foreign_net": 1,
                "trust_net": 2,
                "dealer_net": 3,
                "all_net": 6,
            }
        },
    )
    controller.chips_fetcher = _FakeChipsFetcher(
        {
            "3081": {
                "stock_id": "3081",
                "stock_name": "聯亞",
                "foreign_net": 235759,
                "trust_net": -170000,
                "dealer_net": -19424,
                "all_net": 46335,
            }
        }
    )

    controller._catchup_chips_t86()

    assert controller.chips_fetcher.requested_date == snapshot_date
    assert controller.chips_storage.saved_t86["2330"]["stock_name"] == "台積電"
    assert controller.chips_storage.saved_t86["3081"]["stock_name"] == "聯亞"


def test_t86_snapshot_with_tpex_sentinel_does_not_need_repair():
    snapshot_date = date(2026, 5, 8)
    controller = AppController.__new__(AppController)
    controller.chips_storage = _FakeChipsStorage(
        snapshot_date,
        {
            "3081": {
                "stock_id": "3081",
                "stock_name": "聯亞",
            }
        },
    )

    assert not controller._t86_snapshot_needs_tpex_repair(snapshot_date)


def test_startup_repairs_existing_margin_snapshot_missing_tpex_rows(monkeypatch):
    monkeypatch.setattr(threading, "Thread", _InlineThread)
    snapshot_date = date(2026, 5, 8)
    controller = AppController.__new__(AppController)
    controller.chips_storage = _FakeChipsStorage(
        snapshot_date,
        {"3081": {"stock_id": "3081"}},
        margin_snapshot={
            "2330": {
                "stock_id": "2330",
                "stock_name": "台積電",
                "margin_balance": 10,
                "margin_prev": 9,
                "short_balance": 1,
                "short_prev": 1,
            }
        },
    )
    controller.chips_fetcher = _FakeChipsFetcher(
        tpex_margin_rows={
            "3081": {
                "stock_id": "3081",
                "stock_name": "聯亞",
                "margin_balance": 4826,
                "margin_prev": 4830,
                "short_balance": 115,
                "short_prev": 106,
            }
        }
    )

    controller._catchup_chips_t86()

    assert controller.chips_fetcher.requested_margin_date == snapshot_date
    assert controller.chips_storage.saved_margin["2330"]["stock_name"] == "台積電"
    assert controller.chips_storage.saved_margin["3081"]["short_balance"] == 115
