"""إلغاء تسجيل الحالة بالكامل (مقابل الإنهاء) + «مأمورية» و«انتداب» بنهاية واسم وتفاصيل."""
import json

import pytest

from backend.store import assemble

OFFICER = "OFF-002"


def _row(client, day, officer_id=OFFICER):
    body = client.get(f"/api/duty/{day}").get_json()
    return next(row for row in body["rows"] if row["id"] == officer_id)


def _periods():
    return assemble().get("officer_status_periods") or []


def _put(client, day, status, **extra):
    return client.put(f"/api/duty/{day}/{OFFICER}", json={"status": status, **extra})


def _mission(client, day="2026-05-01", end="2026-05-03", **over):
    body = {"status_end": end, "status_title": "تأمين مؤتمر",
            "status_details": "بمدينة العاشر", **over}
    return _put(client, day, "مأمورية", **body)


# ---------- مأمورية / انتداب بنهاية واسم وتفاصيل ----------

@pytest.mark.parametrize("status", ["مأمورية", "انتداب"])
def test_detailed_status_shows_on_every_covered_day(client, status):
    r = _put(client, "2026-05-01", status, status_end="2026-05-03",
             status_title="تأمين مؤتمر", status_details="بمدينة العاشر")
    assert r.status_code == 200, r.get_json()
    for day in ("2026-05-01", "2026-05-02", "2026-05-03"):
        period = _row(client, day)["persistent_status"]
        assert period["title"] == "تأمين مؤتمر" and period["details"] == "بمدينة العاشر"
        assert period["label"] == (f"{status}: تأمين مؤتمر — بمدينة العاشر — "
                                   "من 1/5/2026 حتى 3/5/2026")
    assert _row(client, "2026-05-04")["persistent_status"] is None
    # الاسم والتفاصيل متخزنين مرة واحدة على السجل
    assert len(_periods()) == 1
    assert _periods()[0]["title"] == "تأمين مؤتمر"


@pytest.mark.parametrize("status", ["مأمورية", "انتداب"])
@pytest.mark.parametrize("over, needle", [
    ({"status_end": ""}, "يوم نهاية"),
    ({"status_title": ""}, "اسم"),
    ({"status_details": ""}, "تفاصيل"),
    ({"status_title": "ا" * 121}, "أطول"),
    ({"status_details": "ا" * 301}, "أطول"),
    ({"status_end": "2026-04-30"}, "قبل يوم بدايتها"),
])
def test_detailed_status_validation(client, status, over, needle):
    body = {"status_end": "2026-05-03", "status_title": "اسم", "status_details": "تفاصيل", **over}
    r = _put(client, "2026-05-01", status, **body)
    assert r.status_code == 400, r.get_json()
    assert needle in r.get_json()["error"]
    assert _periods() == []


def test_emergency_needs_no_name_or_details(client):
    r = _put(client, "2026-05-01", "طارئة", status_end="2026-05-02")
    assert r.status_code == 200, r.get_json()
    assert _row(client, "2026-05-01")["persistent_status"]["title"] == ""


def test_audit_text_includes_name_and_details(client):
    _mission(client)
    texts = [c.get("text", "") for c in assemble().get("change_log") or []
             if c.get("entity") == "officer_status_period"]
    assert any("مأمورية" in t and "تأمين مؤتمر" in t and "بمدينة العاشر" in t for t in texts), texts


def test_mission_status_is_offered_and_removed_status_is_not(client):
    statuses = client.get("/api/bootstrap/duty").get_json()["meta"]["officer_statuses"]
    assert "مأمورية" in statuses
    assert "راحة فرقة" not in statuses


def test_legacy_open_deputation_stays_readable_stoppable_and_cancellable(client, data_file):
    def inject(day_stop):
        data = json.loads(data_file.read_text())
        data.setdefault("officer_status_periods", []).append(
            {"id": "OSP-0001", "officer_id": OFFICER, "status": "انتداب",
             "start": "2026-05-01", "end": "", "stopped_on": ""})
        data_file.write_text(json.dumps(data, ensure_ascii=False))
    inject(None)
    row = _row(client, "2026-05-20")
    assert (row["bucket"], row["status_source"]) == ("انتداب", "period")
    assert row["persistent_status"]["legacy_open"] is True
    assert row["persistent_status"]["label"] == "انتداب"
    # حفظ ملاحظة فقط (بنفس الحالة) ما يفرضش بيانات جديدة ولا يكسر السجل
    r = _put(client, "2026-05-20", "انتداب", note="ملاحظة")
    assert r.status_code == 200, r.get_json()
    assert _periods()[0]["end"] == ""
    # حالة جديدة بالاسم نفسه من غير نهاية ولا اسم ترفض
    assert _put(client, "2026-05-20", "انتداب", status_end="2026-05-22").status_code == 400
    # الإنهاء
    assert client.post("/api/duty/2026-05-10/OFF-002/stop-status", json={}).status_code == 200
    assert _periods()[0]["end"] == "2026-05-09"


def test_legacy_open_deputation_can_be_cancelled(client, data_file):
    data = json.loads(data_file.read_text())
    data.setdefault("officer_status_periods", []).append(
        {"id": "OSP-0001", "officer_id": OFFICER, "status": "انتداب",
         "start": "2026-05-01", "end": "", "stopped_on": ""})
    data_file.write_text(json.dumps(data, ensure_ascii=False))
    r = client.post("/api/duty/2026-05-12/OFF-002/cancel-status", json={})
    assert r.status_code == 200, r.get_json()
    assert _periods() == []


# ---------- الإنهاء مقابل الإلغاء ----------

def test_stop_keeps_earlier_coverage_but_cancel_deletes_whole_period(client):
    _mission(client, "2026-05-01", "2026-05-10")
    stopped = client.post("/api/duty/2026-05-05/OFF-002/stop-status", json={})
    assert stopped.status_code == 200, stopped.get_json()
    assert [(p["start"], p["end"]) for p in _periods()] == [("2026-05-01", "2026-05-04")]
    assert _row(client, "2026-05-04")["status"] == "مأمورية"
    assert _row(client, "2026-05-05")["status"] == ""

    # الإلغاء من أي يوم مغطّى بيمسح السجل كله — الماضي (5/1) والمستقبل
    cancelled = client.post("/api/duty/2026-05-03/OFF-002/cancel-status", json={})
    assert cancelled.status_code == 200, cancelled.get_json()
    assert _periods() == []
    for day in ("2026-05-01", "2026-05-03", "2026-05-04"):
        assert _row(client, day)["persistent_status"] is None
        assert _row(client, day)["status"] == ""


def test_cancel_from_the_last_day_removes_earlier_days_too(client):
    _put(client, "2026-05-01", "طارئة", status_end="2026-05-06")
    assert client.post("/api/duty/2026-05-06/OFF-002/cancel-status", json={}).status_code == 200
    assert _periods() == []
    assert _row(client, "2026-05-01")["status"] == ""


def test_cancel_open_ended_sick_status(client):
    _put(client, "2026-05-01", "مرضي")
    assert client.post("/api/duty/2026-05-30/OFF-002/cancel-status", json={}).status_code == 200
    assert _periods() == []


def test_cancel_only_touches_the_covering_period(client):
    _put(client, "2026-05-01", "طارئة", status_end="2026-05-02")
    _put(client, "2026-05-10", "طارئة", status_end="2026-05-12")
    assert client.post("/api/duty/2026-05-11/OFF-002/cancel-status", json={}).status_code == 200
    assert [(p["start"], p["end"]) for p in _periods()] == [("2026-05-01", "2026-05-02")]


def test_cancel_audit_event_describes_full_cancellation(client):
    _mission(client, "2026-05-01", "2026-05-03")
    client.post("/api/duty/2026-05-02/OFF-002/cancel-status", json={})
    events = [c for c in assemble().get("change_log") or []
              if c.get("entity") == "officer_status_period"]
    last = events[-1]
    assert last["action"] == "delete"
    assert "إلغاء تسجيل" in last["text"] and "بالكامل" in last["text"]
    assert "تأمين مؤتمر" in last["text"]


def test_stop_audit_event_says_ending_not_cancelling(client):
    _mission(client, "2026-05-01", "2026-05-09")
    client.post("/api/duty/2026-05-04/OFF-002/stop-status", json={})
    events = [c for c in assemble().get("change_log") or []
              if c.get("entity") == "officer_status_period"]
    assert events[-1]["action"] == "update"
    assert "إنهاء" in events[-1]["text"] and "إلغاء" not in events[-1]["text"]


def test_cancel_without_a_covering_status_is_404(client):
    r = client.post("/api/duty/2026-05-01/OFF-002/cancel-status", json={})
    assert r.status_code == 404
    assert "error" in r.get_json()


def test_cancel_for_officer_not_on_force_is_404(client):
    _mission(client)
    r = client.post("/api/duty/2019-01-01/OFF-002/cancel-status", json={})
    assert r.status_code in (404, 409)
    assert len(_periods()) == 1


def test_cancel_on_a_closed_day_is_refused(client, frozen_today):
    _mission(client, "2026-05-01", "2026-05-03")
    frozen_today("2026-06-01")          # الأيام اللي فاتت بتتقفل تلقائيًا
    r = client.post("/api/duty/2026-05-02/OFF-002/cancel-status", json={})
    assert r.status_code == 409
    assert len(_periods()) == 1


def test_cancel_spanning_closed_days_needs_a_reason(client, frozen_today):
    _mission(client, "2026-05-01", "2026-05-10")
    frozen_today("2026-05-08")          # 5/1..5/7 مقفولة، 5/8 وبعده مفتوحة
    r = client.post("/api/duty/2026-05-09/OFF-002/cancel-status", json={})
    assert r.status_code == 409
    assert r.get_json().get("needs_reason") is True
    assert len(_periods()) == 1
    ok = client.post("/api/duty/2026-05-09/OFF-002/cancel-status", json={},
                     headers={"X-Retro-Reason": "تسجيل بالغلط"})
    assert ok.status_code == 200, ok.get_json()
    assert _periods() == []


def test_clearing_day_state_ends_period_and_says_so(client):
    _mission(client, "2026-05-01", "2026-05-10")
    r = client.delete("/api/duty/2026-05-05/OFF-002")
    assert r.status_code == 200
    assert r.get_json()["ended_status"] == "مأمورية"
    # إنهاء مش إلغاء: اللي فات محفوظ
    assert [(p["start"], p["end"]) for p in _periods()] == [("2026-05-01", "2026-05-04")]


# ---------- العرض والتصدير ----------

def test_detailed_daily_view_and_exports_carry_the_label(client):
    _mission(client, "2026-05-01", "2026-05-03")
    label = "مأمورية: تأمين مؤتمر — بمدينة العاشر — من 1/5/2026 حتى 3/5/2026"
    assert _row(client, "2026-05-02")["persistent_status"]["label"] == label
    board = client.get("/api/board/2026-05-02").get_json()
    outsiders = next(s for s in board["sections"] if s["name"] == "الخوارج")["rows"]
    row = next(r for r in outsiders if r["id"] == OFFICER)
    assert row["status_period"]["label"] == label
    assert client.get("/api/duty/2026-05-02/export.docx").status_code == 200
    from backend.board_export import status_period_text
    assert status_period_text(row["status_period"]) == label
