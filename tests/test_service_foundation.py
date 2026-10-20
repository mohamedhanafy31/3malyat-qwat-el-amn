from backend.clocktime import format_time, parse_shift_pair, parse_time
from backend.service_catalog import catalog
from backend.service_lines import line_for_service, members
from backend.service_links import resolve_service_id, service_for_counts_entry


def test_archive_times_and_round_trips():
    values = {
        "8 ص / 8 م": ("08:00", "20:00"), "8 ص فترة صباحة": ("08:00", None),
        "//": (None, None), "11 ص حتى الانتهاء": ("11:00", None),
        "2:30م": ("14:30", None), "10.30ص": ("10:30", None),
        "12 ليل": ("00:00", None), "12ص": ("12:00", None), "12م": ("00:00", None),
        "7:30": ("07:30", None), "8 م": ("20:00", None), "٧ م": ("19:00", None),
    }
    for text, expected in values.items():
        assert parse_shift_pair(text) == expected
    for value, printed in {"08:00": "8ص", "12:00": "12ظ", "12:30": "12:30ظ",
                           "20:00": "8م", "14:30": "2:30م", "00:00": "12 ليل",
                           "07:30": "7:30ص"}.items():
        assert format_time(value) == printed
        assert parse_time(printed) == value


def test_all_observed_archive_shapes_are_literal_regression_inputs():
    assignments = [
        "", "0ص", "1 ظ", "1.30 ظ", "1.30 م", "1.5 م", "10", "10 ص", "10.30 ص",
        "10:30 ص", "11:30ص", "12 ص", "12 ظ", "12 ليل", "12:30ظ", "1:30 ص",
        "2.3 م", "2.30 م", "2.5 م", "2:30م", "3:30م", "4 : 8م", "5م استاد السويس",
        "7:30 م", "8 ص / 8 م", "8ص الاربعين", "8:04م", "ليل",
    ]
    schedules = [
        "", "//", '10 ص "تعليمات السيد مدير الأمن"', "10 ص حتى الانتهاء", "10ص وحتي الانتهاء",
        "5ص/5م", "7 ص", "8 ص", "8 ص / 8 م", "8 ص / 8م", "8 ص فترة صباحة",
        "8ص / 8 م", "8ص/8م", '8ص"8ص', "8ص/8م 8م/ 8ص", "9 ص / 9 م", "فندث لابرونتو 8م",
    ]
    for value in assignments + schedules:
        result = parse_time(value)
        assert result is None or len(result) == 5


def test_service_links_are_exact_or_explicit_aliases():
    data = {"service_catalog": [
        {"id": "SVC-1", "name": "القول المكبر", "tags": []},
        {"id": "SVC-2", "name": "حملة الأمن الوطني", "tags": []},
        {"id": "SVC-3", "name": "خدمة ثابتة", "tags": []},
    ]}
    assert resolve_service_id(data, "قول مكبر") == "SVC-1"
    assert resolve_service_id(data, "حملة أمن وطني 12ص") == "SVC-2"
    assert resolve_service_id(data, "خدمة مختلفة") is None
    assert service_for_counts_entry(data, {"service_id": "SVC-3", "name": "مختلف"}) == "SVC-3"
    assert service_for_counts_entry(data, {"service_id": "SVC-999", "name": "قول مكبر"}) == "SVC-1"


def test_service_lines_use_tags_then_catalog_order():
    data = {"service_catalog": [
        {"id": "SVC-2", "name": "ب", "tags": ["فيصل"]},
        {"id": "SVC-1", "name": "أ", "tags": ["فيصل"]},
        {"id": "SVC-3", "name": "ج", "tags": ["خارجي"]},
    ], "service_lines": [{"id": "LN-1", "name": "خط فيصل", "tag": "فيصل",
                          "lorry_id": "LOR-3", "order": ["SVC-1", "SVC-999"]}]}
    assert [x["id"] for x in members(data, "LN-1")] == ["SVC-1", "SVC-2"]
    assert line_for_service(data, "SVC-2")["id"] == "LN-1"


def test_catalog_time_fields_default_and_validate():
    from backend.service_catalog import apply_entry, blank_entry
    data = {"service_catalog": [], "service_tags": []}
    entry = blank_entry("SVC-1", "خدمة")
    entry, error = apply_entry(data, entry, {"report_am": "8 م", "report_pm": ""})
    assert error is None and entry["report_am"] == "20:00" and entry["report_pm"] == ""
    entry, error = apply_entry(data, entry, {"report_am": "مش وقت"})
    assert entry is None and error
    assert catalog({"service_catalog": [{"id": "SVC-2", "name": "قديمة"}]})[0]["report_am"] == ""
