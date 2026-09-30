"""اعداد الخدمات — القالب الثابت (أساسية + طوارئ متكررة) ونسخة كل يوم منه،
وبلوك الطوارئ اليومي المحسوب من عدد المجندين المسجّل على اللوحة.
"""
import json

DAY = "2026-04-10"
OTHER_DAY = "2026-04-11"


def _add_assignment(client, day=DAY, **over):
    body = {"name": "خدمة اختبار", "kind": "خارجية"}
    body.update(over)
    r = client.post(f"/api/assignments/{day}", json=body)
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def test_template_starts_empty_and_unseeded(client):
    r = client.get("/api/counts/template")
    assert r.status_code == 200
    body = r.get_json()
    assert body == {"entries": [], "seeded": False}


def test_seeding_fills_the_three_blocks_from_a_real_day(client):
    r = client.post("/api/counts/template/seed")
    assert r.status_code == 201
    entries = r.get_json()["entries"]
    blocks = {e["block"] for e in entries}
    assert blocks == {"صباحية", "ليلية", "طوارئ"}
    assert len(entries) > 40                       # القالب مبني من يومية حقيقية مش صف تجريبي

    again = client.post("/api/counts/template/seed")
    assert again.status_code == 409, "التبذير يرفض يكرر القالب فوق نفسه"


def test_unseeded_day_view_is_all_zero(client):
    """قبل ما حد يزرع القالب، يومية اعداد الخدمات لازم تفضل فاضية بأمان —
    مش أرقام قديمة ولا استثناء."""
    r = client.get(f"/api/counts/{DAY}")
    assert r.status_code == 200
    body = r.get_json()
    assert body["basic_am"] == body["basic_pm"] == body["recurring"] == []
    assert body["emergency"] == []
    assert body["totals"] == {"basic_am": 0, "basic_pm": 0, "recurring": 0,
                              "emergency_day": 0, "emergency": 0, "custom": 0, "grand_total": 0}
    assert body["services"] == {"basic_am": 0, "basic_pm": 0, "recurring": 0,
                                "emergency_day": 0, "custom": 0, "total": 0}
    assert body["custom_sections"] == []
    assert body["from_template"] is True


def test_day_mirrors_template_until_first_edit(client):
    client.post("/api/counts/template/seed")
    r = client.get(f"/api/counts/{DAY}")
    body = r.get_json()
    assert body["from_template"] is True
    assert len(body["basic_am"]) > 0


def test_editing_a_day_entry_materialises_only_that_day(client):
    """التعديل بيفصل نسخة اليوم عن القالب — القالب وباقي الأيام ما بيتأثروش."""
    seed = client.post("/api/counts/template/seed").get_json()["entries"]
    am_entry = next(e for e in seed if e["block"] == "صباحية")

    r = client.patch(f"/api/counts/{DAY}/entries/{am_entry['id']}", json={"count": 999})
    assert r.status_code == 200
    assert r.get_json()["count"] == 999

    today = client.get(f"/api/counts/{DAY}").get_json()
    assert today["from_template"] is False
    edited = next(e for e in today["basic_am"] if e["id"] == am_entry["id"])
    assert edited["count"] == 999

    other = client.get(f"/api/counts/{OTHER_DAY}").get_json()
    assert other["from_template"] is True
    unaffected = next(e for e in other["basic_am"] if e["id"] == am_entry["id"])
    assert unaffected["count"] == am_entry["count"]

    template = client.get("/api/counts/template").get_json()["entries"]
    assert next(e for e in template if e["id"] == am_entry["id"])["count"] == am_entry["count"]


def test_add_and_delete_day_entry(client):
    client.post("/api/counts/template/seed")
    r = client.post(f"/api/counts/{DAY}/entries",
                     json={"block": "صباحية", "name": "خدمة جديدة اليوم", "count": 3})
    assert r.status_code == 201
    entry_id = r.get_json()["id"]

    today = client.get(f"/api/counts/{DAY}").get_json()
    assert any(e["id"] == entry_id for e in today["basic_am"])

    other = client.get(f"/api/counts/{OTHER_DAY}").get_json()
    assert not any(e["id"] == entry_id for e in other["basic_am"]), "الإضافة بتاعة يوم واحد بس"

    d = client.delete(f"/api/counts/{DAY}/entries/{entry_id}")
    assert d.status_code == 200
    assert d.get_json() == {"ok": True}
    assert client.delete(f"/api/counts/{DAY}/entries/{entry_id}").status_code == 404


def test_reset_day_discards_only_that_day(client):
    seed = client.post("/api/counts/template/seed").get_json()["entries"]
    am_entry = next(e for e in seed if e["block"] == "صباحية")
    client.patch(f"/api/counts/{DAY}/entries/{am_entry['id']}", json={"count": 1})

    r = client.post(f"/api/counts/{DAY}/reset")
    assert r.status_code == 200
    body = r.get_json()
    assert body["from_template"] is True
    restored = next(e for e in body["basic_am"] if e["id"] == am_entry["id"])
    assert restored["count"] == am_entry["count"]


def test_entry_validation_rejects_bad_input(client):
    assert client.post(f"/api/counts/{DAY}/entries",
                        json={"block": "غير موجود", "name": "س", "count": 1}).status_code == 400
    assert client.post(f"/api/counts/{DAY}/entries",
                        json={"block": "صباحية", "count": 1}).status_code == 400, \
        "لازم اسم أو خدمة"
    assert client.post(f"/api/counts/{DAY}/entries",
                        json={"block": "صباحية", "count": 5}).status_code == 400


def test_emergency_block_reads_conscript_count_from_the_board(client, data_file):
    """أعداد الطوارئ بتتكتب على اللوحة وبس — الصفحة دي بتجمعها من غير أي
    إدخال مباشر ليها."""
    r = _add_assignment(client, name="خدمة طارئة", section="الخدمات الطارئة",
                        conscript_count=7)

    body = client.get(f"/api/counts/{DAY}").get_json()
    assert len(body["emergency"]) == 1
    row = body["emergency"][0]
    assert row["name"] == "خدمة طارئة" and row["count"] == 7
    assert body["totals"]["emergency"] == 7
    assert body["totals"]["grand_total"] == 7

    saved = json.loads(data_file.read_text(encoding="utf-8"))
    assignment = saved["day_assignments"][DAY][0]
    assert assignment["conscript_count"] == 7


def test_an_emergency_row_shows_up_even_before_anyone_types_its_count(client):
    """الفلتر القديم كان بيخفي الصف اللي عدده صفر، فخدمة لسه ما اتكتبش عددها
    كانت **بتختفي** بدل ما تفكّر المشغّل إنها ناقصة — والنتيجة ورقة طوارئ
    فاضية في كل يوم من أيام الأرشيف الـ101 رغم إن فيها 1257 خدمة طارئة."""
    _add_assignment(client, name="خدمة طارئة تانية", section="الخدمات الطارئة")

    body = client.get(f"/api/counts/{DAY}").get_json()
    assert len(body["emergency"]) == 1
    row = body["emergency"][0]
    assert row["name"] == "خدمة طارئة تانية" and row["count"] == 0
    assert row["needs_count"] is True
    assert body["emergency_missing"] == 1
    assert body["totals"]["emergency"] == 0, "الصف بيبان، بس بيدخل الإجمالي بصفر لحد ما يتكتب"


def test_the_board_strength_is_shown_next_to_the_count_as_a_hint(client):
    """«conscripts» معناه وحدة/فرد/طلبة مش «عدد مجندين» — بيتعرض كتلميح
    جنب الخانة، وعمره ما بيتجمع في الإجمالي."""
    _add_assignment(client, name="إزالة الأربعين", section="الخدمات الطارئة",
                    personnel_ids=[], conscripts=[{"class": "وحدة", "count": 0},
                                                   {"class": "فرد", "count": 1}])

    row = client.get(f"/api/counts/{DAY}").get_json()["emergency"][0]
    assert row["strength"] == "فرد ×1"
    assert row["count"] == 0


def test_the_count_can_be_typed_from_the_counts_page_itself(client, data_file):
    """كان لازم تسيب الورقة وتروح تفتح خانة الخدمة على اللوحة عشان تكتب رقم —
    دلوقتي بيتكتب من هنا، وبيروح لنفس الحقل على صف التكليف."""
    row = _add_assignment(client, name="خدمة طارئة", section="الخدمات الطارئة")

    r = client.patch(f"/api/counts/{DAY}/board/{row['id']}", json={"count": 7})
    assert r.status_code == 200
    body = r.get_json()
    assert body["emergency"][0]["count"] == 7
    assert body["totals"]["emergency"] == 7

    saved = json.loads(data_file.read_text(encoding="utf-8"))
    assert saved["day_assignments"][DAY][0]["conscript_count"] == 7, "نفس الحقل، مش نسخة تانية"


def test_typing_a_count_on_a_non_emergency_row_is_refused(client):
    row = _add_assignment(client, name="خدمة أساسية", section="الخدمات أساسية")
    assert client.patch(f"/api/counts/{DAY}/board/{row['id']}",
                        json={"count": 4}).status_code == 404


def test_the_counts_page_cannot_edit_a_closed_day_through_the_side_door(client):
    row = _add_assignment(client, name="خدمة طارئة", section="الخدمات الطارئة")
    client.post(f"/api/day-status/{DAY}/close", json={})

    assert client.patch(f"/api/counts/{DAY}/board/{row['id']}",
                        json={"count": 3}).status_code == 409
    assert client.post(f"/api/counts/{DAY}/entries",
                       json={"block": "صباحية", "name": "س", "count": 1}).status_code == 409
    assert client.post(f"/api/counts/{DAY}/reset").status_code == 409


def test_editing_the_template_freezes_a_past_days_view_first(client, frozen_today):
    """يوم فات وليه سجل (تكليف مثلًا) ولسه بيقرا القالب الحيّ — تعديل
    القالب النهاردة ما يلمسهوش، وإلا «اعداد الخدمات» بتاعته تتغيّر
    بأثر رجعي رغم إن اليومية التفصيلية نفسها ما اتلمستش."""
    _add_assignment(client)        # يسجّل DAY في DayRepo.dates() (لسه مفتوح)
    frozen_today("2026-04-15")     # يخلي DAY (2026-04-10) «فات»

    before = client.get(f"/api/counts/{DAY}").get_json()
    assert before["from_template"] is True     # لسه بيقرا القالب الحيّ

    client.post("/api/counts/template/entries",
               json={"block": "صباحية", "name": "خدمة جديدة", "count": 5})

    after = client.get(f"/api/counts/{DAY}").get_json()
    assert after["from_template"] is False     # اتجمّد له نسخة قبل التعديل
    assert after["totals"] == before["totals"]
    assert [e["name"] for e in after["basic_am"]] == [e["name"] for e in before["basic_am"]]

    # يوم جاي (مش مسجّل بعد ولا فات) بيشوف التعديل عادي
    future = client.get("/api/counts/2026-06-01").get_json()
    assert future["from_template"] is True
    assert "خدمة جديدة" in [e["name"] for e in future["basic_am"]]


def test_a_day_with_no_record_at_all_is_not_frozen(client, frozen_today):
    """يوم فات بس مفيهوش أي سجل خالص (`DayRepo.dates()` ما بتشمّلوش) —
    مفيش لازمة تتجمّد له نسخة، لسه هيقرا القالب زي أي يوم جاي."""
    frozen_today("2026-04-15")
    client.post("/api/counts/template/entries",
               json={"block": "صباحية", "name": "خدمة جديدة", "count": 5})

    view = client.get(f"/api/counts/{DAY}").get_json()
    assert view["from_template"] is True
    assert "خدمة جديدة" in [e["name"] for e in view["basic_am"]]


def test_template_edit_never_materialises_imported_days(client, data_file, frozen_today):
    imported = "2023-10-01"
    app_day = "2026-04-10"
    data = json.loads(data_file.read_text(encoding="utf-8"))
    data.setdefault("day_assignments", {})[imported] = [
        {"id": "AS-0001", "name": "خدمة مستوردة", "kind": "خارجية"}]
    data.setdefault("day_import", {})[imported] = {
        "batch": "IMP-1", "at": "2026-09-30T12:00:00", "sources": []}
    data.setdefault("day_assignments", {})[app_day] = [
        {"id": "AS-0001", "name": "خدمة النظام", "kind": "خارجية"}]
    data_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    frozen_today("2026-04-15")

    client.post("/api/counts/template/entries",
                json={"block": "صباحية", "name": "خدمة جديدة", "count": 5})

    stored = json.loads(data_file.read_text(encoding="utf-8"))
    assert imported not in stored.get("service_counts", {})
    assert app_day in stored.get("service_counts", {})


def test_template_edit_does_not_freeze_days_before_first_in_app_assignment(
        client, data_file, frozen_today):
    old_status_day = "2024-01-01"
    app_day = "2026-04-10"
    data = json.loads(data_file.read_text(encoding="utf-8"))
    data.setdefault("day_status", {})[old_status_day] = {"closed": True}
    data.setdefault("day_assignments", {})[app_day] = [
        {"id": "AS-0001", "name": "خدمة النظام", "kind": "خارجية"}]
    data_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    frozen_today("2026-04-15")

    client.post("/api/counts/template/entries",
                json={"block": "صباحية", "name": "خدمة جديدة", "count": 5})

    stored = json.loads(data_file.read_text(encoding="utf-8"))
    assert old_status_day not in stored.get("service_counts", {})
    assert app_day in stored.get("service_counts", {})


def test_each_block_carries_its_own_total_and_they_add_up(client):
    """الورقة فيها «المجموع» تحت كل قسم و«إجمالي اعداد الخدمات» تحت خالص —
    والاتنين لازم يطلعوا من نفس الأرقام مش من عدّتين مختلفتين."""
    client.post(f"/api/counts/{DAY}/entries", json={"block": "صباحية", "name": "أ", "count": 5})
    client.post(f"/api/counts/{DAY}/entries", json={"block": "ليلية", "name": "ب", "count": 3})
    client.post(f"/api/counts/{DAY}/entries", json={"block": "طوارئ", "name": "ج", "count": 4})
    row = _add_assignment(client, name="طارئة اليوم", section="الخدمات الطارئة")
    client.patch(f"/api/counts/{DAY}/board/{row['id']}", json={"count": 6})

    t = client.get(f"/api/counts/{DAY}").get_json()["totals"]
    assert (t["basic_am"], t["basic_pm"], t["recurring"], t["emergency_day"]) == (5, 3, 4, 6)
    assert t["emergency"] == 10, "الطوارئ في الورقة رقم واحد: المتكررة + اليومي"
    assert t["grand_total"] == 18 == t["basic_am"] + t["basic_pm"] + t["emergency"]

    s = client.get(f"/api/counts/{DAY}").get_json()["services"]
    assert (s["basic_am"], s["basic_pm"], s["recurring"], s["emergency_day"]) == (1, 1, 1, 1)
    assert s["total"] == 4, "عدد الخدمات رقم تاني غير عدد المجندين"


def test_basic_section_assignment_is_not_counted_as_emergency(client):
    """خدمة أساسية عليها عدد مجندين على اللوحة مش هي المقصودة هنا — بلوك
    الطوارئ يقرا قسم «الخدمات الطارئة» بس."""
    _add_assignment(client, name="خدمة أساسية", section="الخدمات أساسية", conscript_count=9)

    body = client.get(f"/api/counts/{DAY}").get_json()
    assert body["emergency"] == []


# ---------- قسم مخصّص كتبه المشغّل بإيده لليوم ده بس ----------

def test_a_custom_section_typed_on_the_board_gets_its_own_block_here(client):
    """يوم فيه مباراة: قسم «خدمات مباراة المصري» جديد كليًا، مالوش أي
    تسجيل مسبق — لازم يظهر هنا في بلوكه المستقل بمجرد ما يتحفظ على اللوحة."""
    row = _add_assignment(client, name="تأمين مدرجات الاستاد",
                          section="خدمات مباراة المصري", conscript_count=12)

    body = client.get(f"/api/counts/{DAY}").get_json()
    assert len(body["custom_sections"]) == 1
    section = body["custom_sections"][0]
    assert section["name"] == "خدمات مباراة المصري"
    assert section["rows"][0]["assignment_id"] == row["id"]
    assert section["rows"][0]["count"] == 12
    assert body["totals"]["custom"] == 12
    assert body["totals"]["grand_total"] == 12
    assert body["services"]["custom"] == 1


def test_two_different_custom_sections_stay_in_separate_blocks(client):
    _add_assignment(client, name="تأمين مدرجات الاستاد",
                    section="خدمات مباراة المصري", conscript_count=10)
    _add_assignment(client, name="تأمين مدرجات الاستاد",
                    section="خدمات مباراة الزمالك", conscript_count=8)

    sections = {s["name"]: s for s in client.get(f"/api/counts/{DAY}").get_json()["custom_sections"]}
    assert set(sections) == {"خدمات مباراة المصري", "خدمات مباراة الزمالك"}
    assert sections["خدمات مباراة المصري"]["rows"][0]["count"] == 10
    assert sections["خدمات مباراة الزمالك"]["rows"][0]["count"] == 8


def test_a_custom_section_with_no_days_left_disappears_on_its_own(client):
    """مفيش قايمة أقسام مخزّنة تتنضّف — القسم بيختفي لوحده لما آخر صف
    عليه يتشال، زي أي خدمة عادية بالظبط."""
    row = _add_assignment(client, name="تأمين مدرجات الاستاد",
                          section="خدمات مباراة المصري")
    assert len(client.get(f"/api/counts/{DAY}").get_json()["custom_sections"]) == 1

    client.delete(f"/api/assignments/{DAY}/{row['id']}")
    assert client.get(f"/api/counts/{DAY}").get_json()["custom_sections"] == []


def test_the_count_of_a_custom_section_row_can_be_typed_from_the_counts_page(client, data_file):
    row = _add_assignment(client, name="تأمين مدرجات الاستاد", section="خدمات مباراة المصري")

    r = client.patch(f"/api/counts/{DAY}/board/{row['id']}", json={"count": 15})
    assert r.status_code == 200
    assert r.get_json()["custom_sections"][0]["rows"][0]["count"] == 15

    saved = json.loads(data_file.read_text(encoding="utf-8"))
    assert saved["day_assignments"][DAY][0]["conscript_count"] == 15, "نفس حقل اللوحة بالظبط"


def test_a_custom_section_is_scoped_to_its_own_day_only(client):
    """«لليوم ده بس مش في العموم» — نفس القسم في يوم تاني قسم مختلف
    مالوش أي علاقة بيه."""
    _add_assignment(client, name="تأمين مدرجات الاستاد", section="خدمات مباراة المصري")

    assert client.get(f"/api/counts/{OTHER_DAY}").get_json()["custom_sections"] == []


def test_naming_a_new_section_after_a_computed_one_is_refused(client):
    """«الراحات»/«التقصيرات»/«الخوارج»/«عمل بالإدارة» عناوين محسوبة من حالة
    الضباط — لو خدمة اتسمّت بنفس اسم واحد منهم هتختفي من اللوحة تمامًا،
    فالكتابة بترفض بدل ما تسيب فخ."""
    for reserved in ("الراحات", "التقصيرات", "الخوارج", "عمل بالإدارة"):
        r = client.post(f"/api/assignments/{DAY}",
                        json={"name": "خدمة", "kind": "خارجية", "section": reserved})
        assert r.status_code == 400, reserved


def test_an_extremely_long_section_name_is_refused(client):
    r = client.post(f"/api/assignments/{DAY}",
                    json={"name": "خدمة", "kind": "خارجية", "section": "س" * 61})
    assert r.status_code == 400
