"""اللوحة ويومية الضباط كعرضين على سجل تكليف واحد.

كل اختبار هنا بيقفل خطأ **مقيس فعلًا** في مراجعة الـ101 يوم — الاسم
بيقول الخطأ اللي كان بيحصل، مش اسم الدالة.
"""
DAY = "2026-04-10"


def _add(client, day=DAY, **over):
    body = {"service_id": "SVC-001", "shift": "صباحية"}
    body.update(over)
    return client.post(f"/api/assignments/{day}", json=body)


def _summary(client, day=DAY):
    return client.get(f"/api/duty/{day}").get_json()["summary"]


def _row(client, officer_id, day=DAY):
    d = client.get(f"/api/duty/{day}").get_json()
    return next(r for r in d["rows"] if r["id"] == officer_id)


def _section(client, name, day=DAY):
    b = client.get(f"/api/board/{day}").get_json()
    return next(s for s in b["sections"] if s["name"] == name)


# ---------- التكليف الواحد يظهر في العرضين ----------

def test_assignment_shows_in_both_views_at_once(client):
    """مفيش مزامنة تتأخّر أو تفشل — العرضين بيقروا من نفس السجل."""
    assert _summary(client)["صافي"] == 2
    _add(client, officer_ids=["OFF-002"])

    s = _summary(client)
    assert s["صافي"] == 1
    assert s["خارجية"]["صباحية"] == 1
    assert s["balanced"] is True
    assert _row(client, "OFF-002")["group"] == "خارجية"

    rows = _section(client, "الخدمات أساسية")["rows"]
    assert [o["id"] for r in rows for o in r["officers"]] == ["OFF-002"]


def test_removing_the_officer_leaves_no_trace_of_his_name(client):
    """الخانة كانت بتفضل عارضة اسم الضابط بعد ما يتشال منها، لأن
    sync.py كان بيفضّي officer_id وينسى officer_name."""
    entry = _add(client, officer_ids=["OFF-002"]).get_json()
    client.patch(f"/api/assignments/{DAY}/{entry['id']}", json={"officer_ids": []})

    row = _section(client, "الخدمات أساسية")["rows"][0]
    assert row["officers"] == []
    assert row["vacant"] is True
    assert "OFF-002" not in str(row), "مفيش أي أثر متبقّي للضابط"
    assert _row(client, "OFF-002")["group"] == "صافي"


def test_deleting_an_assignment_frees_the_officer(client):
    entry = _add(client, officer_ids=["OFF-002"]).get_json()
    assert client.delete(f"/api/assignments/{DAY}/{entry['id']}").status_code == 200
    assert _row(client, "OFF-002")["group"] == "صافي"
    assert _summary(client)["صافي"] == 2


def test_moving_an_assignment_updates_both_officers(client):
    entry = _add(client, officer_ids=["OFF-002"]).get_json()
    client.patch(f"/api/assignments/{DAY}/{entry['id']}", json={"officer_ids": ["OFF-001"]})
    assert _row(client, "OFF-002")["group"] == "صافي"
    assert _row(client, "OFF-001")["group"] == "خارجية"
    assert _summary(client)["balanced"] is True


# ---------- الأخطاء المقيسة في الأرشيف ----------

def test_renaming_a_service_does_not_erase_the_assignment(client):
    """كان أخطر خطأ: التكليف مخزّن بالـid لكن اللوحة كانت مخزّنة اسم
    الخدمة كنص، فإعادة التسمية كانت تمسح التكليف من يومية التشغيل في
    صمت وتسيبه ظاهر على اللوحة بالاسم القديم."""
    _add(client, officer_ids=["OFF-002"])
    before = _summary(client)

    r = client.patch("/api/services/SVC-001", json={"name": "دورية خارجية معدّلة"})
    assert r.status_code == 200

    assert _summary(client) == before, "التصنيف والأرقام مالهمش دعوة بالاسم"
    assert _row(client, "OFF-002")["group"] == "خارجية"
    # القسم الأساسي بيكتب الفترة جوّه الاسم، فالمتوقع الاسم الجديد + «صبح»
    assert _section(client, "الخدمات أساسية")["rows"][0]["label"] == "دورية خارجية معدّلة صبح"


def test_two_officers_on_the_same_service_and_shift_both_survive(client):
    """الاشتقاق القديم كان بياخد ضابط واحد لكل (خدمة، فترة) — النتيجة
    128 ضابط اختفوا من اللوحة في 65 يوم من الأرشيف."""
    _add(client, officer_ids=["OFF-001"])
    _add(client, officer_ids=["OFF-002"])

    rows = _section(client, "الخدمات أساسية")["rows"]
    assert len(rows) == 2
    assert {o["id"] for r in rows for o in r["officers"]} == {"OFF-001", "OFF-002"}
    assert _summary(client)["خارجية"]["صباحية"] == 2


def test_one_row_can_carry_two_officers(client):
    """لوحة 20/8 فيها «رائد/جمال امين  م.اول/ماركو ماجد» في خانة واحدة."""
    _add(client, officer_ids=["OFF-001", "OFF-002"])
    row = _section(client, "الخدمات أساسية")["rows"][0]
    assert [o["id"] for o in row["officers"]] == ["OFF-001", "OFF-002"]
    assert _summary(client)["خارجية"]["صباحية"] == 2


def test_a_row_with_no_officer_is_a_real_row(client):
    """1,034 صف خدمات طارئة في الأرشيف قوامها أفراد ومجندين من غير أي
    ضابط — 77% من الطارئة — وكانت مستحيلة التمثيل."""
    _add(client, officer_ids=[], conscripts=[{"class": "فض", "count": 7}],
         weapon="فض", time="9ص", party="الجناين")

    row = _section(client, "الخدمات أساسية")["rows"][0]
    assert row["vacant"] is True
    assert row["conscripts"] == [{"class": "فض", "count": 7}]
    assert (row["weapon"], row["time"], row["party"]) == ("فض", "9ص", "الجناين")
    assert _summary(client)["صافي"] == 2, "خانة بلا ضابط ما تحركش أي ضابط"


def test_the_same_officer_can_work_both_shifts(client):
    """«نوبتجي المعسكر الفرعي فترة صباحية + فترة ليلية» — نفس الضابط في
    الصفّين، والوورد بيطبعهم صفّين."""
    _add(client, officer_ids=["OFF-002"], shift="صباحية")
    _add(client, officer_ids=["OFF-002"], shift="ليلية")

    rows = _section(client, "الخدمات أساسية")["rows"]
    assert sorted(r["shift"] for r in rows) == ["صباحية", "ليلية"]
    s = _summary(client)
    assert s["balanced"] is True, "الضابط لازم يتحسب مرة واحدة بس في الإجمالي"


def test_morning_only_service_never_gets_a_night_shift(client):
    """محور 1 و2 وقول 48 والإسعاف صباحية بس — الوورد بيكتب «ــــ» في
    العمود الليلي."""
    client.patch("/api/services/SVC-001", json={"shifts": ["صباحية"]})
    entry = _add(client, shift="ليلية").get_json()
    assert entry["shift"] == "صباحية"


# ---------- حالة الضابط ----------

def test_every_word_column_of_khawarej_is_reachable(client):
    """«مرضي» و«فرقة» كانوا في الوورد 16 و30 مرة، ومكانش فيه أي طريقة
    توصّلهم لخانتهم — الحالات كانت انتداب/غياب بس."""
    for status in ("انتداب", "غياب", "مرضي", "فرقة", "طارئة"):
        client.put(f"/api/duty/{DAY}/OFF-001", json={"status": status})
        assert _summary(client)["خوارج"][status] == 1, status
        assert _row(client, "OFF-001")["bucket"] == status


def test_unknown_status_is_refused(client):
    assert client.put(f"/api/duty/{DAY}/OFF-001",
                      json={"status": "حالة مخترعة"}).status_code == 400


def test_state_survives_assignment_edits(client):
    """التقصيرة والملاحظة حالة الضابط نفسه — تعديل التكليف ما يمسهاش."""
    client.put(f"/api/duty/{DAY}/OFF-002", json={"taqseera": True, "note": "خرج بدري"})
    _add(client, officer_ids=["OFF-002"])
    row = _row(client, "OFF-002")
    assert row["taqseera"] is True and row["note"] == "خرج بدري"


def test_officer_not_on_force_that_day_is_refused(client):
    """اللوحة كانت بتعرض النشطين بس ويومية التشغيل بتقبل المتأرشفين —
    الصفحتين مكانوش شايفين نفس القايمة."""
    assert _add(client, day="2019-01-01", officer_ids=["OFF-002"]).status_code == 400
    assert client.put("/api/duty/2019-01-01/OFF-002", json={}).status_code == 404


def test_assignment_needs_a_catalog_service(client):
    """مفيش أسماء خدمات حرة — كتابة «تدخل سريع صبح» بالإيد كانت بتكسر
    الربط في صمت وتسيب الضابط في الصافي."""
    assert client.post(f"/api/assignments/{DAY}", json={"service_id": ""}).status_code == 400
    assert _add(client, service_id="SVC-999").status_code == 404


# ---------- تقسيمة اللوحة ----------

def test_board_has_the_ten_word_sections_in_order(client):
    b = client.get(f"/api/board/{DAY}").get_json()
    assert [s["name"] for s in b["sections"]] == [
        "الخدمات أساسية", "الخدمات الطارئة", "عمل بالإدارة", "الأهداف",
        "الراحات", "التقصيرات", "الخوارج",
        "ضابط عظيم وأمن المعسكر الفرعي", "ضابط عظيم الإدارة", "ضابط الأمن بالإدارة",
    ]


def test_fixed_role_blocks_always_print_both_shifts(client):
    """الوورد بيطبع صف «فترة صباحية» وصف «فترة ليلية» في كل يوم — الخانة
    الفاضية معناها «محتاجة تكليف» مش «مش موجودة»."""
    for name in ("ضابط عظيم وأمن المعسكر الفرعي", "ضابط عظيم الإدارة",
                 "ضابط الأمن بالإدارة"):
        rows = _section(client, name)["rows"]
        assert [r["shift"] for r in rows] == ["صباحية", "ليلية"], name
        assert all(r["vacant"] for r in rows)


def test_basic_section_writes_the_shift_inside_the_label(client):
    """الوورد بيكتب «تدخل سريع صبح» مش «تدخل سريع» + عمود فترة."""
    _add(client, shift="ليلية")
    assert _section(client, "الخدمات أساسية")["rows"][0]["label"] == "دورية خارجية ليل"


def test_tagged_services_stay_inside_their_section(client):
    """«خطة انتشار 6م» في لوحة 15/6 عنوان فرعي جوّه الخدمات الطارئة —
    مش جريد منفصل تحت الصفحة."""
    _add(client, tags=["خطة انتشار"])
    section = _section(client, "الخدمات أساسية")
    assert section["rows"] == []
    assert [g["tag"] for g in section["groups"]] == ["خطة انتشار"]
    assert len(section["groups"][0]["rows"]) == 1


def test_officers_with_no_service_land_in_admin_work(client):
    """قسم «عمل بالإدارة» في الوورد = الضباط اللي مالهمش خدمة، والمدير
    والوكيل دايمًا فيه."""
    client.patch("/api/command", json={"مدير الإدارة": "OFF-001"})
    rows = _section(client, "عمل بالإدارة")["rows"]
    assert {r["id"] for r in rows} == {"OFF-001", "OFF-002"}


# ---------- قواعد اتقاست على جدول الإجمالي في الوورد ----------

def test_subcamp_service_leaves_the_officer_in_net(client):
    """قوة المعسكر الفرعي مالهاش خانة في جدول إجمالي الإدارة: الوورد كتب
    ضابط «نوبتجي المعسكر الفرعي» في قايمة «الصافي» بالاسم في 11 يوم من 11."""
    client.patch("/api/services/SVC-001", json={"kind": "داخلية"})
    import json as _json
    from backend import store
    data = _json.loads(store.DATA_FILE.read_text(encoding="utf-8"))
    for svc in data["services"]:
        if svc["id"] == "SVC-001":
            svc["counts_in_summary"] = False
    store.DATA_FILE.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")

    _add(client, officer_ids=["OFF-002"])
    s = _summary(client)
    assert s["داخلية"]["صباحية"] == 0
    assert s["صافي"] == 2, "الخدمة بتظهر على اللوحة لكن مابتحركش الضابط"
    assert s["balanced"] is True
    # ولسه ظاهرة على اللوحة عادي
    assert len(_section(client, "الخدمات أساسية")["rows"]) == 1


# ---------- سلّم أولويات خانة الإجمالي ----------
# تقصيرة > حراسات > الخدمة (وفي الخدمات: اللي اتحط فيها الأول)

def _guard(client, name="هدف سوميد"):
    svc = client.post("/api/services", json={
        "name": name, "kind": "حراسات", "section": "الأهداف"}).get_json()
    return svc["id"]


def test_taqseera_beats_everything_including_targets(client):
    """ضابط على حراسة ومعاه تقصيرة → يتحسب تقصيرة."""
    _add(client, service_id=_guard(client), officer_ids=["OFF-002"])
    client.put(f"/api/duty/{DAY}/OFF-002", json={"taqseera": True})
    s = _summary(client)
    assert s["خوارج"]["تقصيرة"] == 1
    assert s["حراسات"] == 0
    assert _row(client, "OFF-002")["bucket"] == "تقصيرة"


def test_taqseera_beats_an_ordinary_service_too(client):
    _add(client, officer_ids=["OFF-002"])
    client.put(f"/api/duty/{DAY}/OFF-002", json={"taqseera": True})
    s = _summary(client)
    assert s["خوارج"]["تقصيرة"] == 1
    assert s["خارجية"]["صباحية"] == 0


def test_target_beats_an_ordinary_service_whatever_the_order(client):
    """قائد الهدف بيتحسب حراسات حتى لو الهدف مش أول خدمة في سطره —
    يومية 31/8: «مدرجات الدرجة الاولي + عمل بهدف كهرباء عتاقة»."""
    _add(client, officer_ids=["OFF-002"])                       # خارجية الأول
    _add(client, service_id=_guard(client), officer_ids=["OFF-002"])   # حراسة بعدها
    s = _summary(client)
    assert s["حراسات"] == 1
    assert sum(s["خارجية"].values()) == 0


def test_among_ordinary_services_the_first_one_wins(client):
    """الخانة اللي اتحط فيها الأول هي اللي تتحسب."""
    night = client.post("/api/services", json={
        "name": "خدمة ليلية", "kind": "خارجية",
        "section": "الخدمات الطارئة"}).get_json()["id"]
    _add(client, service_id=night, officer_ids=["OFF-002"], shift="ليلية")
    _add(client, officer_ids=["OFF-002"], shift="صباحية")       # اتحط تاني
    s = _summary(client)
    assert s["خارجية"] == {"صباحية": 0, "ليلية": 1, "بحث": 0}
    assert s["balanced"] is True


def test_first_wins_across_internal_and_external_too(client):
    inside = client.post("/api/services", json={
        "name": "خدمة داخلية", "kind": "داخلية",
        "section": "الخدمات الطارئة"}).get_json()["id"]
    _add(client, officer_ids=["OFF-002"], shift="صباحية")       # خارجية الأول
    _add(client, service_id=inside, officer_ids=["OFF-002"], shift="ليلية")
    s = _summary(client)
    assert s["خارجية"]["صباحية"] == 1
    assert sum(s["داخلية"].values()) == 0
