import threading

from src.scheduler.scheduler import Scheduler


def test_fetch_job_skips_when_previous_fetch_is_still_running():
    calls = []
    entered = threading.Event()
    release = threading.Event()
    scheduler = Scheduler(
        fetch_callback=lambda stock_id: _blocking_fetch(
            stock_id,
            calls,
            entered,
            release,
        )
    )

    worker = threading.Thread(target=scheduler._fetch_job, args=("2330",))
    worker.start()
    assert entered.wait(timeout=1)

    scheduler._fetch_job("2330")

    release.set()
    worker.join(timeout=1)

    assert calls == ["2330"]


def _blocking_fetch(stock_id, calls, entered, release):
    calls.append(stock_id)
    entered.set()
    release.wait(timeout=1)
