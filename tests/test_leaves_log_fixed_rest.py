"""سجل الراحات لازم يعرض الراحة الأسبوعية الثابتة القادمة زي اليوميات بالظبط،
حتى قبل ما اليوم يتفتح وتتسجّل راحة فعلية."""
import json

SATURDAY = "2026-04-11"
NEXT_SATURDAY = "2026-04-18"
FRIDAY = "2026-04-10"


def _weekly_saved(data_file, day):
    saved = json.loads(data_file.read_text(encoding="utf-8"))
    return [lv for lv in saved["leaves"] if lv.get("person_id") == "OFF-001"
            and lv.get("type") == "أسبوعية" and lv.get("start") == day]


def _log_rows(client, person="OFF-001", day=SATURDAY):
    data = client.get("/api/bootstrap/leaves").get_json()
    return [lv for lv in data["leaves"]
            if lv["person_id"] == person and lv["type"] == "أسبوعية" and lv["start"] == day]


def test_log_shows_unregistered_fixed_rest_like_the_dailies(client, data_file, frozen_today):
    frozen_today(FRIDAY)
    rows = _log_rows(client)
    assert len(rows) == 1
    assert rows[0]["virtual"] is True and rows[0]["origin"] == "fixed_weekly"
    assert rows[0]["end"] == SATURDAY and rows[0]["return_date"] == "2026-04-12"
    assert rows[0]["name"]
    # اليومية بتعرض نفس الراحة لنفس الضابط
    row = next(r for r in client.get(f"/api/duty/{SATURDAY}").get_json()["rows"]
               if r["id"] == "OFF-001")
    assert row["leave"]["start"] == SATURDAY
    # قراءة بس — مفيش حاجة اتكتبت
    assert not _weekly_saved(data_file, SATURDAY)


def test_log_drops_the_virtual_row_once_the_day_is_registered(client, data_file, frozen_today):
    frozen_today(FRIDAY)
    client.get(f"/api/board/{SATURDAY}")
    client.post(f"/api/assignments/{SATURDAY}", json={"name": "أول تعديل", "kind": "خارجية"})
    rows = _log_rows(client)
    assert len(rows) == 1 and not rows[0].get("virtual")
    assert rows[0]["origin"] == "auto_weekly"


def test_log_does_not_duplicate_a_recorded_leave(client, data_file, frozen_today):
    frozen_today(FRIDAY)
    created = client.post("/api/leaves", json={
        "person_id": "OFF-001", "type": "أسبوعية", "start": SATURDAY, "end": SATURDAY})
    assert created.status_code == 201, created.get_json()
    rows = _log_rows(client)
    assert len(rows) == 1 and not rows[0].get("virtual")


def test_log_hides_fixed_rest_when_weekly_rest_is_suspended(client, data_file, frozen_today):
    frozen_today(FRIDAY)
    response = client.post("/api/rest-suspensions", json={
        "types": ["أسبوعية"], "reason": "تعليمات المديرية", "stop_leave_ids": []})
    assert response.status_code == 201, response.get_json()
    assert _log_rows(client) == []


def test_log_window_is_one_week(client, data_file, frozen_today):
    frozen_today(FRIDAY)
    assert _log_rows(client, day=NEXT_SATURDAY) == []
    frozen_today("2026-04-12")
    assert len(_log_rows(client, day=NEXT_SATURDAY)) == 1
