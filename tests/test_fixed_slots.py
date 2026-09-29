"""الكتل الثابتة الثلاثة (ضابط عظيم وأمن المعسكر الفرعي/ضابط عظيم
الإدارة/ضابط الأمن بالإدارة) — نفس فكرة الأهداف بالظبط: تعيين مباشر
لصف صباحية/ليلية، بلا قائد ثابت ولا «+ إضافة» حر.
"""
DAY = "2026-04-10"

SECTION_SUBCAMP = "ضابط عظيم وأمن المعسكر الفرعي"
SECTION_GREAT = "ضابط عظيم الإدارة"
SECTION_SECURITY = "ضابط الأمن بالإدارة"


def _set_slot(client, section, shift, officer_ids, day=DAY):
    return client.put(f"/api/board/{day}/slot/{section}/{shift}",
                      json={"officer_ids": officer_ids})


def _section(client, name, day=DAY):
    b = client.get(f"/api/board/{day}").get_json()
    return next(s for s in b["sections"] if s["name"] == name)


def _slot_row(client, section, shift, day=DAY):
    return next(r for r in _section(client, section, day)["rows"] if r["shift"] == shift)


def test_slots_start_vacant_for_both_shifts(client):
    for section in (SECTION_SUBCAMP, SECTION_GREAT, SECTION_SECURITY):
        sec = _section(client, section)
        assert sec["type"] == "slots"
        assert {r["shift"] for r in sec["rows"]} == {"صباحية", "ليلية"}
        assert all(r["vacant"] for r in sec["rows"])


def test_assigning_an_officer_creates_the_row_with_the_fixed_name(client):
    r = _set_slot(client, SECTION_GREAT, "صباحية", ["OFF-001"])
    assert r.status_code == 200
    row = _slot_row(client, SECTION_GREAT, "صباحية")
    assert row["vacant"] is False
    assert [o["id"] for o in row["officers"]] == ["OFF-001"]
    assert row["name"] == "ضابط عظيم الإدارة"

    stored = next(a for a in client.get(f"/api/assignments/{DAY}").get_json()["assignments"]
                 if a["section"] == SECTION_GREAT)
    assert stored["name"] == "ضابط عظيم الإدارة" and stored["kind"] == "داخلية"


def test_security_slot_gets_its_own_fixed_name(client):
    _set_slot(client, SECTION_SECURITY, "ليلية", ["OFF-001"])
    stored = next(a for a in client.get(f"/api/assignments/{DAY}").get_json()["assignments"]
                 if a["section"] == SECTION_SECURITY)
    assert stored["name"] == "ضابط أمن الإدارة"


def test_subcamp_slot_does_not_count_toward_the_totals_table(client):
    """المعسكر الفرعي مالوش خانة في جدول الإجمالي — الضابط بيفضل في
    الصافي حتى وهو نوبتجي، عكس ضابط عظيم/أمن الإدارة."""
    _set_slot(client, SECTION_SUBCAMP, "صباحية", ["OFF-001"])
    row = _slot_row(client, SECTION_SUBCAMP, "صباحية")
    assert row["name"] == "نوبتجي المعسكر الفرعي"

    duty_row = next(r for r in client.get(f"/api/duty/{DAY}").get_json()["rows"]
                    if r["id"] == "OFF-001")
    assert duty_row["group"] == "صافي"


def test_great_slot_does_count_toward_the_totals_table(client):
    _set_slot(client, SECTION_GREAT, "صباحية", ["OFF-001"])
    duty_row = next(r for r in client.get(f"/api/duty/{DAY}").get_json()["rows"]
                    if r["id"] == "OFF-001")
    assert duty_row["group"] == "داخلية"


def test_clearing_the_assignment_removes_the_row_and_shows_vacant_again(client):
    _set_slot(client, SECTION_GREAT, "صباحية", ["OFF-001"])
    r = _set_slot(client, SECTION_GREAT, "صباحية", [])
    assert r.status_code == 200
    row = _slot_row(client, SECTION_GREAT, "صباحية")
    assert row["vacant"] is True and row["officers"] == []
    assert not any(a["section"] == SECTION_GREAT
                  for a in client.get(f"/api/assignments/{DAY}").get_json()["assignments"])


def test_clearing_the_only_slot_assignment_of_the_day_removes_the_day_file(client):
    """set_slot_officers بيشيل الصف بإيده على طول (مش عن طريق DayRepo)،
    فلازم يتنضّف عدّاد id التكليفات معاه برضو — وإلا ملف اليوم الفاضي
    بيفضل موجود بس عشان عدّاد يتيم (لوحظ فعليًا وقت المراجعة اليدوية)."""
    from backend import store

    _set_slot(client, SECTION_GREAT, "صباحية", ["OFF-001"])
    _set_slot(client, SECTION_GREAT, "صباحية", [])
    assert not store.day_path(DAY).exists()


def test_the_two_shifts_are_independent(client):
    _set_slot(client, SECTION_GREAT, "صباحية", ["OFF-001"])
    _set_slot(client, SECTION_GREAT, "ليلية", ["OFF-002"])
    assert [o["id"] for o in _slot_row(client, SECTION_GREAT, "صباحية")["officers"]] == ["OFF-001"]
    assert [o["id"] for o in _slot_row(client, SECTION_GREAT, "ليلية")["officers"]] == ["OFF-002"]


def test_an_invalid_shift_is_rejected(client):
    r = _set_slot(client, SECTION_GREAT, "مش فترة", ["OFF-001"])
    assert r.status_code == 400


def test_a_non_fixed_section_is_rejected(client):
    r = _set_slot(client, "قسم مش موجود", "صباحية", ["OFF-001"])
    assert r.status_code == 400


def test_an_officer_not_on_the_force_is_rejected(client):
    client.patch("/api/person/OFF-002", json={"join_date": "2026-05-01"})
    r = _set_slot(client, SECTION_GREAT, "صباحية", ["OFF-002"])
    assert r.status_code == 400


def test_the_generic_assignments_endpoint_still_works_for_editing_the_row(client):
    """الصف نفسه لسه صف تكليف عادي — تعديله من المسار العام لازم يفضل
    شغّال (تسليح، ملاحظة، إلخ)، المسار المخصّص للتعيين السريع بس."""
    _set_slot(client, SECTION_GREAT, "صباحية", ["OFF-001"])
    row_id = next(a["id"] for a in client.get(f"/api/assignments/{DAY}").get_json()["assignments"]
                 if a["section"] == SECTION_GREAT)
    r = client.patch(f"/api/assignments/{DAY}/{row_id}", json={"weapon": "مسدس"})
    assert r.status_code == 200
    assert r.get_json()["weapon"] == "مسدس"


def test_slot_assignment_is_rejected_on_a_closed_day(client):
    client.post(f"/api/day-status/{DAY}/close", json={})
    r = _set_slot(client, SECTION_GREAT, "صباحية", ["OFF-001"])
    assert r.status_code == 409


# ---------- القسم مش قايمة مقفولة — دور تاني حر ممكن يتضاف بإيده (#regression) ----------
#
# كانت الأقسام دي بتتحط في قسمها الصح، ولما بقت «slots» زي الأهداف
# مفيش «+ إضافة» ليها — فأي دور تاني (زي «ضابط عظيم المعسكر الفرعي»
# بالإضافة لـ«نوبتجي المعسكر الفرعي») كان المشغّل مضطر يكتبه في قسم
# تاني (الخدمات الطارئة) من غير مكان يتحط فيه هنا. دلوقتي القسم لسه
# بيقبل إضافة حرة، وأي صف زيادة بيفضل جوّه قسمه الصح.

def test_the_slots_section_still_accepts_a_freely_added_extra_row(client):
    r = client.post(f"/api/assignments/{DAY}", json={
        "name": "ضابط عظيم المعسكر الفرعي", "kind": "داخلية",
        "section": SECTION_SUBCAMP, "shift": "صباحية", "officer_ids": ["OFF-002"]})
    assert r.status_code == 201, r.get_data(as_text=True)

    sec = _section(client, SECTION_SUBCAMP)
    assert sec["type"] == "slots"
    names = {r["name"] for r in sec["rows"] if r["name"]}
    assert "ضابط عظيم المعسكر الفرعي" in names
    # ومفيش أثر ليه في قسم تاني زي الخدمات الطارئة
    assert not any(a["name"] == "ضابط عظيم المعسكر الفرعي"
                  for a in client.get(f"/api/assignments/{DAY}").get_json()["assignments"]
                  if a["section"] != SECTION_SUBCAMP)


def test_the_fixed_slot_and_a_freely_added_extra_row_are_distinguished(client):
    """الصف الرسمي (اسمه الثابت) وحده اللي زرار «تعيين» بيتحكم فيه —
    أي صف تاني (`slot: False`) بيتعرض بجدول خدمات عادي تحته."""
    _set_slot(client, SECTION_SUBCAMP, "صباحية", ["OFF-001"])
    client.post(f"/api/assignments/{DAY}", json={
        "name": "ضابط عظيم المعسكر الفرعي", "kind": "داخلية",
        "section": SECTION_SUBCAMP, "shift": "صباحية", "officer_ids": ["OFF-002"]})

    sec = _section(client, SECTION_SUBCAMP)
    fixed = [r for r in sec["rows"] if r["slot"]]
    extra = [r for r in sec["rows"] if not r["slot"]]
    assert {r["shift"] for r in fixed} == {"صباحية", "ليلية"}
    assert all(r["name"] in ("نوبتجي المعسكر الفرعي", "") for r in fixed)
    assert [r["name"] for r in extra] == ["ضابط عظيم المعسكر الفرعي"]


def test_adding_an_extra_row_does_not_disturb_the_existing_slot_assignment(client):
    _set_slot(client, SECTION_GREAT, "صباحية", ["OFF-001"])
    client.post(f"/api/assignments/{DAY}", json={
        "name": "دور إضافي", "kind": "داخلية",
        "section": SECTION_GREAT, "shift": "صباحية", "officer_ids": ["OFF-002"]})

    row = _slot_row(client, SECTION_GREAT, "صباحية")
    assert row["slot"] is True
    assert [o["id"] for o in row["officers"]] == ["OFF-001"]
