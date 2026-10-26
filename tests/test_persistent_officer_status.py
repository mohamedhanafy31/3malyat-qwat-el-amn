"""حالات الضابط الممتدة: «مرضي»/«غياب»/«انتداب» مستمرة حتى الإيقاف، و«طارئة»
لمدة محددة بيوم نهاية شامل. الاتنين سجل مدى في core مش نسخة في كل ملف يوم.
"""
import json

import pytest

from backend.store import assemble


def _row(client, day, officer_id="OFF-002"):
    body = client.get(f"/api/duty/{day}").get_json()
    return next(row for row in body["rows"] if row["id"] == officer_id)


def _periods():
    return [(p["status"], p["start"], p["end"])
            for p in assemble().get("officer_status_periods") or []]


@pytest.mark.parametrize("status", ["مرضي", "غياب", "انتداب"])
def test_continuous_status_continues_until_explicit_stop(client, status):
    started = client.put("/api/duty/2026-05-01/OFF-002", json={"status": status})
    assert started.status_code == 200, started.get_json()

    first = _row(client, "2026-05-01")
    later = _row(client, "2026-05-20")
    assert (first["status"], first["status_source"]) == (status, "period")
    assert (later["group"], later["bucket"]) == ("خوارج", status)
    assert later["persistent_status"]["start"] == "2026-05-01"
    assert later["persistent_status"]["kind"] == "continuous"
    assert later["persistent_status"]["open_ended"] is True

    # مدى واحد في core — مش منسوخ في ملفات الأيام التالية
    data = assemble()
    assert len(data["officer_status_periods"]) == 1
    assert not (data.get("day_officers", {}).get("2026-05-02") or {}).get("OFF-002")

    stopped = client.post("/api/duty/2026-05-03/OFF-002/stop-status", json={})
    assert stopped.status_code == 200, stopped.get_json()
    assert _row(client, "2026-05-02")["status"] == status
    # يوم الإيقاف هو أول يوم عادي
    assert _row(client, "2026-05-03")["status"] == ""
    assert _row(client, "2026-05-20")["status"] == ""
    assert _periods() == [(status, "2026-05-01", "2026-05-02")]


def test_continuous_status_refuses_an_end_date(client):
    r = client.put("/api/duty/2026-05-01/OFF-002",
                   json={"status": "مرضي", "status_end": "2026-05-04"})
    assert r.status_code == 400
    assert "مستمرة" in r.get_json()["error"]
    assert _periods() == []


def test_emergency_runs_through_its_end_day_and_expires(client):
    r = client.put("/api/duty/2026-05-01/OFF-002",
                   json={"status": "طارئة", "status_end": "2026-05-03"})
    assert r.status_code == 200, r.get_json()

    for day in ("2026-05-01", "2026-05-02", "2026-05-03"):
        row = _row(client, day)
        assert (row["group"], row["bucket"]) == ("خوارج", "طارئة"), day
        assert row["persistent_status"]["kind"] == "bounded"
        assert row["persistent_status"]["open_ended"] is False
    assert _row(client, "2026-05-04")["status"] == ""
    assert _row(client, "2026-05-04")["persistent_status"] is None
    assert _periods() == [("طارئة", "2026-05-01", "2026-05-03")]


@pytest.mark.parametrize("end, needle", [
    (None, "يوم نهاية"),
    ("", "يوم نهاية"),
    ("مش تاريخ", "غير صحيح"),
    ("20260505", "غير صحيح"),          # مش الصيغة المعيارية
    ("2026-02-30", "غير صحيح"),
    ("2026-04-30", "قبل يوم بدايتها"),
])
def test_emergency_end_date_is_required_and_validated(client, end, needle):
    body = {"status": "طارئة"}
    if end is not None:
        body["status_end"] = end
    r = client.put("/api/duty/2026-05-01/OFF-002", json=body)
    assert r.status_code == 400, r.get_json()
    assert needle in r.get_json()["error"]
    assert _periods() == []


def test_single_day_emergency_is_allowed(client):
    r = client.put("/api/duty/2026-05-01/OFF-002",
                   json={"status": "طارئة", "status_end": "2026-05-01"})
    assert r.status_code == 200, r.get_json()
    assert _row(client, "2026-05-01")["status"] == "طارئة"
    assert _row(client, "2026-05-02")["status"] == ""


def test_end_date_is_rejected_for_a_one_day_status(client):
    r = client.put("/api/duty/2026-05-01/OFF-002",
                   json={"status": "مهمة خاصة", "status_end": "2026-05-03"})
    assert r.status_code == 400


def test_switching_status_closes_the_previous_period(client):
    client.put("/api/duty/2026-05-01/OFF-002", json={"status": "مرضي"})
    r = client.put("/api/duty/2026-05-04/OFF-002",
                   json={"status": "طارئة", "status_end": "2026-05-06"})
    assert r.status_code == 200, r.get_json()

    assert _row(client, "2026-05-03")["status"] == "مرضي"
    assert _row(client, "2026-05-04")["status"] == "طارئة"
    assert _row(client, "2026-05-07")["status"] == ""
    assert _periods() == [
        ("مرضي", "2026-05-01", "2026-05-03"),
        ("طارئة", "2026-05-04", "2026-05-06"),
    ]


def test_resaving_an_emergency_edits_its_end_in_place(client):
    client.put("/api/duty/2026-05-01/OFF-002",
               json={"status": "طارئة", "status_end": "2026-05-03"})
    # حفظ الحالة من يوم لاحق (زي فتح النموذج وتعديل «حتى يوم») مش بيقسم السجل
    r = client.put("/api/duty/2026-05-02/OFF-002",
                   json={"status": "طارئة", "status_end": "2026-05-05"})
    assert r.status_code == 200, r.get_json()
    assert _periods() == [("طارئة", "2026-05-01", "2026-05-05")]
    # ونفس الحالة بنفس النهاية مابتعملش أي تغيير
    client.put("/api/duty/2026-05-03/OFF-002",
               json={"status": "طارئة", "status_end": "2026-05-05", "note": "متابعة"})
    assert _periods() == [("طارئة", "2026-05-01", "2026-05-05")]


def test_resaving_the_same_continuous_status_keeps_one_period(client):
    client.put("/api/duty/2026-05-01/OFF-002", json={"status": "غياب"})
    client.put("/api/duty/2026-05-05/OFF-002", json={"status": "غياب", "extra": "x"})
    assert _periods() == [("غياب", "2026-05-01", "")]


def test_future_scheduled_period_is_preserved(client):
    client.put("/api/duty/2026-05-10/OFF-002",
               json={"status": "طارئة", "status_end": "2026-05-12"})
    # حالة مستمرة قبلها بتقف لوحدها قبل الطارئة المجدولة
    client.put("/api/duty/2026-05-01/OFF-002", json={"status": "انتداب"})
    assert _periods() == [
        ("انتداب", "2026-05-01", "2026-05-09"),
        ("طارئة", "2026-05-10", "2026-05-12"),
    ]
    # وطارئة نهايتها بتعدّي على السجل المجدول بتترفض بدل ما تبلعه
    r = client.put("/api/duty/2026-05-05/OFF-002",
                   json={"status": "طارئة", "status_end": "2026-05-11"})
    assert r.status_code == 409
    assert _row(client, "2026-05-11")["status"] == "طارئة"


def test_clearing_the_day_stops_the_period_from_that_day(client):
    client.put("/api/duty/2026-05-01/OFF-002", json={"status": "مرضي"})
    assert client.delete("/api/duty/2026-05-04/OFF-002").status_code == 200
    assert _row(client, "2026-05-03")["status"] == "مرضي"
    assert _row(client, "2026-05-04")["status"] == ""
    assert _periods() == [("مرضي", "2026-05-01", "2026-05-03")]


def test_audit_text_describes_the_new_semantics(client):
    client.put("/api/duty/2026-05-01/OFF-002", json={"status": "مرضي"})
    client.put("/api/duty/2026-05-04/OFF-002",
               json={"status": "طارئة", "status_end": "2026-05-06"})
    texts = [c.get("text", "") for c in assemble().get("change_log") or []
             if c.get("entity") == "officer_status_period"]
    assert any("المستمرة" in t and "حتى إيقافها" in t for t in texts), texts
    assert any("بدء طارئة" in t and "حتى 2026-05-06" in t and "إنهاء حالة مرضي" in t
               for t in texts), texts


def _inject(data_file, mutate):
    data = json.loads(data_file.read_text())
    mutate(data)
    data_file.write_text(json.dumps(data, ensure_ascii=False))


def test_legacy_open_ended_emergency_stays_readable_and_stoppable(client, data_file):
    _inject(data_file, lambda data: data.setdefault("officer_status_periods", []).append(
        {"id": "OSP-0001", "officer_id": "OFF-002", "status": "طارئة",
         "start": "2026-05-01", "end": "", "stopped_on": ""}))

    row = _row(client, "2026-05-09")
    assert (row["bucket"], row["status_source"]) == ("طارئة", "period")
    assert row["persistent_status"]["legacy_open"] is True

    # مفيش «طارئة» مفتوحة جديدة — لكن السجل القديم بيتوقف عادي
    assert client.put("/api/duty/2026-05-09/OFF-001",
                      json={"status": "طارئة"}).status_code == 400
    stopped = client.post("/api/duty/2026-05-10/OFF-002/stop-status", json={})
    assert stopped.status_code == 200, stopped.get_json()
    assert _row(client, "2026-05-09")["status"] == "طارئة"
    assert _row(client, "2026-05-10")["status"] == ""


def test_legacy_open_emergency_can_be_given_an_end_in_place(client, data_file):
    _inject(data_file, lambda data: data.setdefault("officer_status_periods", []).append(
        {"id": "OSP-0001", "officer_id": "OFF-002", "status": "طارئة",
         "start": "2026-05-01", "end": "", "stopped_on": ""}))
    r = client.put("/api/duty/2026-05-03/OFF-002",
                   json={"status": "طارئة", "status_end": "2026-05-04"})
    assert r.status_code == 200, r.get_json()
    assert _periods() == [("طارئة", "2026-05-01", "2026-05-04")]
    assert _row(client, "2026-05-05")["status"] == ""


def test_stop_without_an_active_period_is_404(client):
    r = client.post("/api/duty/2026-05-01/OFF-002/stop-status", json={})
    assert r.status_code == 404


# ---------- «راحة فرقة» اتلغت و«فرقة» مش حالة يدوية ----------

def test_removed_statuses_are_not_offered(client):
    duty_meta = client.get("/api/bootstrap/duty").get_json()["meta"]
    leave_meta = client.get("/api/bootstrap/leaves").get_json()["meta"]
    for value in ("راحة فرقة", "فرقة"):
        assert value not in duty_meta["officer_statuses"]
    assert "راحة فرقة" not in leave_meta["leave_types"]
    assert duty_meta["officer_statuses"][:4] == ["انتداب", "غياب", "مرضي", "طارئة"]
    suspension = client.get("/api/rest-suspensions").get_json()
    assert "راحة فرقة" not in suspension["leave_types"]


def test_removed_statuses_cannot_be_created(client):
    for value in ("راحة فرقة", "فرقة"):
        r = client.put("/api/duty/2026-05-01/OFF-002", json={"status": value})
        assert r.status_code == 400, value
    r = client.post("/api/leaves", json={"person_id": "OFF-002", "type": "راحة فرقة",
                                         "start": "2026-05-01", "end": "2026-05-02"})
    assert r.status_code == 400
    assert "custom_officer_statuses" not in assemble() or not any(
        v in ("فرقة", "راحة فرقة") for v in assemble()["custom_officer_statuses"])


def test_legacy_course_rows_and_leaves_still_load(client, data_file):
    note = "فرقة اعداد مدربين خلال الفترة من 3/5/2026 حتي 29/5/2026 بمعهد التدريب"

    def legacy(data):
        data.setdefault("day_officers", {})["2026-05-05"] = {
            "OFF-002": {"status": "فرقة", "note": note},
            "OFF-001": {"status": "راحة فرقة"},
        }
        data.setdefault("leaves", []).append({
            "id": "LV-9001", "person_id": "OFF-002", "type": "راحة فرقة",
            "start": "2026-05-20", "end": "2026-05-21", "return_date": "2026-05-22",
            "note": "", "special_name": "", "source": ""})
        # تصنيف حر قديم بنفس الاسم مابيرجعش كاختيار
        data["custom_officer_statuses"] = ["راحة فرقة"]
    _inject(data_file, legacy)

    duty = client.get("/api/duty/2026-05-05").get_json()
    rows = {r["id"]: r for r in duty["rows"]}
    assert (rows["OFF-002"]["bucket"], rows["OFF-002"]["note"]) == ("فرقة", note)
    assert rows["OFF-001"]["bucket"] == "راحة فرقة"
    assert duty["summary"]["balanced"] is True
    assert "راحة فرقة" not in duty["officer_statuses"]

    board = client.get("/api/board/2026-05-05").get_json()
    outsiders = next(s for s in board["sections"] if s["name"] == "الخوارج")["rows"]
    assert next(r for r in outsiders if r["id"] == "OFF-002")["note"] == note

    # تعديل ملاحظة صف أرشيفي بيحافظ على حالته القديمة
    r = client.put("/api/duty/2026-05-05/OFF-002", json={"status": "فرقة", "note": note + "."})
    assert r.status_code == 200, r.get_json()
    assert _row(client, "2026-05-05")["status"] == "فرقة"

    # راحة «راحة فرقة» القديمة بتتقري وبتتعدّل بنفس نوعها
    assert _row(client, "2026-05-20")["bucket"] == "فرقة"
    assert client.get("/api/bootstrap/leaves").status_code == 200
    edited = client.patch("/api/leaves/LV-9001", json={"note": "أرشيف"})
    assert edited.status_code == 200, edited.get_json()
    register = client.get("/api/register/2026/5").get_json()
    assert "ر ف" not in {item["code"] for item in register["legend"]}
