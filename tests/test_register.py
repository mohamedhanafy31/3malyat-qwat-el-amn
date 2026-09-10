"""دفتر 43 — صف لكل ضابط، عمود لكل يوم، والخانة رمز حالته.

الدفتر ده بيتستخدم كإثبات رسمي لتواجد الفرد من عدمه في يوم معيّن (اتساءل
عنه في المحاكم بالصيغة دي)، فالاختبارات هنا بتركّز على إن كل رمز صادق
وبيرجّع لمصدره، وإن الفرق بين «مفيش سجل» و«موجود بالإدارة» واضح.
"""
DAY = "2026-04-10"


def _add(client, day=DAY, **over):
    body = {"service_id": "SVC-001", "shift": "صباحية"}
    body.update(over)
    return client.post(f"/api/assignments/{day}", json=body)


def _month(client, year=2026, month=4):
    return client.get(f"/api/register/{year}/{month}").get_json()


def _row(reg, officer_id):
    return next(r for r in reg["rows"] if r["id"] == officer_id)


def _cell(reg, officer_id, day):
    return next(c for c in _row(reg, officer_id)["cells"] if c["day"] == day)


def test_grid_is_officers_by_days_of_the_month(client):
    _add(client, officer_ids=["OFF-002"])
    reg = _month(client)
    assert len(reg["days"]) == 30                      # أبريل
    assert reg["days"][0] == "2026-04-01"
    assert all(len(r["cells"]) == 30 for r in reg["rows"])
    assert {r["id"] for r in reg["rows"]} == {"OFF-001", "OFF-002"}


def test_a_day_with_no_roster_is_not_read_as_admin_work(client):
    """أخطر التباس في سجل بيتستخدم كإثبات: غياب اليومية مش معناه إن
    الضابط كان موجود بالإدارة، ولا معناه إنه كان غايب."""
    _add(client, officer_ids=["OFF-002"])
    reg = _month(client)
    assert _cell(reg, "OFF-002", DAY)["code"] == "أ"
    blank = _cell(reg, "OFF-002", "2026-04-11")
    assert blank["code"] == "·"
    assert blank["family"] == "بدون سجل"
    assert reg["recorded_days"] == [DAY]


def test_unrecorded_days_are_excluded_from_the_tally(client):
    _add(client, officer_ids=["OFF-002"])
    tally = _row(_month(client), "OFF-002")["tally"]
    assert tally["days"] == 1, "يوم واحد بس هو اللي فيه يومية"
    assert tally["by_family"] == {"عمل": 1, "راحة": 0, "إجازة": 0, "خارج": 0}


def test_every_cell_carries_the_service_behind_it(client):
    """الضغط على الخانة لازم يوري الخدمة — ده أساس حجّية الدفتر."""
    _add(client, officer_ids=["OFF-002"])
    cell = _cell(_month(client), "OFF-002", DAY)
    assert [s["name"] for s in cell["services"]] == ["دورية خارجية"]
    assert cell["services"][0]["shift"] == "صباحية"


def test_each_state_has_its_own_symbol(client):
    """رمز مفصّل لكل حالة (غياب/مرضي/فرقة/انتداب) — مش «عمل» موحّد.
    التقصيرة والعمل العادي هما بس اللي اتقصدوا يتوحّدوا (اختبار تاني)."""
    codes = {}
    for status in ("غياب", "مرضي", "فرقة", "انتداب"):
        client.put(f"/api/duty/{DAY}/OFF-001", json={"status": status})
        codes[status] = _cell(_month(client), "OFF-001", DAY)["code"]
    assert len(set(codes.values())) == 4, codes
    assert codes["غياب"] == "غ" and codes["مرضي"] == "م" and codes["فرقة"] == "ف"
    assert codes["انتداب"] == "ن"


def test_any_working_shift_or_duty_gets_the_same_present_symbol(client):
    """دفتر 43 بيثبت التواجد بس — نوع الخدمة (صباحية/ليلية/حراسة/داخلية)
    تفصيلة موجودة في يومية التشغيل نفسها، مش في رمز الدفتر."""
    _add(client, officer_ids=["OFF-002"], shift="صباحية")
    assert _cell(_month(client), "OFF-002", DAY)["code"] == "أ"

    client.post("/api/assignments/2026-04-12",
                json={"service_id": "SVC-001", "shift": "ليلية",
                      "officer_ids": ["OFF-001"]})
    assert _cell(_month(client), "OFF-001", "2026-04-12")["code"] == "أ"


def test_taqseera_keeps_a_compound_symbol(client):
    """التقصيرة اشتغل وخرج بدري — مش عمل عادي ومش خوارج، فرمزها «أ ت»
    مركّب بدل ما تختفي جوه «أ» أو تاخد رمز مستقل زي الغياب."""
    client.put(f"/api/duty/{DAY}/OFF-001", json={"taqseera": True})
    assert _cell(_month(client), "OFF-001", DAY)["code"] == "أ ت"


def test_daily_totals_answer_who_was_present(client):
    _add(client, officer_ids=["OFF-002"])
    client.put(f"/api/duty/{DAY}/OFF-001", json={"status": "غياب"})
    totals = next(t for t in _month(client)["totals"] if t["day"] == DAY)
    assert totals == {"day": DAY, "recorded": True, "force": 2,
                      "working": 1, "resting": 0, "on_leave": 0, "away": 1}


def test_scheduled_rest_and_unscheduled_leave_get_different_symbols(client):
    """الراحة المرتبة مسبقًا (نظام راحة الضابط) رمزها «ر»، وأي إجازة تانية
    (طارئة/مصيف/مجمعة) رمزها «ج» — الفرق مبني على نوع الإجازة مش مجرد
    وجودها."""
    client.post("/api/leaves", json={"person_id": "OFF-001", "type": "أسبوعية",
                                      "start": DAY, "end": DAY})
    assert _cell(_month(client), "OFF-001", DAY)["code"] == "ر"

    client.post("/api/leaves", json={"person_id": "OFF-002", "type": "إجازة مصيف",
                                      "start": DAY, "end": DAY})
    assert _cell(_month(client), "OFF-002", DAY)["code"] == "ج"


def test_emergency_leave_status_is_a_leave_not_a_rest(client):
    """«طارئة» ليها بكت مستقل أصلًا (خوارج/طارئة) — لازم يترجم «ج» زي أي
    إجازة، مش «أ» زي الكود القديم قبل الفصل بين العمل والإجازة."""
    client.post("/api/leaves", json={"person_id": "OFF-001", "type": "إجازة طارئة",
                                      "start": DAY, "end": DAY})
    assert _cell(_month(client), "OFF-001", DAY)["code"] == "ج"


def test_medical_officer_gets_only_present_or_rest_no_third_option(client):
    """ضابط العيادة كان بياخد «ط» طول الأيام حتى وهو شغال عادي. دلوقتي
    مالوش غير حالتين بس: شغال «أ» أو مرتاح «ر» — من غير تفرقة راحة/إجازة
    زي باقي الضباط، حتى لو الإجازة نوعها غير مرتب (مصيف/طارئة/مجمعة)."""
    client.patch("/api/medical-officers", json={"officer_ids": ["OFF-001"]})
    _add(client, day=DAY, officer_ids=["OFF-001"])
    assert _cell(_month(client), "OFF-001", DAY)["code"] == "أ"

    client.post("/api/leaves", json={"person_id": "OFF-001", "type": "أسبوعية",
                                      "start": "2026-04-11", "end": "2026-04-11"})
    assert _cell(_month(client), "OFF-001", "2026-04-11")["code"] == "ر"

    # إجازة غير مرتبة (مصيف) — عادي كانت هتبقى «ج»، لكن ضابط العيادة
    # مالوش تالت: لسه «ر».
    client.post("/api/leaves", json={"person_id": "OFF-001", "type": "إجازة مصيف",
                                      "start": "2026-04-12", "end": "2026-04-12"})
    assert _cell(_month(client), "OFF-001", "2026-04-12")["code"] == "ر"

    codes = {c["code"] for c in _row(_month(client), "OFF-001")["cells"]}
    assert codes <= {"أ", "ر", "·"}, codes


def test_officer_who_left_mid_month_is_marked_apart(client):
    """مش على القوة ≠ غايب ≠ مفيش سجل — تلات حالات مختلفة، ولازم تفضل
    مميزة عن بعضها في سجل بيثبت التواجد."""
    _add(client, officer_ids=["OFF-002"])                    # 10 أبريل: بالقوة
    client.post("/api/assignments/2026-04-15",
                json={"service_id": "SVC-001", "officer_ids": ["OFF-001"]})
    client.post("/api/person/OFF-002/remove", json={"leave_date": "2026-04-12"})

    reg = _month(client)
    assert _cell(reg, "OFF-002", DAY)["code"] == "أ"          # كان بالقوة
    # بعد خروجه بيفضل «—» حتى في الأيام اللي مالهاش يومية: خروجه من القوة
    # معلومة مؤكدة من تاريخ خروجه، مش نقص في السجل
    assert _cell(reg, "OFF-002", "2026-04-15")["code"] == "—"
    assert _cell(reg, "OFF-002", "2026-04-20")["code"] == "—"
    # والضابط اللي لسه بالقوة بيفضل «·» في اليوم اللي مالوش يومية
    assert _cell(reg, "OFF-001", "2026-04-20")["code"] == "·"


def test_an_officer_never_on_force_gets_no_row(client):
    """الدفتر بيعرض اللي كانوا على القوة في الشهر ده بس."""
    client.post("/api/person/OFF-002/remove", json={"leave_date": "2026-03-01"})
    client.post("/api/assignments/2026-04-15",
                json={"service_id": "SVC-001", "officer_ids": ["OFF-001"]})
    assert {r["id"] for r in _month(client)["rows"]} == {"OFF-001"}


def test_officer_page_covers_every_recorded_day(client):
    _add(client, officer_ids=["OFF-002"])
    client.post("/api/assignments/2026-05-02",
                json={"service_id": "SVC-001", "officer_ids": ["OFF-002"]})
    out = client.get("/api/register/officer/OFF-002").get_json()
    assert out["tally"]["days"] == 2
    assert [m["month"] for m in out["months"]] == ["2026-04", "2026-05"]
    assert out["tally"]["services"] == [{"name": "دورية خارجية", "count": 2}]


def test_officer_page_counts_services_by_name(client):
    """«حصر لعدد الخدمات وأنواعها» — الخدمة بالاسم مش بالخانة بس."""
    client.post("/api/services", json={"name": "هدف سوميد", "kind": "حراسات",
                                        "section": "الأهداف"})
    guard = client.get("/api/bootstrap/catalog").get_json()["services"][-1]["id"]
    _add(client, officer_ids=["OFF-002"])
    _add(client, day="2026-04-11", service_id=guard, officer_ids=["OFF-002"])
    out = client.get("/api/register/officer/OFF-002").get_json()
    assert {s["name"]: s["count"] for s in out["tally"]["services"]} == {
        "دورية خارجية": 1, "هدف سوميد": 1}
    assert out["tally"]["by_code"] == {"أ": 2}


def test_legend_covers_every_code_in_use(client):
    _add(client, officer_ids=["OFF-002"])
    reg = _month(client)
    known = {l["code"] for l in reg["legend"]}
    used = {c["code"] for r in reg["rows"] for c in r["cells"]}
    assert used <= known, used - known


def test_bad_month_and_unknown_officer_are_refused(client):
    assert client.get("/api/register/2026/13").status_code == 400
    assert client.get("/api/register/officer/OFF-999").status_code == 404


def test_register_codes_cover_every_group_bucket_duty_can_produce():
    """لو duty.py قدر ينتج (group, bucket) مالوش رمز صريح، cell_for() هترجع
    رمز تلقائي بالسكوت (أول حرف) — والدليل الوحيد إنه حصل هو تحذير في
    اللوج. الاختبار ده بيمنع النسيان: أي إضافة حالة/نوع راحة/فترة جديدة
    من غير تحديث REGISTER_CODES تفشّل هنا بدل ما تظهر كرمز غلط في الدفتر.

    القايمة تحت بترصد كل فروع `duty._bucket`/`duty._first_cell` يدويًا —
    أي تعديل هناك لازم يتبعه تحديث هنا. بكت «راحة» (خوارج أو طبية) مستثنى
    من REGISTER_CODES نفسها لأنه بيتحدد في cell_for() من نوع الإجازة —
    اختبار تاني تحت بيتأكد إن كل نوع إجازة موجود ليه كود صريح هناك.
    """
    from backend.assignments import OFFICER_STATUSES
    from backend.constants import LEAVE_BUCKET, LEAVE_TYPES, SHIFTS
    from backend.register import REGISTER_CODES

    possible = {("خوارج", status) for status in OFFICER_STATUSES}
    possible.add(("طبية", "موجود"))
    possible |= {("خوارج", LEAVE_BUCKET.get(t, "راحة")) for t in LEAVE_TYPES}
    possible.add(("خوارج", "تقصيرة"))
    possible.add(("حراسات", None))
    possible.add(("خارجية", "بحث"))
    possible |= {("خارجية", s) for s in SHIFTS}
    possible |= {("داخلية", s) for s in SHIFTS}
    possible.add(("خوارج", "فرقة"))
    possible.add(("صافي", None))
    # بكت "راحة" (خوارج أو طبية) مقصود مش موجود — منطقه ديناميكي في cell_for()
    possible.discard(("خوارج", "راحة"))

    missing = possible - set(REGISTER_CODES)
    assert not missing, f"لا يوجد رمز دفتر 43 لـ: {missing}"


def test_every_leave_type_resolves_to_rest_or_leave_symbol(client):
    """أي نوع إجازة (بما فيهم أنواع جديدة تتضاف بكرة لـLEAVE_TYPES) لازم
    يترجم لـ«ر» أو «ج» — مفيش نوع يقع في الرمز التلقائي البديل."""
    from backend.constants import LEAVE_TYPES

    for i, kind in enumerate(LEAVE_TYPES):
        day = f"2026-06-{i + 1:02d}"
        r = client.post("/api/leaves", json={"person_id": "OFF-001", "type": kind,
                                              "start": day, "end": day})
        assert r.status_code == 201, (kind, r.get_json())
        code = _cell(_month(client, 2026, 6), "OFF-001", day)["code"]
        assert code in ("ر", "ج", "م", "ف"), (kind, code)
