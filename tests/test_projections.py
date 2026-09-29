"""اللوحة ويومية الضباط كعرضين على سجل تكليف واحد.

كل اختبار هنا بيقفل خطأ **مقيس فعلًا** في مراجعة الـ101 يوم — الاسم
بيقول الخطأ اللي كان بيحصل، مش اسم الدالة.
"""
DAY = "2026-04-10"
OTHER_DAY = "2026-04-11"


def _add(client, day=DAY, **over):
    body = {"name": "دورية خارجية", "kind": "خارجية", "section": "الخدمات أساسية",
            "shift": "صباحية"}
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


def test_guard_kind_never_gets_a_shift(client):
    """الحراسات هدف ثابت طول اليوم — مالهاش فترة، حتى لو المشغّل بعتها."""
    entry = _add(client, name="سوميد", kind="حراسات", section="الأهداف",
                 shift="ليلية").get_json()
    assert entry["shift"] == ""


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


def test_assignment_needs_a_name_and_kind(client):
    """الاسم حر بيكتبه المشغّل — لكن لازم يبقى فيه اسم وتصنيف، وإلا
    الخانة تفضل بلا معنى في جدول الإجمالي."""
    assert client.post(f"/api/assignments/{DAY}", json={"name": ""}).status_code == 400
    assert client.post(f"/api/assignments/{DAY}",
                       json={"name": "خدمة", "kind": "تصنيف غير موجود"}).status_code == 400


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


def test_board_labels_and_tags_are_not_stored_on_services(client):
    """الاسم على اللوحة والوسوم اتشالوا من الخدمات — الحفظ بيتجاهلهم
    والصف بيتعرض باسمه بس، من غير عناوين فرعية جوّه القسم."""
    _add(client, tags=["خطة انتشار"], label_override="اسم تاني")
    stored = client.get(f"/api/assignments/{DAY}").get_json()["assignments"][0]
    assert "tags" not in stored and "label_override" not in stored
    section = _section(client, "الخدمات أساسية")
    assert section["rows"][0]["label"] == "دورية خارجية صبح"
    assert "groups" not in section


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
    _add(client, officer_ids=["OFF-002"], kind="داخلية", counts_in_summary=False)
    s = _summary(client)
    assert s["داخلية"]["صباحية"] == 0
    assert s["صافي"] == 2, "الخدمة بتظهر على اللوحة لكن مابتحركش الضابط"
    assert s["balanced"] is True
    # ولسه ظاهرة على اللوحة عادي
    assert len(_section(client, "الخدمات أساسية")["rows"]) == 1


# ---------- سلّم أولويات خانة الإجمالي ----------
# تقصيرة > حراسات > الخدمة (وفي الخدمات: اللي اتحط فيها الأول)

def test_taqseera_beats_everything_including_targets(client):
    """ضابط على حراسة ومعاه تقصيرة → يتحسب تقصيرة."""
    _add(client, name="سوميد", kind="حراسات", section="الأهداف", officer_ids=["OFF-002"])
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
    _add(client, name="سوميد", kind="حراسات", section="الأهداف",
         officer_ids=["OFF-002"])                                # حراسة بعدها
    s = _summary(client)
    assert s["حراسات"] == 1
    assert sum(s["خارجية"].values()) == 0


def test_among_ordinary_services_the_first_one_wins(client):
    """الخانة اللي اتحط فيها الأول هي اللي تتحسب."""
    _add(client, name="خدمة ليلية", section="الخدمات الطارئة",
         officer_ids=["OFF-002"], shift="ليلية")
    _add(client, officer_ids=["OFF-002"], shift="صباحية")       # اتحط تاني
    s = _summary(client)
    assert s["خارجية"] == {"صباحية": 0, "ليلية": 1, "بحث": 0}
    assert s["balanced"] is True


def test_first_wins_across_internal_and_external_too(client):
    _add(client, officer_ids=["OFF-002"], shift="صباحية")       # خارجية الأول
    _add(client, name="خدمة داخلية", kind="داخلية", section="الخدمات الطارئة",
         officer_ids=["OFF-002"], shift="ليلية")
    s = _summary(client)
    assert s["خارجية"]["صباحية"] == 1
    assert sum(s["داخلية"].values()) == 0


# ---------- قسم مخصّص كتبه المشغّل بإيده لليوم ده بس ----------

def test_a_hand_typed_section_appears_at_the_end_instead_of_vanishing(client):
    """قسم زي «خدمات مباراة المصري» مش من العشرة — لازم يظهر كقسم مستقل
    في آخر اللوحة بدل ما يختفي."""
    _add(client, name="تأمين مدرجات الاستاد", section="خدمات مباراة المصري",
        officer_ids=["OFF-002"])
    b = client.get(f"/api/board/{DAY}").get_json()
    names = [s["name"] for s in b["sections"]]
    assert "خدمات مباراة المصري" in names
    section = next(s for s in b["sections"] if s["name"] == "خدمات مباراة المصري")
    assert section["type"] == "services"
    assert section["rows"][0]["name"] == "تأمين مدرجات الاستاد"


def test_a_custom_section_is_scoped_to_the_day_it_was_typed_on(client):
    _add(client, name="تأمين مدرجات الاستاد", section="خدمات مباراة المصري")
    other_day_names = [s["name"] for s in client.get(f"/api/board/{OTHER_DAY}").get_json()["sections"]]
    assert "خدمات مباراة المصري" not in other_day_names


def test_section_names_offered_for_autocomplete_include_official_and_used_custom_ones(client):
    """مودال الخانة بيقترح القسمين الحرّين + كل قسم مخصّص استُخدم في أي
    يوم — عشان اسم اتعمل قبل كده يفضل متاح ومايتكتبش بصورة مختلفة."""
    _add(client, name="تأمين مدرجات الاستاد", section="خدمات مباراة المصري")
    names = client.get(f"/api/board/{DAY}").get_json()["section_names"]
    assert "الخدمات أساسية" in names and "الخدمات الطارئة" in names
    assert "خدمات مباراة المصري" in names
    # الاقتراحات عامة عبر الأيام، حتى لو اليوم المفتوح نفسه ما لمسوش.
    other_names = client.get(f"/api/board/{OTHER_DAY}").get_json()["section_names"]
    assert "خدمات مباراة المصري" in other_names


def test_naming_a_section_after_a_computed_one_is_rejected_on_edit_too(client):
    row = _add(client, section="خدمات مباراة المصري").get_json()
    r = client.patch(f"/api/assignments/{DAY}/{row['id']}", json={"section": "الخوارج"})
    assert r.status_code == 400


# ---------- قائد الهدف العام (خانة ثابتة) مقابل الضابط المعيّن بالهدف ----------

def _make_commander(client, officer_id, post, effective_from="2020-01-01"):
    r = client.patch(f"/api/person/{officer_id}",
                     json={"post": post, "effective_from": effective_from})
    assert r.status_code == 200, r.get_json()


def _target_row(client, name, day=DAY):
    section = _section(client, "الأهداف", day)
    return next(r for r in section["rows"] if r["name"] == name)


def test_the_eight_fixed_targets_always_show_up_even_with_no_data(client):
    """الأهداف قايمة مغلقة — بتظهر بصفوفها الثمانية كل يوم حتى لو محدش
    عيّن حد في أي واحد منهم، عكس باقي الأقسام اللي محتاجة «+ إضافة»."""
    names = [r["name"] for r in _section(client, "الأهداف")["rows"]]
    assert names == ["مشرف الأهداف", "سوميد", "أنابيب البترول", "عيون موسي",
                     "مصر للبترول", "كهرباء عتاقة", "كهرباء السخنة", "هلة المحجر"]
    assert all(r["vacant"] for r in _section(client, "الأهداف")["rows"])


def test_the_target_commander_is_read_from_the_officers_fixed_post(client):
    """قائد الهدف خانة ثابتة — بتتحدد من منصب الضابط مش من تكليف اليوم."""
    _make_commander(client, "OFF-001", "قائد هدف سوميد")
    _add(client, name="سوميد", section="الأهداف", officer_ids=["OFF-002"])

    row = _target_row(client, "سوميد")
    assert [c["id"] for c in row["commander"]] == ["OFF-001"]
    # الضابط المعيّن فعليًا (OFF-002) مختلف عن القائد الثابت (OFF-001)
    assert [o["id"] for o in row["officers"]] == ["OFF-002"]


def test_a_target_with_no_registered_commander_has_an_empty_list(client):
    row = _target_row(client, "كهرباء عتاقة")
    assert row["commander"] == []


def test_an_officer_archived_before_the_day_is_not_shown_as_a_target_commander(client):
    """قادة الأهداف بيتاخدوا من الضباط اللي على القوة فعلًا في اليوم ده —
    مش من أي ضابط اتسجّل يومًا في السيستم. ضابط اتأرشف ومنصبه القديم لسه
    متسجّل «قائد هدف سوميد» ما يظهرش قائد لهدف مالوش علاقة بيه دلوقتي."""
    _make_commander(client, "OFF-001", "قائد هدف سوميد")
    # leave_date بعد راحة OFF-001 المسجّلة في fixture (2026-01-10) — قبلها
    # كان بيترفض 409 لوجود راحة مسجّلة بعد تاريخ الخروج (test_force_lifecycle.py).
    r = client.post("/api/person/OFF-001/remove", json={"leave_date": "2026-01-11"})
    assert r.status_code == 200, r.get_json()

    row = _target_row(client, "سوميد")   # DAY = 2026-04-10, بعد الأرشفة
    assert row["commander"] == []


def test_the_targets_supervisor_commander_is_the_strict_guards_section_head(client):
    """«مشرف الأهداف» صف مختلف عن باقي السبعة — مالوش منصب «قائد هدف مشرف
    الأهداف»، المسئول عنه هو رئيس قسم الحراسات المشددة نفسه (كل الأهداف
    تبع الحراسات المشددة أصلًا)."""
    _make_commander(client, "OFF-001", "رئيس قسم الحراسات المشددة")
    row = _target_row(client, "مشرف الأهداف")
    assert [c["id"] for c in row["commander"]] == ["OFF-001"]


def test_commander_matching_tolerates_arabic_spelling_variants(client):
    """الأرشيف فيه «هلة المحجر» و«هله المحجر» بيتكتبوا الاتنين — لازم
    يتطابقوا زي أي مقارنة عربي تانية في السيستم."""
    _make_commander(client, "OFF-001", "قائد هدف هله المحجر")
    row = _target_row(client, "هلة المحجر")
    assert [c["id"] for c in row["commander"]] == ["OFF-001"]


def test_commander_reflects_the_post_as_it_was_on_that_day(client):
    """المنصب بيتغيّر بالترقيات — لوحة قديمة لازم تطبع القائد اللي كان
    وقتها، مش القائد الحالي بعد نقل الضابط."""
    _make_commander(client, "OFF-001", "قائد هدف سوميد", effective_from="2020-01-01")
    _make_commander(client, "OFF-002", "قائد هدف سوميد", effective_from="2026-04-11")

    before = _target_row(client, "سوميد")   # DAY = 2026-04-10
    assert [c["id"] for c in before["commander"]] == ["OFF-001"]


def test_duplicate_commanders_for_the_same_target_are_both_shown(client):
    """لو اتغلط ومنصبين اتسجّلوا بنفس اسم الهدف، الاتنين بيظهروا زي ما
    هما بدل ما نختار واحد عشوائي ونخبي الغلط."""
    _make_commander(client, "OFF-001", "قائد هدف عيون موسي")
    _make_commander(client, "OFF-002", "قائد هدف عيون موسي")

    row = _target_row(client, "عيون موسي")
    assert {c["id"] for c in row["commander"]} == {"OFF-001", "OFF-002"}


def test_two_rows_typed_for_the_same_target_on_the_same_day_merge_instead_of_hiding_one(client):
    """لو اتغلط وتكليفين اتسجّلوا بنفس اسم الهدف في نفس اليوم عن طريق
    الـAPI العام (مش المودال المخصّص)، الاتنين لازم يتجمّعوا في صف واحد —
    مفيش ضابط بيختفي بصمت من الـdict comprehension القديم."""
    _add(client, name="سوميد", section="الأهداف", officer_ids=["OFF-001"])
    _add(client, name="سوميد", section="الأهداف", officer_ids=["OFF-002"])

    row = _target_row(client, "سوميد")
    assert {o["id"] for o in row["officers"]} == {"OFF-001", "OFF-002"}
    assert row["vacant"] is False


def test_the_kahraba_sakhna_target_matches_its_full_commander_post(client):
    """اسم اللوحة القديم كان «السخنة» بس بينما المنصب «قائد هدف كهرباء
    السخنة» — القائد كان بيظهر فاضي دايمًا. هجرة 012 رحّلت الاسم للكامل،
    والاختبار ده بيقفل رجوعها."""
    _make_commander(client, "OFF-001", "قائد هدف كهرباء السخنة")
    row = _target_row(client, "كهرباء السخنة")
    assert [c["id"] for c in row["commander"]] == ["OFF-001"]


def test_targets_section_is_rendered_with_the_two_role_columns(client):
    """صفحة اللوحة نفسها — الأهداف ليها شكل مختلف عن باقي الخدمات."""
    _make_commander(client, "OFF-001", "قائد هدف سوميد")
    _add(client, name="سوميد", section="الأهداف", officer_ids=["OFF-002"])

    b = client.get(f"/api/board/{DAY}").get_json()
    section = next(s for s in b["sections"] if s["name"] == "الأهداف")
    assert section["type"] == "targets"
    assert "commander" in section["rows"][0]


# ---------- الأهداف قايمة مغلقة — التعيين والحذف من المسار المخصّص ----------

def _set_target(client, name, officer_ids, day=DAY):
    return client.put(f"/api/board/{day}/target/{name}", json={"officer_ids": officer_ids})


def test_assigning_an_officer_to_a_fixed_target_creates_the_row(client):
    r = _set_target(client, "سوميد", ["OFF-002"])
    assert r.status_code == 200
    row = _target_row(client, "سوميد")
    assert [o["id"] for o in row["officers"]] == ["OFF-002"]
    assert row["vacant"] is False


def test_clearing_a_target_assignment_removes_the_underlying_row(client):
    _set_target(client, "سوميد", ["OFF-002"])
    r = _set_target(client, "سوميد", [])
    assert r.status_code == 200
    row = _target_row(client, "سوميد")
    assert row["officers"] == [] and row["vacant"] is True
    assert not any(a.get("name") == "سوميد" for a in
                   client.get(f"/api/assignments/{DAY}").get_json()["assignments"])


def test_clearing_the_only_target_assignment_of_the_day_removes_the_day_file(client):
    """set_target_officers بيشيل الصف بإيده على طول (مش عن طريق
    DayRepo)، فلازم يتنضّف عدّاد id التكليفات معاه برضو — وإلا ملف اليوم
    الفاضي بيفضل موجود بس عشان عدّاد يتيم."""
    from backend import store

    _set_target(client, "سوميد", ["OFF-002"])
    _set_target(client, "سوميد", [])
    assert not store.day_path(DAY).exists()


def test_assigning_to_an_unknown_target_name_is_rejected(client):
    assert _set_target(client, "هدف مش موجود في القايمة", ["OFF-002"]).status_code == 400


def test_a_target_assignment_always_has_the_guard_kind_and_no_shift(client):
    _set_target(client, "سوميد", ["OFF-002"])
    row = next(a for a in client.get(f"/api/assignments/{DAY}").get_json()["assignments"]
              if a["name"] == "سوميد")
    assert row["kind"] == "حراسات" and row["shift"] == ""


def test_the_generic_endpoint_also_refuses_a_non_fixed_target_name(client):
    """مسار الأهداف المخصّص مش الوحيد اللي بيحمي القايمة — المسار العام
    (`/api/assignments`) لازم يرفض برضو، وإلا يبقى باب خلفي."""
    r = client.post(f"/api/assignments/{DAY}",
                    json={"name": "هدف اختراع", "kind": "حراسات", "section": "الأهداف"})
    assert r.status_code == 400


def test_the_generic_endpoint_forces_the_guard_kind_for_targets(client):
    """حتى لو حد بعت تصنيف مختلف عن طريق المسار العام، الأهداف بتفضل
    حراسات دايمًا — القايمة المغلقة معناها التصنيف مش اختيار."""
    r = client.post(f"/api/assignments/{DAY}",
                    json={"name": "سوميد", "kind": "خارجية", "section": "الأهداف",
                          "shift": "صباحية"})
    assert r.status_code == 201
    assert r.get_json()["kind"] == "حراسات"
    assert r.get_json()["shift"] == ""
