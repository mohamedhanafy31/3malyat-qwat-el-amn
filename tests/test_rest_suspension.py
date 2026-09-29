"""وقف الراحات — أمر وقف عام بأنواع راحة، وإيقاف راحة ضابط بعينها.

«النهاردة» متثبّت على 2026-03-05 في الاختبارات دي، فالأيام اللي قبله
مقفولة (`day_status`) — أي راحة بتمسّها محتاجة سبب بأثر رجعي، فالمساعد
`_leave` بيبعته دايمًا.
"""
import json
from datetime import date

import pytest

from backend import store
from backend.checks import day_warnings
from backend.duty import summarise
from backend.rest_status import officer_status, taqseera_alerts

TODAY = "2026-03-05"
RETRO = {"X-Retro-Reason": "test"}


@pytest.fixture(autouse=True)
def _today(frozen_today):
    frozen_today(TODAY)


def _leave(client, pid="OFF-002", kind="شهرية", start="2026-03-03", end="2026-03-09"):
    return client.post("/api/leaves", headers=RETRO, json={
        "person_id": pid, "type": kind, "start": start, "end": end})


def _suspend(client, types, stop=(), reason="أمر المديرية"):
    return client.post("/api/rest-suspensions", json={
        "types": list(types), "reason": reason, "stop_leave_ids": list(stop)})


def _stored(data_file):
    return json.loads(data_file.read_text())


def _find_leave(data_file, leave_id):
    return next((lv for lv in _stored(data_file)["leaves"] if lv["id"] == leave_id), None)


def _add_personnel(client):
    r = client.post("/api/person", json={
        "type": "personnel", "name": "فرد اختبار", "code": "900", "phone": "0100",
        "join_date": "2020-01-01", "role": "أمين شرطة"})
    assert r.status_code == 201, r.get_json()
    return r.get_json()["id"]


# ---------- إنشاء الأمر ----------

def test_create_validates_types_and_reason(client):
    assert _suspend(client, []).status_code == 400
    assert _suspend(client, ["نوع مخترع"]).status_code == 400
    assert _suspend(client, ["شهرية"], reason="").status_code == 400


def test_create_order_is_stored_active_from_today(client, data_file):
    r = _suspend(client, ["شهرية", "أسبوعية"])
    assert r.status_code == 201, r.get_json()
    order = r.get_json()["suspension"]
    assert order["id"] == "RS-001"
    assert order["started_on"] == TODAY and order["lifted_on"] == ""
    assert order["types"] == ["أسبوعية", "شهرية"]        # بترتيب LEAVE_TYPES
    assert _stored(data_file)["rest_suspensions"][0]["id"] == "RS-001"


def test_a_type_can_only_be_in_one_active_order(client):
    _suspend(client, ["شهرية"])
    assert _suspend(client, ["شهرية", "مرضي"]).status_code == 409
    assert _suspend(client, ["مرضي"]).status_code == 201
    assert len(client.get("/api/rest-suspensions").get_json()["active"]) == 2


def test_meta_exposes_the_suspended_types(client):
    _suspend(client, ["شهرية"])
    meta = client.get("/api/bootstrap/dashboard").get_json()["meta"]
    assert meta["rest_suspension"]["types"] == ["شهرية"]


# ---------- الرفض وقت التسجيل ----------

def test_registering_a_suspended_type_for_an_officer_is_rejected(client):
    _suspend(client, ["شهرية"])
    r = _leave(client, start="2026-03-10", end="2026-03-16")
    assert r.status_code == 409 and r.get_json()["suspended"] is True
    assert _leave(client, kind="مرضي", start="2026-03-10", end="2026-03-11").status_code == 201


def test_personnel_are_not_affected(client):
    pid = _add_personnel(client)
    _suspend(client, ["شهرية"])
    assert _leave(client, pid=pid, start="2026-03-10", end="2026-03-16").status_code == 201


def test_a_leave_that_ended_before_the_order_can_still_be_registered(client):
    _suspend(client, ["شهرية"])
    assert _leave(client, start="2026-02-01", end="2026-02-07").status_code == 201


def test_patch_that_enters_or_grows_into_the_suspension_is_rejected(client):
    lv = _leave(client, kind="مرضي", start="2026-03-10", end="2026-03-12").get_json()
    sh = _leave(client, start="2026-03-20", end="2026-03-26").get_json()
    _suspend(client, ["شهرية"])

    body = {"person_id": "OFF-002", "type": "شهرية", "start": "2026-03-10", "end": "2026-03-12"}
    assert client.patch(f"/api/leaves/{lv['id']}", json=body).status_code == 409

    grow = {**sh, "end": "2026-03-28"}
    assert client.patch(f"/api/leaves/{sh['id']}", json=grow).status_code == 409
    shrink = {**sh, "end": "2026-03-24"}
    assert client.patch(f"/api/leaves/{sh['id']}", json=shrink).status_code == 200
    assert client.patch(f"/api/leaves/{sh['id']}", json={**shrink, "note": "x"}).status_code == 200


def test_monthly_roster_shows_suspended_and_skips_blocked_rows(client):
    client.patch("/api/person/OFF-002", json={"rest_system": "شهرية"})
    client.patch("/api/person/OFF-001", json={"rest_system": "نصف شهرية"})
    _suspend(client, ["شهرية"])

    roster = client.get("/api/bootstrap/leaves_monthly").get_json()["roster"]
    row = next(r for r in roster if r["id"] == "OFF-002")
    assert row["status"] == "suspended"

    r = client.post("/api/leaves/monthly", json={"entries": [
        {"officer_id": "OFF-002", "start": "2026-03-10"},
        {"officer_id": "OFF-001", "start": "2026-03-10"}]})
    assert r.status_code == 200, r.get_json()
    out = r.get_json()
    assert [e["officer_id"] for e in out["errors"]] == ["OFF-002"]
    assert [c["person_id"] for c in out["created"]] == ["OFF-001"]


def test_blocked_monthly_row_alone_does_not_ask_for_a_retro_reason(client):
    """صف ماضي مرفوض بالوقف مايستاهلش سؤال «سبب بأثر رجعي»."""
    client.patch("/api/person/OFF-002", json={"rest_system": "شهرية"})
    _suspend(client, ["شهرية"])
    r = client.post("/api/leaves/monthly", json={"entries": [
        {"officer_id": "OFF-002", "start": "2026-03-01"}]})
    assert r.status_code == 200, r.get_json()
    assert len(r.get_json()["errors"]) == 1


# ---------- المرشّحين والإيقاف مع الأمر ----------

def test_candidates_are_officers_active_and_upcoming_of_selected_types(client):
    pid = _add_personnel(client)
    active = _leave(client).get_json()
    upcoming = _leave(client, pid="OFF-001", start="2026-03-20", end="2026-03-26").get_json()
    _leave(client, start="2026-02-01", end="2026-02-07")                       # خلصت
    _leave(client, kind="مرضي", start="2026-03-12", end="2026-03-13")          # نوع تاني
    _leave(client, pid=pid, start="2026-03-10", end="2026-03-16")              # فرد

    rows = client.get("/api/rest-suspensions/candidates?type=شهرية").get_json()["rows"]
    by_id = {r["leave_id"]: r for r in rows}
    assert set(by_id) == {active["id"], upcoming["id"]}
    assert by_id[active["id"]]["effect"] == "trim"
    assert by_id[upcoming["id"]]["effect"] == "cancel"


def test_create_with_selected_leaves_trims_active_and_cancels_upcoming(client, data_file):
    active = _leave(client).get_json()
    upcoming = _leave(client, pid="OFF-001", start="2026-03-20", end="2026-03-26").get_json()
    untouched = _leave(client, start="2026-04-01", end="2026-04-07").get_json()

    r = _suspend(client, ["شهرية"], stop=[active["id"], upcoming["id"]])
    assert r.status_code == 201, r.get_json()
    order = r.get_json()["suspension"]
    assert (order["stopped_count"], order["cancelled_count"]) == (1, 1)

    trimmed = _find_leave(data_file, active["id"])
    assert trimmed["end"] == "2026-03-04" and trimmed["return_date"] == TODAY
    assert trimmed["original_end"] == "2026-03-09" and trimmed["stopped_on"] == TODAY
    assert trimmed["stop_reason"] == "أمر المديرية" and trimmed["suspension_id"] == "RS-001"
    assert _find_leave(data_file, upcoming["id"]) is None
    assert _find_leave(data_file, untouched["id"])["end"] == "2026-04-07"   # مااختارهاش

    actions = {(c["entity"], c["action"]) for c in _stored(data_file)["change_log"]}
    assert {("leave", "stop"), ("leave", "cancel"), ("rest_suspension", "suspend")} <= actions


def test_create_is_atomic_when_a_stop_id_is_not_a_candidate(client, data_file):
    active = _leave(client).get_json()
    other = _leave(client, kind="مرضي", start="2026-03-12", end="2026-03-13").get_json()
    r = _suspend(client, ["شهرية"], stop=[active["id"], other["id"]])
    assert r.status_code == 400
    assert not _stored(data_file).get("rest_suspensions")
    assert _find_leave(data_file, active["id"])["end"] == "2026-03-09"


# ---------- إيقاف راحة ضابط واحد ----------

def _stop(client, leave_id, **body):
    body.setdefault("reason", "استدعاء")
    return client.post(f"/api/leaves/{leave_id}/stop", json=body)


def test_stop_validation(client):
    pid = _add_personnel(client)
    lv = _leave(client).get_json()
    ended = _leave(client, start="2026-02-01", end="2026-02-07").get_json()
    fard = _leave(client, pid=pid, start="2026-03-10", end="2026-03-12").get_json()

    assert _stop(client, "LV-999").status_code == 404
    assert _stop(client, lv["id"], reason="").status_code == 400
    assert _stop(client, lv["id"], on="2026-03-20").status_code == 400      # بعد النهاية
    assert _stop(client, ended["id"]).status_code == 400                     # خلصت
    assert _stop(client, fard["id"]).status_code == 400                      # فرد


def test_stop_trims_the_active_leave_and_returns_the_officer_to_the_force(client, data_file):
    lv = _leave(client).get_json()
    assert summarise(store.assemble(), TODAY)["rows"][1]["group"] == "خوارج"

    r = _stop(client, lv["id"])
    assert r.status_code == 200 and r.get_json()["cancelled"] is False
    saved = _find_leave(data_file, lv["id"])
    assert saved["end"] == "2026-03-04" and saved["original_end"] == "2026-03-09"

    row = next(x for x in summarise(store.assemble(), TODAY)["rows"] if x["id"] == "OFF-002")
    assert row["group"] != "خوارج" and row["leave"] is None
    roster = client.get(f"/api/board/{TODAY}").get_json()["roster"]["officers"]
    assert "OFF-002" in {o["id"] for o in roster}


def test_stop_on_or_before_start_cancels_the_leave(client, data_file):
    lv = _leave(client, start="2026-03-10", end="2026-03-16").get_json()
    r = _stop(client, lv["id"], on="2026-03-10")
    assert r.get_json()["cancelled"] is True
    assert _find_leave(data_file, lv["id"]) is None


def test_stop_in_the_past_logs_retro_on_the_closed_days(client, data_file):
    lv = _leave(client).get_json()
    assert _stop(client, lv["id"], on="2026-03-04").status_code == 200
    retro = [c for c in _stored(data_file)["change_log"]
             if c["action"] == "retro" and c["entity_id"] == lv["id"] and c["reason"] == "استدعاء"]
    assert retro


def test_stopped_leave_dates_are_locked_but_note_edit_keeps_stop_fields(client, data_file):
    lv = _leave(client).get_json()
    _stop(client, lv["id"])
    saved = _find_leave(data_file, lv["id"])

    assert client.patch(f"/api/leaves/{lv['id']}", json={**saved, "end": "2026-03-08"}).status_code == 400
    r = client.patch(f"/api/leaves/{lv['id']}", headers=RETRO, json={**saved, "note": "ملاحظة"})
    assert r.status_code == 200, r.get_json()
    after = _find_leave(data_file, lv["id"])
    assert after["note"] == "ملاحظة"
    assert after["stopped_on"] == TODAY and after["original_end"] == "2026-03-09"


# ---------- فتح الراحات ----------

def test_lift_reopens_registration_and_restores_nothing(client, data_file):
    lv = _leave(client).get_json()
    order = _suspend(client, ["شهرية"], stop=[lv["id"]]).get_json()["suspension"]

    r = client.post(f"/api/rest-suspensions/{order['id']}/lift", json={"reason": "انتهى الأمر"})
    assert r.status_code == 200 and r.get_json()["lifted_on"] == TODAY
    assert client.post(f"/api/rest-suspensions/{order['id']}/lift", json={}).status_code == 409

    assert _leave(client, start="2026-03-20", end="2026-03-26").status_code == 201
    assert _find_leave(data_file, lv["id"])["end"] == "2026-03-04"        # فضلت متقصوصة
    assert client.get("/api/bootstrap/dashboard").get_json()["meta"]["rest_suspension"]["types"] == []


# ---------- الراحة الأسبوعية المحسوبة ----------

def _off1():
    data = store.assemble()
    return data, next(o for o in data["officers"] if o["id"] == "OFF-001")


def test_weekly_suspension_silences_the_computed_rest_and_its_alerts(client, frozen_today):
    frozen_today("2026-04-15")                 # الأربعاء — السبت الجاي 2026-04-18
    order = _suspend(client, ["أسبوعية"]).get_json()["suspension"]

    data, off1 = _off1()
    assert officer_status(data, off1, date(2026, 4, 17))["state"] == "working"
    assert taqseera_alerts(data, date(2026, 4, 17)) == []

    frozen_today("2026-04-16")                 # الفتح يوم 16 — السبت 18 بعده
    assert client.post(f"/api/rest-suspensions/{order['id']}/lift", json={}).status_code == 200
    data, off1 = _off1()
    assert officer_status(data, off1, date(2026, 4, 17))["state"] == "taqseera"


def test_weekly_suspension_silences_the_unregistered_weekly_rest_warning(client, frozen_today):
    saturday = "2026-03-07"
    data = store.assemble()
    rows = summarise(data, saturday)["rows"]
    assert any(w["kind"] == "راحة أسبوعية غير مسجلة" for w in day_warnings(data, saturday, rows))

    _suspend(client, ["أسبوعية"])
    data = store.assemble()
    rows = summarise(data, saturday)["rows"]
    assert not any(w["kind"] == "راحة أسبوعية غير مسجلة" for w in day_warnings(data, saturday, rows))


# ---------- سلامة البيانات ----------

def test_leave_index_is_fresh_after_a_stop(client):
    from backend import rest_suspension
    from backend.leaves import leave_on

    lv = _leave(client).get_json()
    data = store.assemble()
    assert leave_on(data, "OFF-002", "2026-03-06")
    rest_suspension.stop_leave(data, lv["id"], "استدعاء", today=TODAY)
    assert leave_on(data, "OFF-002", "2026-03-06") is None


def test_integrity_check_knows_suspension_ids(client):
    from tools.check_integrity import check

    lv = _leave(client).get_json()
    _suspend(client, ["شهرية"], stop=[lv["id"]])
    data = store.assemble()
    assert check(data) == []
    next(x for x in data["leaves"] if x["id"] == lv["id"])["suspension_id"] = "RS-999"
    assert any(kind == "rest_suspension" for _, kind, _ in check(data))


def test_change_log_filter_by_entity(client):
    order = _suspend(client, ["مرضي"]).get_json()["suspension"]
    client.post(f"/api/rest-suspensions/{order['id']}/lift", json={})
    rows = client.get("/api/changes?entity=rest_suspension").get_json()
    rows = rows.get("entries", rows) if isinstance(rows, dict) else rows
    assert {r["action"] for r in rows} == {"suspend", "lift"}


# ---------- صفحة الوقف وشريط أماكن التسكين ----------

def test_listing_shows_exactly_which_leaves_an_order_stopped_and_cancelled(client):
    active = _leave(client).get_json()
    upcoming = _leave(client, pid="OFF-001", start="2026-03-20", end="2026-03-26").get_json()
    _suspend(client, ["شهرية"], stop=[active["id"], upcoming["id"]])

    order = client.get("/api/rest-suspensions").get_json()["active"][0]
    assert [l["id"] for l in order["stopped_leaves"]] == [active["id"]]
    assert order["stopped_leaves"][0]["original_end"] == "2026-03-09"
    cancelled = order["cancelled_leaves"]
    assert [c["leave_id"] for c in cancelled] == [upcoming["id"]]
    assert cancelled[0]["start"] == "2026-03-20" and cancelled[0]["person_id"] == "OFF-001"


def test_listing_is_a_view_and_is_not_saved_into_the_order(client, data_file):
    lv = _leave(client).get_json()
    _suspend(client, ["شهرية"], stop=[lv["id"]])
    client.get("/api/rest-suspensions")
    assert "stopped_leaves" not in _stored(data_file)["rest_suspensions"][0]


def test_day_summary_lists_suspended_types_and_officers_returned_that_day(client):
    lv = _leave(client).get_json()
    _suspend(client, ["شهرية"], stop=[lv["id"]])

    d = client.get(f"/api/rest-suspensions/day/{TODAY}").get_json()
    assert d["types"] == ["شهرية"]
    assert [r["person_id"] for r in d["returned"]] == ["OFF-002"]
    assert d["returned"][0]["original_end"] == "2026-03-09"

    before = client.get("/api/rest-suspensions/day/2026-03-01").get_json()
    assert before == {"types": [], "returned": []}
    assert client.get("/api/rest-suspensions/day/not-a-day").status_code == 400


def test_duty_row_exposes_the_leave_id_for_stopping_from_the_status_dialog(client):
    lv = _leave(client).get_json()
    row = next(r for r in client.get(f"/api/duty/{TODAY}").get_json()["rows"] if r["id"] == "OFF-002")
    assert row["leave"]["id"] == lv["id"]


def test_the_suspension_page_renders(client):
    r = client.get("/leaves/suspension")
    assert r.status_code == 200
    assert "وقف الراحات" in r.get_data(as_text=True)
    assert client.get("/api/bootstrap/rest_suspension").status_code == 200


# ---------- فتح الراحات في نفس يوم الوقف: رجوع الراحات زي ما كانت ----------

def _lift(client, order_id, **body):
    return client.post(f"/api/rest-suspensions/{order_id}/lift", json=body)


def test_same_day_lift_with_restore_puts_every_affected_leave_back(client, data_file):
    active = _leave(client).get_json()
    upcoming = _leave(client, pid="OFF-001", start="2026-03-20", end="2026-03-26").get_json()
    order = _suspend(client, ["شهرية"], stop=[active["id"], upcoming["id"]]).get_json()["suspension"]

    listed = client.get("/api/rest-suspensions").get_json()["active"][0]
    assert listed["can_restore"] is True

    r = _lift(client, order["id"], restore=True, reason="اتلغى الأمر")
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["restored_count"] == 2

    back = _find_leave(data_file, active["id"])
    assert back["end"] == "2026-03-09" and back["return_date"] == "2026-03-10"
    assert not any(k in back for k in ("original_end", "stopped_on", "stop_reason", "suspension_id"))
    recreated = _find_leave(data_file, upcoming["id"])
    assert recreated and recreated["person_id"] == "OFF-001" and recreated["end"] == "2026-03-26"

    restores = [c for c in _stored(data_file)["change_log"] if c["action"] == "restore"]
    assert {c["entity_id"] for c in restores} == {active["id"], upcoming["id"]}


def test_lift_without_restore_keeps_the_leaves_stopped(client, data_file):
    lv = _leave(client).get_json()
    order = _suspend(client, ["شهرية"], stop=[lv["id"]]).get_json()["suspension"]
    assert _lift(client, order["id"]).get_json()["restored_count"] == 0
    assert _find_leave(data_file, lv["id"])["end"] == "2026-03-04"


def test_restore_is_only_offered_on_the_same_day(client, frozen_today, data_file):
    lv = _leave(client).get_json()
    order = _suspend(client, ["شهرية"], stop=[lv["id"]]).get_json()["suspension"]

    frozen_today("2026-03-06")
    assert client.get("/api/rest-suspensions").get_json()["active"][0]["can_restore"] is False
    assert _lift(client, order["id"], restore=True).status_code == 400
    assert not _stored(data_file)["rest_suspensions"][0]["lifted_on"]     # مااتفتحش
    assert _lift(client, order["id"]).status_code == 200                   # الفتح العادي شغال


def test_restore_refuses_when_a_new_leave_took_the_freed_days(client, data_file):
    lv = _leave(client).get_json()
    order = _suspend(client, ["شهرية"], stop=[lv["id"]]).get_json()["suspension"]
    # راحة تانية (نوع مش موقوف) اتسجّلت في الأيام اللي اتفضّت
    assert _leave(client, kind="مرضي", start="2026-03-06", end="2026-03-07").status_code == 201

    r = _lift(client, order["id"], restore=True)
    assert r.status_code == 409
    assert not _stored(data_file)["rest_suspensions"][0]["lifted_on"]     # ذرّي — مفيش حاجة اتغيّرت
    assert _find_leave(data_file, lv["id"])["end"] == "2026-03-04"


def test_integrity_tracks_people_in_cancelled_snapshots(client):
    from tools.check_integrity import check

    upcoming = _leave(client, pid="OFF-001", start="2026-03-20", end="2026-03-26").get_json()
    _suspend(client, ["شهرية"], stop=[upcoming["id"]])
    data = store.assemble()
    assert check(data) == []
    data["rest_suspensions"][0]["cancelled_leaves"][0]["person_id"] = "OFF-999"
    assert any(kind == "person" and ref == "OFF-999" for _, kind, ref in check(data))
