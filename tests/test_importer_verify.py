from importer.apply import _apply_references, apply_core, assign_ids, unlink_off_force
from importer.golden import compare_day
from importer.verify import leave_counter_breaks, score, system_summary, word_summary


def _cells(rows):
    out = []
    for row_index, row in enumerate(rows):
        for column, text in enumerate(row):
            out.append({"table_index": 1, "row_index": row_index, "column_indexes": [column], "raw_text": text})
    return out


def test_old_summary_maps_only_clear_columns():
    word = word_summary(_cells([
        ["الجهة", "أصل القوة", "تقصيره", "راحة أسبوعية", "راحة شهرية", "فرقة", "إجمالي خوارج"],
        ["إدارة", "40", "1", "3", "1", "1", "5"],
    ]))
    assert word["era"] == "old"
    assert word["values"] == {("أصل القوة", ""): 40, ("خوارج", "تقصيرة"): 1, ("خوارج", "راحة"): 4}
    assert set(word["not_comparable"]) == {"فرقة", "إجمالي خوارج"}


def test_new_summary_reads_spanned_headers_and_search_suffix():
    cells = _cells([
        ["أصل القوة", "الخدمات الخارجية", "الخدمات الخارجية", "الخوراج", "الصافي (3)"],
        ["", "فترة صباحية", "فترة ليلية", "تقصيرة", ""],
        ["34", "5 + 1 بحث", "1", "3", ""],
    ])
    word = word_summary(cells)
    assert word["era"] == "new"
    assert word["values"][("خارجية", "صباحية")] == 5 and word["values"][("خارجية", "بحث")] == 1
    assert word["values"][("خارجية", "ليلية")] == 1 and word["values"][("صافي", "")] == 3
    summary = {"أصل القوة": 34, "خارجية": {"صباحية": 5, "ليلية": 1, "بحث": 1}, "صافي": 3}
    assert system_summary(summary, ("خارجية", "بحث")) == 1 and system_summary(summary, ("صافي", "")) == 3


def test_score_drops_missing_components_and_reweights():
    assert score({"presence": 1, "validity": 1, "identity": None, "consistency": None, "summary": None}) == 100
    assert score({"presence": 1, "validity": 0.5, "identity": None, "consistency": None, "summary": 0}) == 54


def test_leave_counter_breaks_only_on_consecutive_days():
    days = {"2025-01-01": {"officer_states": {"OFF-1": {"note": "راحة شهرية (1/7)"}}},
            "2025-01-02": {"officer_states": {"OFF-1": {"note": "راحة شهرية (2/7)"}}},
            "2025-01-03": {"officer_states": {"OFF-1": {"note": "راحة شهرية (5/7)"}}}}
    assert list(leave_counter_breaks(days)) == ["2025-01-03"]


def test_assign_ids_is_stable_through_the_id_map():
    delta = {"officers": [{"id": "NEW-OFF-001", "code": "12/2020", "name": "ضابط", "first_seen": "2024-01-01"}],
             "personnel": [{"id": "NEW-IND-001", "name": "فرد تجريبي", "first_seen": "2024-01-01"}]}
    data = {"officers": [{"id": "OFF-007"}], "personnel": [{"id": "IND-200"}]}
    id_map = {}
    first = assign_ids(data, delta, id_map)
    assert first == {"NEW-OFF-001": "OFF-008", "NEW-IND-001": "IND-201"}
    again = assign_ids({"officers": [{"id": "OFF-007"}, {"id": "OFF-008"}], "personnel": []}, delta, id_map)
    assert again == first


def test_apply_core_never_rewrites_existing_people_and_reviews_bad_leaves():
    data = {"officers": [{"id": "OFF-1", "name": "قائم", "role": "عقيد", "code": "1/2000", "join_date": "2026-06-01",
                          "post": "مدير", "section": "القوة", "rest_system": "—", "rest_day": ""}],
            "personnel": [], "leaves": [{"id": "LV-001", "person_id": "OFF-1", "type": "أسبوعية",
                                         "start": "2025-01-02", "end": "2025-01-02"}]}
    delta = {"officers": [{"id": "OFF-1", "first_seen": "2025-01-01", "last_seen": "2026-09-01", "code": "1/2000",
                           "name": "قائم", "history": [{"from": "2025-01-01", "role": "مقدم", "post": "وكيل",
                                                       "section": "القوة"}]}],
             "leaves": [{"op": "add", "person_id": "OFF-1", "type": "شهرية", "start": "2025-01-01", "end": "2025-01-07",
                         "return_date": "2025-01-08", "source": "راحة شهرية (1/7)"}]}
    result = apply_core(data, delta, {}, system_start="2026-06-01")
    officer = data["officers"][0]
    assert officer["role"] == "عقيد" and officer["join_date"] == "2025-01-01"
    assert [(h["from"], h["role"]) for h in officer["history"]] == [("2025-01-01", "مقدم"), ("2026-06-01", "عقيد")]
    assert len(data["leaves"]) == 1
    assert [item["type"] for item in result["review"]] == ["leave_not_added"]


def test_reference_lists_keep_kept_days_and_current_list_last():
    data = {"reference_lists": {"targets": [{"from": "2026-06-01", "names": ["مشرف الأهداف", "سوميد"]}]}}
    lists = {"targets": [{"from": "2026-08-30", "names": ["مشرف الأهداف", "سوميد", "جديد"]}]}
    _apply_references(data, lists, "2026-06-01", imported={"2026-08-30", "2026-08-31", "2026-09-03"},
                      kept={"2026-09-01", "2026-09-02", "2026-10-01"})
    versions = data["reference_lists"]["targets"]
    assert [(v["from"], len(v["names"])) for v in versions] == [
        ("2026-06-01", 2), ("2026-08-30", 3), ("2026-09-01", 2), ("2026-09-03", 3), ("2026-10-01", 2)]


def test_unlink_off_force_keeps_the_name_in_the_note():
    day = {"assignments": [{"id": "AS-0001", "name": "ترحيلة", "officer_ids": ["OFF-9"], "personnel_ids": [],
                            "note": ""}],
           "afraad_basic": {"AFB-01": {"morning_person_id": "IND-9", "morning_name": "م.ش/ فرد"}}}
    review = unlink_off_force(day, "2024-01-01", {"officers": set(), "personnel": set()}, {"OFF-9": "رائد/ ضابط"})
    assert day["assignments"][0]["officer_ids"] == [] and day["assignments"][0]["note"] == "رائد/ ضابط"
    assert "morning_person_id" not in day["afraad_basic"]["AFB-01"] and len(review) == 2


def test_golden_compare_reports_presence_fields_and_order():
    reference = {"assignments": [{"section": "أ", "name": "خدمة", "shift": "صباحية", "kind": "خارجية", "time": "8ص"},
                                 {"section": "ب", "name": "حدث", "shift": "صباحية", "kind": "خارجية"}],
                 "officer_states": {"OFF-1": {"note": "عمل"}}}
    candidate = {"assignments": [{"section": "أ", "name": "خدمة", "shift": "صباحية", "kind": "خارجية", "time": "8 ص"}],
                 "officer_states": {"OFF-1": {"note": "عمل "}}}
    result = compare_day(reference, candidate)
    assert result["missing"] == ["ب · حدث · صباحية"] and result["match"]["states"] == 100.0
    assert [diff["field"] for diff in result["field_diffs"]] == ["time"]


def test_same_named_new_people_get_different_ids():
    delta = {"officers": [], "personnel": [
        {"id": "NEW-IND-095", "name": "محمد مصطفي", "first_seen": "2023-12-10", "phones": ["01208882744"]},
        {"id": "NEW-IND-096", "name": "محمد مصطفي", "first_seen": "2023-12-13", "phones": ["01000307287"]}]}
    assigned = assign_ids({"officers": [], "personnel": []}, delta, {})
    assert assigned["NEW-IND-095"] != assigned["NEW-IND-096"]


def test_leave_is_cut_on_imported_duty_days():
    from importer.apply import cut_leaves_on_duty
    data = {"leaves": [{"id": "LV-001", "person_id": "OFF-1", "type": "شهرية", "start": "2026-09-16", "end": "2026-09-22"}]}
    days = {"2026-09-16": {"assignments": [{"officer_ids": ["OFF-1"]}]},
            "2026-09-19": {"assignments": [{"officer_ids": ["OFF-1"]}]}}
    review = cut_leaves_on_duty(data, days)
    assert sorted((lv["start"], lv["end"]) for lv in data["leaves"]) == [("2026-09-17", "2026-09-18"), ("2026-09-20", "2026-09-22")]
    assert review[0]["service_days"] == ["2026-09-16", "2026-09-19"]
    assert cut_leaves_on_duty(data, days) == []
