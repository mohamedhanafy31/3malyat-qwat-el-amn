"""اقتراحات أقسام اللوحة وإعادة استخدام تعريفات خدمات يوم سابق."""

TARGET_DAY = "2026-04-10"
SECTION = "خطة انتشار"


def _add(client, day, name, section=SECTION, **overrides):
    payload = {
        "name": name,
        "kind": "خارجية",
        "section": section,
        "shift": "صباحية",
    }
    payload.update(overrides)
    response = client.post(f"/api/assignments/{day}", json=payload)
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def _history(client, day=TARGET_DAY, section=SECTION):
    return client.get(f"/api/board/{day}/section-history",
                      query_string={"section": section})


def _copy(client, *, day=TARGET_DAY, section=SECTION, source_day="2026-04-09", ids=None):
    return client.post(f"/api/board/{day}/section-copy", json={
        "section": section,
        "source_day": source_day,
        "ids": ids or [],
    })


def test_section_suggestions_span_all_days_and_sort_custom_names_by_latest_use(client):
    _add(client, "2026-04-01", "خدمة أ", section="قسم قديم")
    _add(client, "2026-04-02", "خدمة ب", section="قسم أحدث")
    _add(client, "2026-04-03", "خدمة ج", section="قسم قديم")
    _add(client, "2026-04-04", "سوميد", section="الأهداف", kind="حراسات", shift="")
    _add(client, "2026-04-05", "دور ثابت", section="ضابط عظيم الإدارة")

    names = client.get(f"/api/board/{TARGET_DAY}").get_json()["section_names"]

    assert names[:2] == ["الخدمات أساسية", "الخدمات الطارئة"]
    assert names[2:] == ["قسم قديم", "قسم أحدث"]
    assert "الأهداف" not in names
    assert "ضابط عظيم الإدارة" not in names


def test_history_returns_latest_earlier_day_and_copyable_fields_without_people(client):
    _add(client, "2026-04-08", "نسخة أقدم")
    source = _add(client, "2026-04-09", "كمين رئيسي",
                  officer_ids=["OFF-001"],
                  weapon="آلي", time="٨ ص", party="عتاقة",
                  conscripts=[{"class": "قتالية", "count": 3}], conscript_count=4,
                  note="تعليمات المصدر", counts_in_summary=False)
    _add(client, "2026-04-12", "نسخة مستقبلية")

    response = _history(client)
    assert response.status_code == 200
    body = response.get_json()
    assert body["section"] == SECTION
    assert body["source_day"] == "2026-04-09"
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["id"] == source["id"]
    assert row["weapon"] == "آلي"
    assert row["conscripts"] == [{"class": "قتالية", "count": 3}]
    assert row["counts_in_summary"] is False
    assert "officer_ids" not in row
    assert "personnel_ids" not in row


def test_history_falls_back_to_most_recent_other_day_when_none_is_earlier(client):
    _add(client, "2026-04-12", "خدمة مستقبلية قديمة")
    _add(client, "2026-04-15", "خدمة مستقبلية أحدث")

    body = _history(client).get_json()

    assert body["source_day"] == "2026-04-15"
    assert [row["name"] for row in body["rows"]] == ["خدمة مستقبلية أحدث"]


def test_history_is_empty_for_sections_with_dedicated_ui(client):
    _add(client, "2026-04-09", "سوميد", section="الأهداف", kind="حراسات", shift="")

    body = _history(client, section="الأهداف").get_json()

    assert body == {"section": "الأهداف", "source_day": None, "rows": []}


def test_copy_creates_fresh_rows_without_people_and_skips_normalized_duplicates(client):
    duplicate_source = _add(client, "2026-04-09", "نقطة تفتيش",
                            officer_ids=["OFF-001"], weapon="آلي")
    copied_source = _add(client, "2026-04-09", "تأمين البوابة", shift="ليلية",
                         officer_ids=["OFF-002"],
                         weapon="خرطوش", time="٨ م", party="الجناين",
                         conscripts=[{"class": "حفظ نظام", "count": 2}],
                         conscript_count=5, note="بدون تأخير",
                         counts_in_summary=False)
    _add(client, TARGET_DAY, "نقطه تفتيش", weapon="دونك")

    response = _copy(client, ids=[duplicate_source["id"], copied_source["id"]])

    assert response.status_code == 201, response.get_json()
    assert response.get_json()["added"] == 1
    assert response.get_json()["skipped"] == 1
    assignments = client.get(f"/api/assignments/{TARGET_DAY}").get_json()["assignments"]
    copied = next(row for row in assignments if row["name"] == "تأمين البوابة")
    assert copied["id"] != next(row["id"] for row in assignments if row["name"] == "نقطه تفتيش")
    assert copied["section"] == SECTION
    assert copied["officer_ids"] == []
    assert copied["personnel_ids"] == []
    for field in ("kind", "shift", "weapon", "time", "party",
                  "conscripts", "conscript_count", "note", "counts_in_summary"):
        assert copied[field] == copied_source[field]


def test_copy_refuses_a_closed_target_day(client):
    source = _add(client, "2026-04-09", "خدمة مصدر")
    assert client.post(f"/api/day-status/{TARGET_DAY}/close", json={}).status_code == 201

    response = _copy(client, ids=[source["id"]])

    assert response.status_code == 409
    assert client.get(f"/api/assignments/{TARGET_DAY}").get_json()["assignments"] == []


def test_copy_validates_source_day_and_selected_ids_atomically(client):
    source = _add(client, "2026-04-09", "خدمة مصدر")

    assert _copy(client, source_day="يوم غلط", ids=[source["id"]]).status_code == 400
    assert _copy(client, source_day="2026-04-08", ids=[source["id"]]).status_code == 404
    response = _copy(client, ids=[source["id"], "AS-9999"])
    assert response.status_code == 404
    assert client.get(f"/api/assignments/{TARGET_DAY}").get_json()["assignments"] == []
