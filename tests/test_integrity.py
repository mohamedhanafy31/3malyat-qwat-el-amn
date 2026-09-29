"""التكامل المرجعي — حذف سجل مايسيبش وراه مراجع معلّقة.

الاختبارات دي مكتوبة على **السلوك** مش على التنفيذ: في المرحلة ٠ الحذف
مكتوب بالإيد في `routes/people.py`، وفي المرحلة ٢ بيتحوّل لمحرّك عام
بيمشي على `references.py`. الاختبارات دي المفروض تعدّي في الحالتين — هي
اللي بتضمن إن التحويل ماكسرش حاجة.
"""
import json

from tools.check_integrity import check


def _dangling(data_file):
    """كل المراجع المعلّقة في الملف بعد العملية."""
    return check(json.loads(data_file.read_text(encoding="utf-8")))


def _archive_and_delete(client, person_id, leave_date="2026-02-01"):
    """إخراج من القوة ثم حذف نهائي — الحذف مسموح لسجلات الأرشيف بس.

    `cleanup: true` عشان الاختبارات دي بتسجّل فرق/مأموريات/راحات مفتوحة
    عمدًا وبتخرج الشخص بتاريخ مايغطّيهاش — ده لازم يترفض من غير تأكيد
    (`test_force_lifecycle.py`)، فهنا بنأكّده صريح."""
    r = client.post(f"/api/person/{person_id}/remove",
                    json={"leave_date": leave_date, "reason": "", "cleanup": True})
    assert r.status_code == 200, r.get_data(as_text=True)
    r = client.delete(f"/api/person/{person_id}")
    assert r.status_code == 200, r.get_data(as_text=True)


def test_live_fixture_starts_clean(data_file):
    assert _dangling(data_file) == []


def test_deleting_officer_clears_course_terms(client, data_file):
    """سجل دورة بيشاور على ضابط متمسوح كان بيفضل في الملف للأبد — صفحة
    الدورات بتعرض صف باسم فاضي ومفيش طريقة توصله تمسحه."""
    course = client.post("/api/courses", json={"name": "دورة اختبار"}).get_json()
    r = client.post("/api/course-terms", json={
        "course_id": course["id"], "officer_id": "OFF-001",
        "start": "2026-03-01", "end": "2026-03-10"})
    assert r.status_code == 201, r.get_data(as_text=True)

    _archive_and_delete(client, "OFF-001")

    assert _dangling(data_file) == []
    stored = json.loads(data_file.read_text(encoding="utf-8"))
    assert [t for t in stored["course_terms"] if t["officer_id"] == "OFF-001"] == []


def test_deleting_officer_detaches_from_missions(client, data_file):
    """المأمورية نفسها بتفضل — بس بدون العضو المحذوف."""
    mission = client.post("/api/missions", json={
        "name": "مأمورية اختبار", "member_ids": ["OFF-001", "OFF-002"]}).get_json()

    _archive_and_delete(client, "OFF-001")

    assert _dangling(data_file) == []
    stored = json.loads(data_file.read_text(encoding="utf-8"))
    kept = next(m for m in stored["missions"] if m["id"] == mission["id"])
    assert kept["member_ids"] == ["OFF-002"]


def test_deleting_officer_clears_every_reference_at_once(client, data_file):
    """الحالة الكاملة: راحة + دورة + مأمورية + تكليف + حالة يوم + منصب
    قيادي + عيادة طبية على نفس الضابط، وكلهم لازم ينضّفوا في عملية واحدة."""
    day = "2026-03-05"
    course = client.post("/api/courses", json={"name": "دورة"}).get_json()
    client.post("/api/course-terms", json={
        "course_id": course["id"], "officer_id": "OFF-001",
        "start": "2026-03-01", "end": "2026-03-10"})
    client.post("/api/missions", json={"name": "مأمورية", "member_ids": ["OFF-001"]})
    client.post("/api/leaves", json={
        "person_id": "OFF-001", "type": "أسبوعية",
        "start": "2026-03-20", "end": "2026-03-20"})
    row = client.post(f"/api/assignments/{day}", json={
        "name": "خدمة اختبار", "section": "الخدمات الطارئة",
        "kind": "خارجية", "officer_ids": ["OFF-001"]})
    assert row.status_code in (200, 201), row.get_data(as_text=True)
    client.put(f"/api/duty/{day}/OFF-001", json={"note": "ملاحظة"})
    client.patch("/api/command", json={"مدير الإدارة": "OFF-001"})

    _archive_and_delete(client, "OFF-001", leave_date="2026-04-01")

    assert _dangling(data_file) == []
    stored = json.loads(data_file.read_text(encoding="utf-8"))

    # السجلات التاريخية **مش** مراجع — `change_log` و`day_confirm` لقطات
    # لحظة حصلت فعلًا، ومسح الـid منها بأثر رجعي بيحوّل سجل التدقيق لسجل
    # بيكدب. فبيتستثنوا من الفحص هنا وفي tools/check_integrity.py بالظبط.
    live = {k: v for k, v in stored.items() if k not in ("change_log", "day_confirm")}
    assert "OFF-001" not in json.dumps(live, ensure_ascii=False)


def test_archiving_alone_keeps_every_reference(client, data_file):
    """الإخراج من القوة **مش** حذف — السجل بينتقل للأرشيف وكل مراجعه
    بتفضل سليمة، عشان الأيام القديمة تفضل تتعرض صح."""
    client.post("/api/leaves", json={
        "person_id": "OFF-001", "type": "أسبوعية",
        "start": "2026-01-20", "end": "2026-01-20"})

    r = client.post("/api/person/OFF-001/remove",
                    json={"leave_date": "2026-02-01", "reason": ""})
    assert r.status_code == 200

    assert _dangling(data_file) == []
    stored = json.loads(data_file.read_text(encoding="utf-8"))
    assert any(lv["person_id"] == "OFF-001" for lv in stored["leaves"])
    # القوة متخزّنة قايمة واحدة و`status` هو اللي بيفرّق (هجرة 008)
    assert any(o["id"] == "OFF-001" and o["status"] == "archived"
               for o in stored["officers"])


# ---------- إزالة التكرار (P6) ----------

def test_leave_name_is_never_stored(client, data_file):
    """الاسم مابيتكتبش في سجل الراحة خالص — لا عند الإضافة ولا التعديل."""
    client.post("/api/leaves", json={"person_id": "OFF-002", "type": "أسبوعية",
                                     "start": "2026-02-01", "end": "2026-02-01"})
    stored = json.loads(data_file.read_text(encoding="utf-8"))
    assert all("name" not in lv for lv in stored["leaves"])


def test_renaming_a_person_updates_every_leave_they_own(client):
    """ده كان الخطأ: تعديل الاسم كان بيسيب الراحات القديمة بالاسم القديم.
    دلوقتي مستحيل — مفيش نسخة تانية من الاسم تبقى قديمة."""
    client.patch("/api/person/OFF-001", json={"name": "اسم جديد تمامًا"})

    rows = client.get("/api/bootstrap/leaves").get_json()["leaves"]
    mine = [lv for lv in rows if lv["person_id"] == "OFF-001"]
    assert mine and all(lv["name"] == "اسم جديد تمامًا" for lv in mine)


def test_api_still_returns_the_name_the_ui_expects(client):
    """الواجهة بتعرض `l.name` — لازم يفضل موجود في الاستجابة رغم إنه
    مابقاش متخزّن."""
    created = client.post("/api/leaves", json={
        "person_id": "OFF-002", "type": "أسبوعية",
        "start": "2026-02-05", "end": "2026-02-05"}).get_json()
    assert created["name"] == "محمود علي"
