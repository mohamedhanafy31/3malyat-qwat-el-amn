"""دورة حياة القوة — خروج/استرجاع، والتنظيف اللي المفروض يحصل معاهم.

المشاكل اللي البند ده اتعمل عشانها:

  - استرجاع بتاريخ انضمام «النهاردة» كان بيقبل حتى لو الشخص خرج
    «النهاردة» بالظبط — نفس اليوم بيبقى فيه سجلين على القوة (القديم
    ولسه بيغطي يوم خروجه، والجديد بدأ منه) فأصل القوة بيتحسب زيادة واحد.

  - الإخراج من القوة كان بيمشي من غير ما يشوف لو فيه راحات/فرق/تكليفات
    مسجّلة بعد تاريخ الخروج — بتفضل معلّقة لشخص السيستم بيقول إنه خرج.
"""
DAY = "2026-04-10"


def _remove(client, person_id="OFF-002", **over):
    body = {"leave_date": "2026-02-01", "reason": "", **over}
    return client.post(f"/api/person/{person_id}/remove", json=body)


def _restore(client, person_id="OFF-002", **over):
    return client.post(f"/api/person/{person_id}/restore", json=over)


def _force_count(client, day=DAY):
    return client.get(f"/api/duty/{day}").get_json()["summary"]["أصل القوة"]


# ---------- استرجاع بنفس يوم الخروج (#2) ----------

def test_restoring_on_the_exact_leave_date_is_rejected(client):
    """لازم تاريخ انضمام بعد تاريخ الخروج — وإلا الشخص هيتحسب مرتين."""
    r = _remove(client, leave_date="2026-05-01")
    assert r.status_code == 200, r.get_data(as_text=True)

    r = _restore(client, join_date="2026-05-01")
    assert r.status_code == 400
    assert "leave_date" in r.get_json()


def test_restoring_before_the_leave_date_is_rejected(client):
    r = _remove(client, leave_date="2026-05-01")
    r = _restore(client, join_date="2026-04-20")
    assert r.status_code == 400


def test_restoring_after_the_leave_date_succeeds_and_force_counts_once(client):
    r = _remove(client, leave_date="2026-05-01")
    assert r.status_code == 200

    r = _restore(client, join_date="2026-05-02")
    assert r.status_code == 201, r.get_data(as_text=True)

    # النهاردة (2026-04-10) قبل الخروج، فلسه سجل واحد بس شايف — مش
    # اتنين ولا صفر. الفحص الحقيقي على أصل القوة يوم فيه الاتنين معًا:
    # يوم الخروج (كان لسه على القوة القديمة) ويوم الانضمام الجديد.
    assert _force_count(client, "2026-05-01") >= 1
    on_5_1 = client.get("/api/duty/2026-05-01").get_json()["rows"]
    on_5_2 = client.get("/api/duty/2026-05-02").get_json()["rows"]
    assert sum(1 for r in on_5_1 if r["id"] == "OFF-002") == 1
    assert sum(1 for r in on_5_2 if r["id"] == "OFF-002") == 0  # الأرشيف خرج، الجديد بمعرّف تاني
    new_id = next(o["id"] for o in on_5_2 if o["name"] == "محمود علي")
    assert sum(1 for r in on_5_2 if r["id"] == new_id) == 1


def test_restoring_with_no_join_date_still_checked_against_leave_date(client):
    """الافتراضي (النهاردة الحقيقي) عادي بعيد كفاية عن أي تاريخ اختبار،
    بس الفحص لازم يشتغل برضو لو الافتراضي وقع في يوم الخروج أو قبله."""
    import datetime
    today = datetime.date.today().isoformat()
    r = _remove(client, leave_date=today)
    assert r.status_code == 200
    r = _restore(client)          # من غير join_date -> النهاردة الحقيقي
    assert r.status_code == 400


# ---------- تعارض مدى الخدمة عند الإخراج (#3) ----------

def test_removing_with_a_future_leave_needs_confirmation(client):
    """OFF-001 عنده راحة مسجّلة (fixture) من 10 لـ2026-01-10 — إخراجه
    بتاريخ قبلها لازم يترفض من غير تأكيد."""
    r = _remove(client, "OFF-001", leave_date="2026-01-01")
    assert r.status_code == 409
    body = r.get_json()
    assert body["needs_confirm"] is True
    assert "leaves" in body["conflicts"]


def test_removing_with_cleanup_trims_the_leave_and_succeeds(client):
    r = _remove(client, "OFF-001", leave_date="2026-01-01", cleanup=True)
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert "leaves" in body["cleanup"]

    stored = client.get("/api/bootstrap/leaves").get_json()["leaves"]
    mine = [lv for lv in stored if lv["person_id"] == "OFF-001"]
    assert mine == [], "الراحة كانت بعد الخروج بالكامل — لازم تتشال"


def test_removing_with_a_future_assignment_needs_confirmation(client):
    client.post(f"/api/assignments/{DAY}", json={
        "name": "خدمة اختبار", "kind": "خارجية", "officer_ids": ["OFF-002"]})

    r = _remove(client, "OFF-002", leave_date="2026-01-01")   # قبل DAY
    assert r.status_code == 409
    assert "assignment_days" in r.get_json()["conflicts"]


def test_removing_with_cleanup_detaches_the_future_assignment(client):
    row = client.post(f"/api/assignments/{DAY}", json={
        "name": "خدمة اختبار", "kind": "خارجية", "officer_ids": ["OFF-002"]}).get_json()

    r = _remove(client, "OFF-002", leave_date="2026-01-01", cleanup=True)
    assert r.status_code == 200, r.get_data(as_text=True)

    board = client.get(f"/api/assignments/{DAY}").get_json()["assignments"]
    kept = next(a for a in board if a["id"] == row["id"])
    assert kept["officer_ids"] == []


def test_removing_with_an_open_mission_needs_confirmation(client):
    client.post("/api/missions", json={"name": "مأمورية", "member_ids": ["OFF-002"]})
    r = _remove(client, "OFF-002")
    assert r.status_code == 409
    assert "missions" in r.get_json()["conflicts"]


def test_removing_with_no_conflicts_needs_no_confirmation(client):
    r = _remove(client, "OFF-002")
    assert r.status_code == 200


# ---------- تعديل تاريخ الانضمام/الخروج (#3، تعديل مش خروج) ----------

def test_moving_join_date_later_past_an_existing_leave_is_rejected(client):
    """OFF-001 عنده راحة يوم 2026-01-10 — تأجيل انضمامه لبعدها هيسيبها
    قبل انضمامه الجديد."""
    r = client.patch("/api/person/OFF-001", json={"join_date": "2026-01-15"})
    assert r.status_code == 400
    assert "leaves" in r.get_json()["conflicts"]


def test_moving_join_date_before_the_leave_is_fine(client):
    r = client.patch("/api/person/OFF-001", json={"join_date": "2020-02-01"})
    assert r.status_code == 200


def test_pulling_in_an_archived_persons_leave_date_with_a_later_leave_is_rejected(client):
    client.post("/api/leaves", json={"person_id": "OFF-002", "type": "أسبوعية",
                                     "start": "2026-05-10", "end": "2026-05-10"})
    _remove(client, "OFF-002", leave_date="2026-06-01")

    r = client.patch("/api/person/OFF-002", json={"leave_date": "2026-05-05"})
    assert r.status_code == 400
    assert "leaves" in r.get_json()["conflicts"]
