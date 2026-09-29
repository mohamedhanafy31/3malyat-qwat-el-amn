"""سلامة ساعة الجهاز — تحذير لو رجعت لتاريخ قبل ما شافه السيستم قبل كده
(`backend/clock.py`)، عشان القفل التلقائي مش مبني على أي حاجة متخزّنة
غير ساعة الجهاز.
"""
from datetime import date

from backend import clock


def test_first_run_ever_has_no_warning(client):
    assert clock.check(date(2026, 4, 10)) is None


def test_clock_moving_forward_has_no_warning(client):
    clock.check(date(2026, 4, 10))
    assert clock.check(date(2026, 4, 15)) is None


def test_clock_moving_backward_warns(client):
    clock.check(date(2026, 4, 15))
    warning = clock.check(date(2026, 4, 10))
    assert warning is not None
    assert "2026-04-15" in warning


def test_dashboard_bootstrap_surfaces_the_warning(client, monkeypatch):
    from datetime import date as real_date

    class FakeDate(real_date):
        @classmethod
        def today(cls):
            return real_date(2026, 4, 15)

    monkeypatch.setattr("backend.routes.meta.date", FakeDate)
    client.get("/api/bootstrap/dashboard")   # يسجّل 2026-04-15

    class OlderDate(real_date):
        @classmethod
        def today(cls):
            return real_date(2026, 4, 10)

    monkeypatch.setattr("backend.routes.meta.date", OlderDate)
    body = client.get("/api/bootstrap/dashboard").get_json()
    assert body["clock_warning"] is not None


def test_dashboard_bootstrap_has_no_warning_on_a_clean_run(client):
    body = client.get("/api/bootstrap/dashboard").get_json()
    assert body["clock_warning"] is None
