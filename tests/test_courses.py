"""فرق الضباط — الفرقة نفسها والتحاق الضباط بيها.

الفرقة كانت مجرد كلمة في نص التشغيل: بتوصل لخانة «فرقة» في الخوارج لو حد
كتبها في اليوم ده بالظبط، والاسم والمكان والمدة بيضيعوا. دلوقتي الالتحاق
سجل بمدى تواريخ زي الراحة، فبيغطي أيامه لوحده.
"""
DAY = "2026-04-10"


def _course(client, **over):
    body = {"name": "فرقة الحراسات المشددة", "place": "مدرسة الدفاع الشعبي",
            "kind": "تخصصية"}
    body.update(over)
    return client.post("/api/courses", json=body)


def _term(client, **over):
    body = {"officer_id": "OFF-002", "start": "2026-04-05", "end": "2026-04-15"}
    body.update(over)
    return client.post("/api/course-terms", json=body)


def _row(client, officer_id, day):
    d = client.get(f"/api/duty/{day}").get_json()
    return next(r for r in d["rows"] if r["id"] == officer_id)


def test_course_carries_name_place_and_kind(client):
    course = _course(client).get_json()
    assert course["name"] == "فرقة الحراسات المشددة"
    assert course["place"] == "مدرسة الدفاع الشعبي"
    assert course["kind"] == "تخصصية"


def test_a_term_puts_the_officer_in_the_khawarej_cell_all_through_it(client):
    """الفايدة الأساسية: الحالة بتغطي كل أيام المدة من غير ما تتكتب يوم بيوم."""
    course = _course(client).get_json()
    _term(client, course_id=course["id"])

    for day in ("2026-04-05", "2026-04-10", "2026-04-15"):
        row = _row(client, "OFF-002", day)
        assert (row["group"], row["bucket"]) == ("خوارج", "فرقة"), day
        assert row["course"]["name"] == "فرقة الحراسات المشددة"
    # وبره المدة عادي
    assert _row(client, "OFF-002", "2026-04-16")["group"] == "صافي"


def test_the_summary_counts_it_in_the_faraqa_column(client):
    course = _course(client).get_json()
    _term(client, course_id=course["id"])
    s = client.get(f"/api/duty/{DAY}").get_json()["summary"]
    assert s["خوارج"]["فرقة"] == 1
    assert s["balanced"] is True


def test_a_recorded_assignment_beats_the_inferred_span(client):
    """المدة بتيجي من نص مكتوب مرة واحدة («من 22/8 حتى 3/9»)، وساعات
    الضابط بيرجع بدري أو الفرقة بتتأجل — والدليل إنه ظاهر على خدمة في
    اليوم ده. المكتوب لليوم بعينه أقوى من المدى المستنتج.

    ده مش افتراض: في الأرشيف ضابط مكتوب له فرقة من 22/8 حتى 3/9 وهو
    شغّال بهدف أنابيب البترول يوم 31/8.
    """
    course = _course(client).get_json()
    _term(client, course_id=course["id"])
    client.post(f"/api/assignments/{DAY}",
                json={"service_id": "SVC-001", "shift": "صباحية",
                      "officer_ids": ["OFF-002"]})

    row = _row(client, "OFF-002", DAY)
    assert row["group"] == "خارجية", "التكليف المسجّل بيغلب"
    # وباقي أيام المدة اللي مفيهاش تكليف بتفضل فرقة
    assert _row(client, "OFF-002", "2026-04-11")["bucket"] == "فرقة"


def test_written_status_still_wins(client):
    course = _course(client).get_json()
    _term(client, course_id=course["id"])
    client.put(f"/api/duty/{DAY}/OFF-002", json={"status": "مرضي"})
    assert _row(client, "OFF-002", DAY)["bucket"] == "مرضي"


def test_overlapping_terms_for_the_same_officer_are_refused(client):
    course = _course(client).get_json()
    _term(client, course_id=course["id"])
    r = _term(client, course_id=course["id"], start="2026-04-12", end="2026-04-20")
    assert r.status_code == 409
    assert "ملتحق بفرقة تانية" in r.get_json()["error"]


def test_two_officers_can_share_the_same_course(client):
    course = _course(client).get_json()
    assert _term(client, course_id=course["id"]).status_code == 201
    assert _term(client, course_id=course["id"], officer_id="OFF-001").status_code == 201
    out = client.get("/api/courses").get_json()["courses"][0]
    assert out["officers"] == 2


def test_bad_dates_and_unknown_refs_are_refused(client):
    course = _course(client).get_json()
    assert _term(client, course_id="CRS-999").status_code == 400
    assert _term(client, course_id=course["id"], officer_id="OFF-999").status_code == 400
    assert _term(client, course_id=course["id"],
                 start="2026-04-20", end="2026-04-10").status_code == 400


def test_term_with_empty_dates_is_allowed(client):
    """الالتحاق بفرقة ينفع بدون تحديد تواريخ بداية ونهاية."""
    course = _course(client).get_json()
    r = _term(client, course_id=course["id"], start="", end="")
    assert r.status_code == 201
    data = r.get_json()
    assert data["start"] == "" and data["end"] == ""



def test_duplicate_course_name_is_refused(client):
    _course(client)
    assert _course(client).status_code == 409


def test_course_with_terms_cannot_be_deleted(client):
    course = _course(client).get_json()
    _term(client, course_id=course["id"])
    r = client.delete(f"/api/courses/{course['id']}")
    assert r.status_code == 409
    assert "التحاق مسجّل" in r.get_json()["error"]


def test_deleting_the_term_frees_the_officer_and_the_course(client):
    course = _course(client).get_json()
    term = _term(client, course_id=course["id"]).get_json()
    client.delete(f"/api/course-terms/{term['id']}")
    assert _row(client, "OFF-002", DAY)["group"] == "صافي"
    assert client.delete(f"/api/courses/{course['id']}").status_code == 200


def test_course_shows_as_faraqa_symbol_in_the_register(client):
    course = _course(client).get_json()
    _term(client, course_id=course["id"])
    reg = client.get("/api/register/2026/4").get_json()
    row = next(r for r in reg["rows"] if r["id"] == "OFF-002")
    cell = next(c for c in row["cells"] if c["day"] == DAY)
    assert cell["code"] == "ف"


# ---------- العرضين: حسب الفرقة وحسب الضابط ----------

def test_api_returns_both_groupings(client):
    course = _course(client).get_json()
    _term(client, course_id=course["id"])
    out = client.get("/api/courses").get_json()
    assert set(out) == {"courses", "officers"}


def test_officer_view_lists_every_officer_even_without_courses(client):
    """«مين لسه ماخدش فرقة» سؤال تشغيلي زي «مين خد إيه»."""
    course = _course(client).get_json()
    _term(client, course_id=course["id"])
    rows = client.get("/api/courses").get_json()["officers"]
    assert {r["id"] for r in rows} == {"OFF-001", "OFF-002"}
    taken = next(r for r in rows if r["id"] == "OFF-002")
    none_yet = next(r for r in rows if r["id"] == "OFF-001")
    assert taken["count"] == 1 and taken["days"] == 11
    assert none_yet["count"] == 0 and none_yet["courses"] == []


def test_officer_view_carries_the_full_detail_of_each_course(client):
    course = _course(client).get_json()
    _term(client, course_id=course["id"], note="بترشيح من الإدارة")
    row = next(r for r in client.get("/api/courses").get_json()["officers"]
               if r["id"] == "OFF-002")
    detail = row["courses"][0]
    assert detail["course_name"] == "فرقة الحراسات المشددة"
    assert detail["course_place"] == "مدرسة الدفاع الشعبي"
    assert detail["course_kind"] == "تخصصية"
    assert (detail["start"], detail["end"], detail["days"]) == (
        "2026-04-05", "2026-04-15", 11)
    assert detail["note"] == "بترشيح من الإدارة"


def test_detail_shows_the_rank_he_held_when_he_took_it(client):
    """الرتبة وقت الفرقة مش رتبته النهاردة — الضابط بيترقّى."""
    client.patch("/api/person/OFF-002", json={"role": "نقيب",
                                              "effective_from": "2026-01-01"})
    client.patch("/api/person/OFF-002", json={"role": "رائد",
                                              "effective_from": "2026-08-01"})
    course = _course(client).get_json()
    _term(client, course_id=course["id"])          # أبريل — قبل الترقية

    row = next(r for r in client.get("/api/courses").get_json()["officers"]
               if r["id"] == "OFF-002")
    assert row["role"] == "رائد", "رتبته الحالية في صف الضابط"
    assert row["courses"][0]["officer_role"] == "نقيب", "ورتبته وقتها في التفاصيل"


def test_both_views_agree_on_the_same_terms(client):
    course = _course(client).get_json()
    _term(client, course_id=course["id"])
    _term(client, course_id=course["id"], officer_id="OFF-001")
    out = client.get("/api/courses").get_json()

    by_course = {t["id"] for c in out["courses"] for t in c["terms"]}
    by_officer = {t["id"] for o in out["officers"] for t in o["courses"]}
    assert by_course == by_officer
