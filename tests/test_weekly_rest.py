"""تسجيل الراحة الأسبوعية عند أول فتح لليوم، والراحة الإضافية من الكشف."""
import json

from backend import store
from tools.check_integrity import check

SATURDAY = "2026-04-11"
NEXT_SATURDAY = "2026-04-18"
FRIDAY = "2026-04-10"


def _saved(data_file):
    return json.loads(data_file.read_text(encoding="utf-8"))


def _weekly(data_file, day=None):
    rows = [lv for lv in _saved(data_file)["leaves"]
            if lv.get("person_id") == "OFF-001" and lv.get("type") == "أسبوعية"]
    return [lv for lv in rows if day is None or lv.get("start") == day]


def _suspend_weekly(client, frozen_today, today="2026-04-01"):
    frozen_today(today)
    response = client.post("/api/rest-suspensions", json={
        "types": ["أسبوعية"], "reason": "تعليمات المديرية", "stop_leave_ids": []})
    assert response.status_code == 201, response.get_json()


def test_board_first_open_registers_the_fixed_weekly_rest(client, data_file):
    response = client.get(f"/api/board/{SATURDAY}")
    assert response.status_code == 200
    client.post(f"/api/assignments/{SATURDAY}", json={"name": "أول تعديل", "kind": "خارجية"})

    leave = _weekly(data_file, SATURDAY)[0]
    assert leave["start"] == leave["end"] == SATURDAY
    assert leave["return_date"] == "2026-04-12"
    assert leave["origin"] == "auto_weekly"
    saved = _saved(data_file)
    assert saved["weekly_rest_seeded_days"][SATURDAY] is True
    event = next(c for c in saved["change_log"] if c["entity_id"] == leave["id"])
    assert event["action"] == "create" and "تلقائي" in event["text"]
    assert not any(w["kind"] == "راحة أسبوعية غير مسجلة"
                   for w in response.get_json()["warnings"])


def test_duty_first_open_registers_the_fixed_weekly_rest(client, data_file):
    response = client.get(f"/api/duty/{NEXT_SATURDAY}")
    assert response.status_code == 200
    client.post(f"/api/assignments/{NEXT_SATURDAY}", json={"name": "أول تعديل", "kind": "خارجية"})
    assert _weekly(data_file, NEXT_SATURDAY)[0]["origin"] == "auto_weekly"
    row = next(r for r in response.get_json()["rows"] if r["id"] == "OFF-001")
    assert row["leave"]["start"] == NEXT_SATURDAY


def test_other_weekday_and_closed_day_do_not_seed(client, data_file, frozen_today):
    before = {p: p.stat().st_mtime_ns for p in store.DATA_DIR.rglob("*.json")}
    assert client.get(f"/api/board/{FRIDAY}").status_code == 200
    assert {p: p.stat().st_mtime_ns for p in store.DATA_DIR.rglob("*.json")} == before
    assert not _weekly(data_file, FRIDAY)

    frozen_today("2026-04-12")
    assert client.get(f"/api/duty/{SATURDAY}").status_code == 200
    assert not _weekly(data_file, SATURDAY)
    assert SATURDAY not in _saved(data_file).get("weekly_rest_seeded_days", {})


def test_active_officer_outside_his_service_window_is_skipped(client, data_file):
    response = client.post("/api/person", json={
        "type": "officer", "name": "ضابط ينضم لاحقًا", "role": "ملازم",
        "code": "77", "phone": "010077", "join_date": "2026-04-12",
        "rest_system": "أسبوعية", "rest_day": "السبت",
    })
    assert response.status_code == 201, response.get_json()
    future_id = response.get_json()["id"]

    client.get(f"/api/board/{SATURDAY}")
    client.post(f"/api/assignments/{SATURDAY}", json={"name": "أول تعديل", "kind": "خارجية"})
    client.post(f"/api/assignments/{SATURDAY}", json={"name": "أول تعديل", "kind": "خارجية"})
    client.post(f"/api/assignments/{SATURDAY}", json={"name": "أول تعديل", "kind": "خارجية"})
    assert not any(lv.get("person_id") == future_id and lv.get("start") == SATURDAY
                   for lv in _saved(data_file)["leaves"])


def test_suspension_existing_leave_and_course_each_skip_auto_rest(
        client, data_file, frozen_today):
    _suspend_weekly(client, frozen_today)
    client.get(f"/api/board/{SATURDAY}")
    client.post(f"/api/assignments/{SATURDAY}", json={"name": "أول تعديل", "kind": "خارجية"})
    assert not _weekly(data_file, SATURDAY)
    assert _saved(data_file)["weekly_rest_seeded_days"][SATURDAY] is True

    # اختبارا التعارض والفرقة على أسبوعين مستقلين بعد فتح الوقف.
    order_id = _saved(data_file)["rest_suspensions"][0]["id"]
    assert client.post(f"/api/rest-suspensions/{order_id}/lift", json={}).status_code == 200
    existing_day = NEXT_SATURDAY
    assert client.post("/api/leaves", json={
        "person_id": "OFF-001", "type": "أسبوعية",
        "start": existing_day, "end": existing_day}).status_code == 201
    client.get(f"/api/duty/{existing_day}")
    assert len(_weekly(data_file, existing_day)) == 1

    course_day = "2026-04-25"
    course = client.post("/api/courses", json={"name": "فرقة اختبار"}).get_json()
    assert client.post("/api/course-terms", json={
        "course_id": course["id"], "officer_id": "OFF-001",
        "start": course_day, "end": course_day}).status_code == 201
    board = client.get(f"/api/board/{course_day}").get_json()
    assert not _weekly(data_file, course_day)
    assert not any(w["kind"] == "راحة أسبوعية غير مسجلة" for w in board["warnings"])


def test_deleted_auto_rest_is_not_recreated(client, data_file):
    client.get(f"/api/board/{SATURDAY}")
    client.post(f"/api/assignments/{SATURDAY}", json={"name": "أول تعديل", "kind": "خارجية"})
    leave_id = _weekly(data_file, SATURDAY)[0]["id"]
    assert client.delete(f"/api/leaves/{leave_id}").status_code == 200
    assert not _weekly(data_file, SATURDAY)

    client.get(f"/api/duty/{SATURDAY}")
    assert not _weekly(data_file, SATURDAY)


def test_extra_weekly_rest_is_future_only_and_coexists_with_auto(
        client, data_file, frozen_today):
    frozen_today("2026-04-06")
    past = client.post("/api/leaves", json={
        "person_id": "OFF-001", "type": "أسبوعية",
        "start": "2026-04-05", "end": "2026-04-05", "origin": "weekly_extra"})
    assert past.status_code == 400 and "اليوم" in past.get_json()["error"]

    fixed = client.post("/api/leaves", json={
        "person_id": "OFF-001", "type": "أسبوعية",
        "start": SATURDAY, "end": SATURDAY, "origin": "weekly_extra"})
    assert fixed.status_code == 400 and "الثابتة" in fixed.get_json()["error"]

    extra_day = FRIDAY
    extra = client.post("/api/leaves", json={
        "person_id": "OFF-001", "type": "أسبوعية",
        "start": extra_day, "end": extra_day, "origin": "weekly_extra"})
    assert extra.status_code == 201, extra.get_json()
    assert extra.get_json()["origin"] == "weekly_extra"

    client.get(f"/api/board/{SATURDAY}")
    client.post(f"/api/assignments/{SATURDAY}", json={"name": "تعديل بعد العرض", "kind": "خارجية"})
    origins = {(lv["start"], lv.get("origin")) for lv in _weekly(data_file)
               if lv["start"] >= "2026-04-06"}
    assert (extra_day, "weekly_extra") in origins
    assert (SATURDAY, "auto_weekly") in origins

    roster = client.get("/api/bootstrap/leaves_monthly").get_json()["weekly_roster"]
    row = next(r for r in roster if r["id"] == "OFF-001")
    assert row["rest_day"] == "السبت" and row["next_fixed"] == SATURDAY
    assert {(lv["start"], lv["origin"]) for lv in row["upcoming"]} >= origins
    assert check(store.assemble()) == []


def test_suspended_extra_uses_the_normal_leave_rejection(client, frozen_today):
    _suspend_weekly(client, frozen_today)
    response = client.post("/api/leaves", json={
        "person_id": "OFF-001", "type": "أسبوعية",
        "start": FRIDAY, "end": FRIDAY, "origin": "weekly_extra"})
    assert response.status_code == 409
    assert response.get_json()["suspended"] is True
