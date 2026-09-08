"""تاريخ الضابط — الرتبة والمنصب والقسم وجهة التشغيل بتاريخ سريان.

المشكلة اللي بيحلها: الملف كان بيحتفظ بقيمة واحدة حالية، فإعادة توليد أي
يوم قديم كانت بتطبع بيانات النهاردة. يومية 5/7 في الوورد بتقول
«مقدم / أشرف الشريف» والملف كان فيه «عقيد» (اترقّى بعد كده)، و«علي فاروق»
كان مكتوب في قسم الخوارج بمنصب «انتداب من قسم عتاقة» والملف بيقول
«رئيس قسم الأمن والتحريات» — ده منصب ضابط تاني خالص في نفس اليوم.
"""


def _row(client, officer_id, day):
    d = client.get(f"/api/duty/{day}").get_json()
    return next(r for r in d["rows"] if r["id"] == officer_id)


def _patch(client, **body):
    return client.patch("/api/person/OFF-002", json=body)


def test_promotion_does_not_rewrite_older_days(client):
    _patch(client, role="مقدم", effective_from="2026-06-01")
    _patch(client, role="عقيد", effective_from="2026-08-01")

    assert _row(client, "OFF-002", "2026-07-05")["role"] == "مقدم"
    assert _row(client, "OFF-002", "2026-08-15")["role"] == "عقيد"


def test_post_change_is_dated_too(client):
    _patch(client, post="انتداب من قسم عتاقة", effective_from="2026-06-01")
    _patch(client, post="رئيس قسم الأمن والتحريات", effective_from="2026-09-01")

    assert _row(client, "OFF-002", "2026-07-05")["post"] == "انتداب من قسم عتاقة"
    assert _row(client, "OFF-002", "2026-09-05")["post"] == "رئيس قسم الأمن والتحريات"


def test_officer_section_follows_the_same_rule(client):
    """قسم جدول الوورد (القوة / الحراسات المشددة / الخوارج) تابع لوضع
    الضابط التنظيمي، وبيتغيّر مع حركة الضباط."""
    _patch(client, section="القوة", effective_from="2026-06-01")
    _patch(client, section="الحراسات المشددة", effective_from="2026-08-01")

    assert _row(client, "OFF-002", "2026-07-01")["section"] == "القوة"
    assert _row(client, "OFF-002", "2026-08-05")["section"] == "الحراسات المشددة"


def test_unknown_section_is_refused(client):
    assert _patch(client, section="قسم مخترع").status_code == 400


def test_current_values_mirror_the_latest_record(client):
    """أي كود بيقرا person["role"] مباشرةً لازم يفضل شغّال."""
    _patch(client, role="مقدم", effective_from="2026-06-01")
    _patch(client, role="عقيد", effective_from="2026-08-01")
    officer = next(o for o in client.get("/api/bootstrap/officers").get_json()["officers"]["active"]
                   if o["id"] == "OFF-002")
    assert officer["role"] == "عقيد"
    assert [h["from"] for h in officer["history"]] == ["2020-01-01", "2026-06-01", "2026-08-01"]


def test_same_effective_date_corrects_instead_of_stacking(client):
    _patch(client, role="مقدم", effective_from="2026-06-01")
    _patch(client, role="رائد", effective_from="2026-06-01")
    officer = next(o for o in client.get("/api/bootstrap/officers").get_json()["officers"]["active"]
                   if o["id"] == "OFF-002")
    dates = [h["from"] for h in officer["history"]]
    assert dates == sorted(set(dates)), "مفيش سجلّين بنفس تاريخ السريان"
    assert _row(client, "OFF-002", "2026-07-01")["role"] == "رائد"


def test_search_attachment_is_dated(client):
    """«+N بحث» تابع لجهة تشغيل الضابط، وهي بتتغيّر: رئيس مباحث الإدارة
    اتكتب في الوورد «(تشغيل من ادارة البحث)» من 1/9 وقبلها لأ."""
    _patch(client, search_attached=True, effective_from="2026-09-01")
    assert _row(client, "OFF-002", "2026-08-20")["search_attached"] is False
    assert _row(client, "OFF-002", "2026-09-05")["search_attached"] is True


def test_search_attached_officer_counts_in_the_search_cell(client):
    _patch(client, search_attached=True, effective_from="2026-06-01")
    client.post("/api/assignments/2026-07-01",
                json={"service_id": "SVC-001", "shift": "صباحية",
                      "officer_ids": ["OFF-002"]})
    s = client.get("/api/duty/2026-07-01").get_json()["summary"]
    assert s["خارجية"]["بحث"] == 1
    assert s["خارجية"]["صباحية"] == 0
    assert s["balanced"] is True


def test_bad_effective_date_is_refused(client):
    assert _patch(client, role="مقدم", effective_from="مش-تاريخ").status_code == 400
