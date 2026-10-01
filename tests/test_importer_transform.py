from collections import defaultdict

from backend.constants import SECTION_BASIC, SECTION_GREAT, SECTION_OCCASIONAL, SECTION_SUBCAMP, SECTION_TARGETS
from importer.transform import (
    DayBuilder, _count_int, _display_section, _party, _pick, _shift_from_time, _strip_shift_word,
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


def test_reference_versions_are_monthly_and_stable():
    days = {f"2025-01-{d:02d}": {"afraad_basic": {"خط الغاز": {}, "جديدة": {}}, "assignments": []} for d in range(1, 11)}
    versions = reference_versions(days)
    assert len(versions["afraad_basic"]) == 1
    names = [item["name"] for item in versions["afraad_basic"][0]["items"]]
    assert names == ["خط الغاز", "جديدة"]
    assert versions["afraad_ids"]["جديدة"].startswith("AFB-")


def test_reference_versions_keep_ids_for_rare_basic_services():
    days = {f"2025-01-{d:02d}": {"afraad_basic": {"خط الغاز": {}}, "assignments": []} for d in range(1, 11)}
    days["2025-01-05"]["afraad_basic"]["خدمة يوم واحد"] = {}
    versions = reference_versions(days)
    assert [item["name"] for item in versions["afraad_basic"][0]["items"]] == ["خط الغاز"]
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
