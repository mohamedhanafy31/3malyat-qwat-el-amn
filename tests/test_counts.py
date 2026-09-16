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
                              "emergency_day": 0, "emergency": 0, "grand_total": 0}
    assert body["services"] == {"basic_am": 0, "basic_pm": 0, "recurring": 0,
                                "emergency_day": 0, "total": 0}
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

    r = client.patch(f"/api/counts/{DAY}/emergency/{row['id']}", json={"count": 7})
    assert r.status_code == 200
    body = r.get_json()
    assert body["emergency"][0]["count"] == 7
    assert body["totals"]["emergency"] == 7

    saved = json.loads(data_file.read_text(encoding="utf-8"))
    assert saved["day_assignments"][DAY][0]["conscript_count"] == 7, "نفس الحقل، مش نسخة تانية"


def test_typing_a_count_on_a_non_emergency_row_is_refused(client):
    row = _add_assignment(client, name="خدمة أساسية", section="الخدمات أساسية")
    assert client.patch(f"/api/counts/{DAY}/emergency/{row['id']}",
                        json={"count": 4}).status_code == 404


def test_the_counts_page_cannot_edit_a_closed_day_through_the_side_door(client):
    row = _add_assignment(client, name="خدمة طارئة", section="الخدمات الطارئة")
    client.post(f"/api/day-status/{DAY}/close", json={})

    assert client.patch(f"/api/counts/{DAY}/emergency/{row['id']}",
                        json={"count": 3}).status_code == 409
    assert client.post(f"/api/counts/{DAY}/entries",
                       json={"block": "صباحية", "name": "س", "count": 1}).status_code == 409
    assert client.post(f"/api/counts/{DAY}/reset").status_code == 409


def test_each_block_carries_its_own_total_and_they_add_up(client):
    """الورقة فيها «المجموع» تحت كل قسم و«إجمالي اعداد الخدمات» تحت خالص —
    والاتنين لازم يطلعوا من نفس الأرقام مش من عدّتين مختلفتين."""
    client.post(f"/api/counts/{DAY}/entries", json={"block": "صباحية", "name": "أ", "count": 5})
    client.post(f"/api/counts/{DAY}/entries", json={"block": "ليلية", "name": "ب", "count": 3})
    client.post(f"/api/counts/{DAY}/entries", json={"block": "طوارئ", "name": "ج", "count": 4})
    row = _add_assignment(client, name="طارئة اليوم", section="الخدمات الطارئة")
    client.patch(f"/api/counts/{DAY}/emergency/{row['id']}", json={"count": 6})

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
