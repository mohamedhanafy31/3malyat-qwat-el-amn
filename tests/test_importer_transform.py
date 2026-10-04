from collections import defaultdict

from backend.constants import (
    SECTION_ADMIN_WORK, SECTION_BASIC, SECTION_GREAT, SECTION_OCCASIONAL,
    SECTION_OUTSIDERS, SECTION_RESTS, SECTION_SUBCAMP, SECTION_TARGETS,
)
from importer.transform import (
    DayBuilder, _computed_section, _count_int, _display_section, _party, _pick,
    _shift_from_time, _strip_shift_word,
    core_delta, reference_versions,
)


def test_shift_from_time_matches_reference_days():
    assert _shift_from_time("12ظ") == "صباحية"
    assert _shift_from_time("7ص") == "صباحية"
    assert _shift_from_time("2:30م") == "صباحية"
    assert _shift_from_time("10 م") == "ليلية"
    assert _shift_from_time("12م") == "ليلية"
    assert _shift_from_time("") == ""


def test_section_display_names_and_shift_words():
    assert _display_section("الخدمات الطاريه") == SECTION_OCCASIONAL
    assert _display_section("ضابط عظيم وامن المعسكر الفرعي") == SECTION_SUBCAMP
    assert _display_section("ضابط عظيم الاداره") == SECTION_GREAT
    assert _display_section("الخدمات اساسيه") == SECTION_BASIC
    assert _strip_shift_word("ارتكاز بتروجيت ليل") == "ارتكاز بتروجيت"


def test_computed_word_headings_keep_their_real_sections():
    assert _computed_section("الخوارج") == SECTION_OUTSIDERS
    assert _computed_section("الراحات") == SECTION_RESTS
    assert _computed_section("عمل بالاداره") == SECTION_ADMIN_WORK


def test_count_and_party_reject_phone_numbers():
    assert _count_int("01145944609") == 0
    assert _count_int("7") == 7
    assert _party(["01145944609", "عتاقة"]) == "عتاقة"


def test_pick_prefers_time_then_shift_then_single():
    a = {"time": "10م", "shift": "ليلية"}
    b = {"time": "12ظ", "shift": "صباحية"}
    assert _pick([a, b], "10م") is a
    assert _pick([a, b], "12م") is a
    assert _pick([b], "9ص") is b
    assert _pick([], "9ص") is None


class FakeCtx:
    def __init__(self, officers=None, people=None):
        self.officers = officers or {}
        self.people = people or {}
        self.events = defaultdict(list)
        self.vocabulary = []

    def usable(self, record):
        return True

    def officer_of_row(self, record):
        return self.officers.get(record["i"], "")

    def personnel_match(self, person):
        return ""

    def people_of(self, record):
        return [(person, self.people.get((record["i"], index), "")) for index, person in enumerate(record["people"])]

    def alias(self, phrase):
        return {"key": phrase, "canonical": phrase, "confidence": "high", "category": "service",
                "kind": "خارجية", "section": SECTION_OCCASIONAL, "counts_in_summary": True}

    def service_name(self, alias):
        return alias["canonical"], "خارجية", True

    def service_section(self, name, fallback):
        return fallback

    def target_name(self, label):
        return {"سوميد": "سوميد"}.get(label.replace("عمل بهدف ", "").strip(), "")


def _rec(i, role, type_, **over):
    record = {"i": i, "date": "2025-01-05", "role": role, "type": type_, "path": f"{role}.docx", "sha1": "x",
              "table": 0, "row": i, "half": over.pop("half", 0), "label": "", "manning": "", "fields": {}, "cells": [],
              "aligned": {}, "block": "", "section": "", "known_section": False, "stale": False, "shift": [],
              "time": [], "party": [], "conscripts": {}, "weapon": "", "people": []}
    record.update(over)
    return record


def test_board_day_role_slot_inheritance_targets_from_roster_and_computed_sections():
    officer = {"name": "", "rank": "رائد", "qualifier": "", "code": "", "post": "", "note": "عمل بهدف سوميد",
               "taqseera": False, "status": "", "leaves": [], "services": ["عمل بهدف سوميد"],
               "rest_system": "", "rest_day": ""}
    records = [
        _rec(1, "roster", "roster_row", officer={**officer, "name": "احمد علي حسن"}),
        _rec(2, "roster", "roster_row", officer={**officer, "name": "محمود سيد عمر", "note": "راحة", "services": []}),
        _rec(10, "board", "board_label", half=1, label="ضابط عظيم وأمن المعسكر الفرعي"),
        _rec(11, "board", "board_row", half=1, label="فترة صباحية", manning="رائد/ محمود سيد",
             people=[{"kind": "officer", "name": "محمود سيد", "rank": "رائد", "shift": "", "phones": []}]),
        _rec(12, "board", "board_label", half=1, label="فترة ليلية"),
        _rec(13, "board", "board_label", half=1, label="الأهداف"),
        _rec(14, "board", "board_row", half=1, label="سوميد", manning="رائد/ محمود سيد",
             people=[{"kind": "officer", "name": "محمود سيد", "rank": "رائد", "shift": "", "phones": []}]),
        _rec(15, "board", "board_label", half=1, label="الراحات"),
        _rec(16, "board", "board_row", half=1, label="رائد/ محمود سيد", manning="راحة"),
    ]
    ctx = FakeCtx(officers={1: "OFF-1", 2: "OFF-2"}, )
    ctx.people = {(11, 0): "OFF-2", (14, 0): "OFF-2"}
    day = DayBuilder("2025-01-05", records, ctx).build("B", "B")
    rows = [(row["section"], row["name"], row["shift"], row["officer_ids"]) for row in day["assignments"]]
    # الليلية مدموجة رأسيًا مع الصباحية = نفس الضابط
    assert (SECTION_SUBCAMP, "نوبتجي المعسكر الفرعي", "صباحية", ["OFF-2"]) in rows
    assert (SECTION_SUBCAMP, "نوبتجي المعسكر الفرعي", "ليلية", ["OFF-2"]) in rows
    # يومية الضباط مرجع ضابط الهدف
    assert (SECTION_TARGETS, "سوميد", "", ["OFF-1"]) in rows
    # «الراحات» قسم محسوب مش تكليف
    assert not any(row["section"] == "الراحات" for row in day["assignments"])
    assert day["officer_states"]["OFF-1"]["note"] == "عمل بهدف سوميد"
    assert [row["id"] for row in day["assignments"]] == [f"AS-{i:04d}" for i in range(1, len(rows) + 1)]


def test_core_delta_history_command_and_leave_stitching():
    obs = lambda post, leaves=(): {"rank": "رائد", "qualifier": "", "code": "1/2010", "post": post, "section": "القوة",
                                    "rest_system": "", "rest_day": "", "search_attached": False, "leaves": list(leaves),
                                    "note": "راحة", "services": [], "name": "احمد علي حسن"}
    leave = lambda day: {"type": "شهرية", "start": day, "end": day}
    observations = {
        "2025-01-01": {"officers": {"OFF-1": obs("مدير الإدارة", [leave("2025-01-01")])}, "personnel": {}},
        "2025-01-02": {"officers": {"OFF-1": obs("مدير الإدارة", [leave("2025-01-02")])}, "personnel": {}},
        "2025-01-03": {"officers": {"OFF-1": obs("وكيل الإدارة")}, "personnel": {}},
    }
    delta = core_delta(observations, {"officers": [], "personnel": [], "leaves": []})
    officer = delta["officers"][0]
    assert officer["action"] == "create" and [entry["from"] for entry in officer["history"]] == ["2025-01-01", "2025-01-03"]
    assert [entry["command"]["مدير الإدارة"] for entry in delta["command_history"]] == ["OFF-1", None]
    assert delta["leaves"] == [{"op": "add", "person_id": "OFF-1", "type": "شهرية", "start": "2025-01-01",
                                "end": "2025-01-02", "source": "راحة", "return_date": "2025-01-03", "overlaps": []}]


def test_reference_versions_collapse_identical_days():
    days = {f"2025-01-{d:02d}": {"afraad_basic": {"خط الغاز": {}, "جديدة": {}}, "assignments": []} for d in range(1, 11)}
    versions = reference_versions(days)
    assert len(versions["afraad_basic"]) == 1
    names = [item["name"] for item in versions["afraad_basic"][0]["items"]]
    assert names == ["خط الغاز", "جديدة"]
    assert versions["afraad_ids"]["جديدة"].startswith("AFB-")


def test_reference_versions_follow_each_day_list_so_nothing_is_hidden():
    days = {f"2025-01-{d:02d}": {"afraad_basic": {"خط الغاز": {}}, "assignments": []} for d in range(1, 11)}
    days["2025-01-05"]["afraad_basic"]["خدمة يوم واحد"] = {}
    versions = reference_versions(days)
    assert [(v["from"], [item["name"] for item in v["items"]]) for v in versions["afraad_basic"]] == [
        ("2025-01-01", ["خط الغاز"]), ("2025-01-05", ["خط الغاز", "خدمة يوم واحد"]), ("2025-01-06", ["خط الغاز"])]
    assert versions["afraad_ids"]["خدمة يوم واحد"].startswith("AFB-")


def test_board_shift_only_row_continues_service_and_person_label_is_not_a_section():
    records = [
        _rec(1, "board", "board_label", label="الخدمات الطارئة"),
        _rec(2, "board", "board_row", label="ارتكاز المثلث صبح", manning="فرد", shift=["صباحية"]),
        _rec(3, "board", "board_row", label="ليل", manning="فرد + وحدة", shift=["ليلية"]),
        _rec(4, "board", "board_label", label="مقدم / ضابط تجريبي"),
        _rec(5, "board", "board_row", label="مأمورية إمداد", manning="فرد"),
    ]
    day = DayBuilder("2025-01-05", records, FakeCtx()).build("B", "B")
    rows = [(row["section"], row["name"], row["shift"]) for row in day["assignments"]]
    assert ("الخدمات الطارئة", "ارتكاز المثلث صبح", "صباحية") in rows
    assert ("الخدمات الطارئة", "ارتكاز المثلث ليل", "ليلية") in rows
    assert ("الخدمات الطارئة", "مأمورية إمداد", "صباحية") in rows


def test_history_ignores_unknown_ranks_and_one_day_blips():
    from importer.transform import _history_entries
    obs = lambda rank, post="رئيس مباحث": {"rank": rank, "post": post, "section": "القوة"}
    days = [("2025-08-01", obs("نقيب")), ("2025-08-02", obs("مقدم كريم ناجي رييس قسم")),
            ("2025-08-03", obs("رائد")), ("2025-08-04", obs("نقيب")), ("2025-08-05", obs("رائد")),
            ("2025-08-06", obs("رائد"))]
    blips = []
    entries = _history_entries(days, blips)
    assert [(entry["from"], entry["role"]) for entry in entries] == [("2025-08-01", "نقيب"), ("2025-08-05", "رائد")]
    assert [blip["date"] for blip in blips] == ["2025-08-03"]


def test_conscripts_drop_the_individual_and_read_unit_size():
    builder = DayBuilder("2026-09-02", [], FakeCtx())
    row = builder._new_row("الباب الرئيسي للاستاد", "مباراة")
    record = {"conscripts": {"raw": "فرد + وحدة (7 مجند)", "value": [
        {"class": "فرد", "count": 1}, {"class": "وحدة", "count": 1}, {"class": "مج", "count": 7}]}}
    builder._conscripts_into(row, record)
    assert row["conscripts"] == [{"class": "وحدة", "count": 1}] and row["conscript_count"] == 7
    other = builder._new_row("ترحيلة", "الخدمات الطارئة")
    builder._conscripts_into(other, {"conscripts": {"raw": "فرد + مج", "value": [
        {"class": "فرد", "count": 1}, {"class": "مج", "count": 1}]}})
    assert other["conscripts"] == [{"class": "مج", "count": 1}] and other["conscript_count"] == 1


def test_time_keeps_document_spelling():
    from importer.transform import _time_text
    assert _time_text({"label": "حملة امن وطنى 10 م", "cells": [], "time": ["10م"]}) == "10 م"
    assert _time_text({"label": "ترحيلة", "cells": ["", "2:30م"], "time": ["2:30م"]}) == "2:30م"


def test_personnel_prefix_match_requires_a_unique_compatible_person():
    from importer.transform import Context
    ctx = Context.__new__(Context)
    ctx.core = {"personnel": [{"id": "IND-1", "name": "السيد احمد محمد حسن", "role": "معاون شرطة ثالث"},
                              {"id": "IND-2", "name": "محمد علي حسن", "role": "أمين شرطة ثان"},
                              {"id": "IND-3", "name": "محمد علي سيد", "role": "أمين شرطة أول"}]}
    assert ctx.personnel_match({"name": "السيد احمد", "rank": "م.ش"}) == "IND-1"
    assert ctx.personnel_match({"name": "السيد احمد", "rank": "ا.ش"}) == ""
    assert ctx.personnel_match({"name": "محمد علي", "rank": "ا.ش"}) == ""


def test_conscripts_merge_same_class_and_typed_unit():
    builder = DayBuilder("2026-09-02", [], FakeCtx())
    row = builder._new_row("مأمورية", "الخدمات الطارئة")
    builder._conscripts_into(row, {"conscripts": {"raw": "مقدم/ ضابط + مج فرد + مج", "value": [
        {"class": "مج", "count": 1}, {"class": "فرد", "count": 1}, {"class": "مج", "count": 1}]}})
    assert row["conscripts"] == [{"class": "مج", "count": 2}] and row["conscript_count"] == 2
    unit = builder._new_row("تأمين المقصورة", "مباراة")
    builder._conscripts_into(unit, {"conscripts": {"raw": "وحدة (10مجند رياضي)", "value": [
        {"class": "وحدة", "count": 1}, {"class": "مج", "count": 10}, {"class": "رياضي", "count": 1}]}})
    assert unit["conscripts"] == [{"class": "رياضي", "count": 1}] and unit["conscript_count"] == 10


def test_event_heading_time_and_place_reach_its_rows():
    records = [
        _rec(1, "board", "board_label", label="مباراة قرية عامر باستاد الجيش 2:30م", time=["2:30م"],
             party=["استاد الجيش 2:30م"]),
        _rec(2, "board", "board_row", label="تأمين ارض الملعب", manning="وحدة"),
    ]
    ctx = FakeCtx()
    ctx.events["2025-01-05"] = ["مباراة قرية عامر"]
    day = DayBuilder("2025-01-05", records, ctx).build("B", "B")
    row = day["assignments"][0]
    assert (row["section"], row["time"], row["party"]) == ("مباراة قرية عامر", "2:30م", "استاد الجيش")


def test_already_linked_leader_is_not_copied_to_the_note():
    builder = DayBuilder("2026-09-02", [], FakeCtx())
    builder.roster_names = [("OFF-42", ["ماركو", "ماجد", "حنا"])]
    row = builder._new_row("تأمين المقصورة", "مباراة", officer_ids=["OFF-42"])
    builder._people_into(row, _rec(9, "afraad", "afraad_emergency_row"), "م.اول/ ماركو ماجد")
    assert row["officer_ids"] == ["OFF-42"] and row["note"] == ""


def test_duplicate_merge_repeats_until_stable():
    builder = DayBuilder("2025-11-22", [], FakeCtx())
    builder._new_row("ترحيلة بدر", "مباراة", shift="صباحية", personnel_ids=["IND-125"])
    builder._new_row("ترحيلة بدر", "مباراة", shift="صباحية", personnel_ids=["IND-060"])
    builder._new_row("ترحيلة بدر", "الخدمات الطارئة", shift="صباحية", personnel_ids=["IND-125", "IND-060"])
    builder.merge_duplicates()
    assert [row["personnel_ids"] for row in builder.rows] == [["IND-125", "IND-060"]]


def test_times_are_not_read_as_shift_words():
    from importer.transform import _shifts_in
    assert _shifts_in("منوب الادارة فترة ليلية من 9 م حتى 9 ص") == ["ليلية"]
    assert _shifts_in("ارتكاز محكمة صباحية + ليلية") == ["صباحية", "ليلية"]


def test_deployment_plan_cells_fill_leader_strength_and_weapon():
    builder = DayBuilder("2023-10-31", [], FakeCtx())
    from importer.transform import _tokens
    builder.roster_names = [("OFF-9", _tokens("عبد الرحمن احمد نور الدين"))]
    row = builder._new_row("ارتكاز ابو العزايم", "خطة الانتشار")
    record = _rec(5, "deployment", "deployment_row")
    builder._document_cells_into(row, record, ["نقيب/ عبدالرحمن نورالدين", "01011797802", "13 مجند", "وحدة فض", "8 ص"])
    assert row["officer_ids"] == ["OFF-9"] and row["conscript_count"] == 13
    assert row["conscripts"] == [{"class": "وحدة فض", "count": 1}] and row["weapon"] == "وحدة فض" and row["note"] == ""


def test_merge_keeps_the_richer_row_details_and_the_event_section():
    builder = DayBuilder("2023-10-31", [], FakeCtx())
    builder._new_row("ارتكاز المثلث", "الخدمات الطارئة", shift="صباحية", officer_ids=["OFF-9"])
    builder._new_row("ارتكاز المثلث", "خطة الانتشار", shift="صباحية", officer_ids=["OFF-9"], time="8 ص",
                     weapon="مج فض", conscripts=[{"class": "مج", "count": 3}], conscript_count=3)
    builder.merge_duplicates()
    [row] = builder.rows
    assert (row["section"], row["time"], row["weapon"], row["conscript_count"]) == ("خطة الانتشار", "8 ص", "مج فض", 3)
    assert row["note"] == ""


def test_deployment_leader_with_full_grade_is_not_taken_as_weapon():
    builder = DayBuilder("2023-10-31", [], FakeCtx())
    row = builder._new_row("ارتكاز الحرفيين", "خطة الانتشار")
    builder._document_cells_into(row, _rec(6, "deployment", "deployment_row"),
                                 ["مندوب/ جمال الكويس", "01155539914", "3 مجند", "مايك فض (د + خ + ف+ ك)", "8 ص"])
    assert row["weapon"] == "مايك فض (د + خ + ف+ ك)" and row["note"] == "مندوب/ جمال الكويس"


def _roster(i, oid, note):
    return _rec(i, "roster", "roster_row", officer={"name": f"ضابط {oid}", "rank": "رائد", "qualifier": "", "code": "",
                "post": "", "note": note, "taqseera": False, "status": "", "leaves": [], "services": [note],
                "rest_system": "", "rest_day": ""})


def test_manob_al_idara_follows_the_user_rule():
    from backend.constants import SECTION_GREAT, SECTION_SECURITY
    ctx = FakeCtx(officers={1: "OFF-1", 2: "OFF-2", 3: "OFF-3"})
    both = [_roster(1, "OFF-1", "ضابط عظيم الإدارة فترة صباحية"), _roster(2, "OFF-2", "ضابط امن الادارة فترة صباحية"),
            _roster(3, "OFF-3", "منوب الادارة فترة ليلية")]
    day = DayBuilder("2023-10-05", both, ctx).build("B", "B")
    assert [r["section"] for r in day["assignments"] if r["officer_ids"] == ["OFF-3"]] == [SECTION_SECURITY]
    alone = [_roster(1, "OFF-1", "ضابط عظيم الإدارة فترة صباحية"), _roster(3, "OFF-3", "منوب الادارة فترة ليلية")]
    day = DayBuilder("2023-10-05", alone, ctx).build("B", "B")
    assert [r["section"] for r in day["assignments"] if r["officer_ids"] == ["OFF-3"]] == [SECTION_GREAT]


def test_unknown_name_under_targets_moves_to_emergency():
    records = [_rec(1, "board", "board_label", half=1, label="الأهداف"),
               _rec(2, "board", "board_row", half=1, label="ترحيلة الجيزة", manning="فرد")]
    day = DayBuilder("2025-01-05", records, FakeCtx()).build("B", "B")
    assert [(r["section"], r["name"]) for r in day["assignments"]] == [("الخدمات الطارئة", "ترحيلة الجيزة")]


def test_assigned_day_cuts_the_leave():
    from importer.transform import core_delta
    obs = lambda leaves: {"rank": "رائد", "post": "", "section": "القوة", "leaves": leaves, "note": "", "name": "ضابط"}
    leave = {"type": "نصف شهرية", "start": "2026-09-26", "end": "2026-09-28"}
    observations = {"2026-09-26": {"officers": {"OFF-1": obs([leave])}, "personnel": {}},
                    "2026-09-27": {"officers": {}, "personnel": {}, "assigned": ["OFF-1"]},
                    "2026-09-28": {"officers": {}, "personnel": {}}}
    leaves = [(op["start"], op["end"]) for op in core_delta(observations, {"leaves": []})["leaves"]]
    assert leaves == [("2026-09-26", "2026-09-26"), ("2026-09-28", "2026-09-28")]
