from datetime import datetime
from copy import deepcopy

import pytest

from backend import store
from backend import ops_board
from backend.ops_board import (_BuildContext, _build_ops, build_ops, depart,
                               return_, set_time, undo)
from backend.service_links import resolve_service_id
from backend import campaign


def _data():
    return {
        "service_catalog": [{"id": "SVC-1", "name": "خدمة أ", "period": "صباحية وليلية",
                              "report_am": "08:00", "report_pm": "20:00", "count": 7,
                              "weapon": "آلي", "tags": []}],
        "service_lines": [], "day_assignments": {},
        "service_counts": {"2026-10-20": {"entries": [{"id": "CNT-1", "name": "خدمة أ",
                                                           "block": "صباحية", "count": 2, "weapon": ""}]}},
        "day_afraad": {}, "day_campaign": {}, "day_service_runs": {}, "day_status": {},
        "reference_lists": {}, "personnel": [], "officers": [],
    }


def test_shared_run_is_one_state_and_exclusions_are_not_sources():
    data = _data()
    data["day_assignments"]["2026-10-20"] = [
        {"id": "AS-1", "section": "الخدمات أساسية", "name": "خدمة أ",
         "shift": "صباحية", "officer_ids": []},
        {"id": "AS-2", "section": "الأهداف", "name": "هدف", "shift": "صباحية", "officer_ids": []},
    ]
    view = build_ops(data, "2026-10-20", datetime(2026, 10, 20, 7, 0))
    assert view["groups"]["officers"][0]["key"] == "SVC-1:am"
    assert view["groups"]["basic"]["am"]["single"][0]["key"] == "SVC-1:am"
    assert all(r["name"] != "هدف" for r in view["groups"]["officers"])
    shared = next(run for run in view["runs"] if run["key"] == "SVC-1:am")
    assert shared["types"] == ["officers", "basic"]
    assert sum(run["key"] == "SVC-1:am" for run in view["runs"]) == 1


def test_transitions_and_undo():
    data = _data()
    key = "SVC-1:am"
    depart(data, "2026-10-20", [key], "مشغل", datetime(2026, 10, 20, 7, 1))
    assert build_ops(data, "2026-10-20")["counters"]["out"] == 1
    return_(data, "2026-10-20", [key], "مشغل", datetime(2026, 10, 20, 7, 2))
    undo(data, "2026-10-20", key, "مشغل", datetime(2026, 10, 20, 7, 3))
    assert data["day_service_runs"]["2026-10-20"][key]["state"] == "out"


def test_next_is_future_only_and_archive_time_style():
    data = _data()
    data["service_lines"] = [{"id": "LINE-1", "name": "خط فيصل", "tag": "route",
                               "order": ["SVC-1"], "lorry_id": "LOR-3"}]
    data["service_catalog"][0]["tags"] = ["route"]
    data["service_counts"]["2026-10-20"]["entries"].append(
        {"id": "CNT-2", "name": "خدمة أ", "block": "ليلية", "count": 2, "weapon": ""})
    view = build_ops(data, "2026-10-20", datetime(2026, 10, 20, 19, 0))
    assert view["next"]["key"] == "SVC-1:pm"
    assert view["next"]["line_id"] == "LINE-1"
    assert view["next"]["line"] == "خط فيصل"
    assert view["next"]["report_time"] == "20:00"
    assert view["next"]["report_text"] == "8م"
    assert build_ops(data, "2026-10-20", datetime(2026, 10, 20, 21, 0))["next"] is None


def test_line_runs_follow_configured_order_and_absent_members_are_not_cards():
    data = _data()
    data["service_catalog"] = [
        {"id": "SVC-1", "name": "أ", "period": "صباحية", "report_am": "08:00", "tags": ["route"]},
        {"id": "SVC-2", "name": "ب", "period": "صباحية", "report_am": "08:00", "tags": ["route"]},
        {"id": "SVC-3", "name": "غائب", "period": "صباحية", "report_am": "08:00", "tags": ["route"]},
    ]
    data["service_lines"] = [{"id": "LN-1", "name": "خط", "tag": "route", "lorry_id": "LOR-1",
                               "order": ["SVC-2", "SVC-1", "SVC-3"]}]
    data["service_counts"]["2026-10-20"]["entries"] = [
        {"id": "CNT-1", "name": "أ", "service_id": "SVC-1", "block": "صباحية", "count": 1},
        {"id": "CNT-2", "name": "ب", "service_id": "SVC-2", "block": "صباحية", "count": 1},
    ]
    runs = build_ops(data, "2026-10-20")["groups"]["basic"]["am"]["lines"][0]["runs"]
    assert [run["key"] for run in runs] == ["SVC-2:am", "SVC-1:am"]
    assert runs[0]["line_meta"] == {"line_id": "LN-1", "name": "خط", "lorry": "المحور + المحكمة",
                                     "driver": None, "vehicle": None, "warning": None}


def test_afraad_link_head_and_catalog_fallbacks():
    data = _data()
    data["reference_lists"] = {"afraad_basic": [{"from": "2026-10-20", "items": [
        {"id": "AFB-1", "name": "خدمة أ", "service_id": "SVC-1"}]}]}
    data["day_afraad"] = {"2026-10-20": {"AFB-1": {"morning_name": "أمين شرطة/ محمد السيد"}}}
    data["service_counts"]["2026-10-20"]["entries"][0].update(count=None, weapon="")
    run = build_ops(data, "2026-10-20")["groups"]["basic"]["am"]["single"][0]
    assert run["head"] == "أمين شرطة/ محمد السيد"
    assert run["count"] == 7
    assert run["weapon"] == "آلي"


def test_officer_and_counts_aliases_share_departed_run():
    data = _data()
    data["service_catalog"] = [{"id": "SVC-2", "name": "التدخل السريع",
                                 "period": "صباحية", "report_am": "08:00", "tags": []}]
    data["day_assignments"]["2026-10-20"] = [{"id": "AS-1", "section": "الخدمات أساسية",
        "name": "تدخل سريع", "shift": "صباحية", "officer_ids": []}]
    data["service_counts"]["2026-10-20"]["entries"] = [{"id": "CNT-1", "name": "التدخل السريع",
        "block": "صباحية", "count": 1, "weapon": ""}]
    view = build_ops(data, "2026-10-20", datetime(2026, 10, 20, 7, 0))
    assert view["groups"]["officers"][0]["key"] == "SVC-2:am"
    assert view["groups"]["basic"]["am"]["single"][0]["key"] == "SVC-2:am"
    depart(data, "2026-10-20", ["SVC-2:am"], "مشغل", datetime(2026, 10, 20, 7, 1))
    view = build_ops(data, "2026-10-20", datetime(2026, 10, 20, 7, 2))
    assert view["groups"]["officers"][0]["state"] == "out"
    assert view["groups"]["basic"]["am"]["single"][0]["state"] == "out"


def _cross_day_data():
    services = [
        {"id": f"SVC-{i:03d}", "name": f"خدمة {i}", "period": "ليلية",
         "report_pm": "17:00", "count": 1, "weapon": "آلي", "tags": ["ln2"]}
        for i in (1, 4, 7, 10, 13)
    ]
    entries = [{"id": f"CNT-{i:03d}", "name": f"خدمة {i}", "block": "ليلية",
                "count": 1, "weapon": ""} for i in (1, 4, 7, 10, 13)]
    return {
        "service_catalog": services,
        "service_lines": [{"id": "LN-2", "name": "خط فيصل", "tag": "ln2",
                            "order": [service["id"] for service in services]}],
        "day_assignments": {}, "service_counts": {
            "2026-10-19": {"entries": entries}, "2026-10-20": {"entries": [dict(e) for e in entries]},
        },
        "day_afraad": {}, "day_campaign": {}, "day_service_runs": {},
        "day_status": {"2026-10-19": {"reopened_on": "2026-10-20"}},
        "reference_lists": {}, "personnel": [], "officers": [],
    }


def test_carried_runs_do_not_hide_or_share_today_runs():
    data = _cross_day_data()
    keys = [f"SVC-{i:03d}:pm" for i in (1, 4, 7, 10, 13)]
    depart(data, "2026-10-19", keys, "مشغل", datetime(2026, 10, 19, 17, 1))
    view = build_ops(data, "2026-10-20", datetime(2026, 10, 20, 8, 0))
    line = view["groups"]["basic"]["pm"]["lines"][0]
    assert {run["key"] for run in line["runs"]} == set(keys)
    assert {run["key"] for run in view["carried"]} == set(keys)
    assert all(run["day"] == "2026-10-19" for run in view["carried"])
    assert {run["ref"] for run in view["carried"]} == {f"2026-10-19/{key}" for key in keys}
    assert view["counters"]["out"] == 0
    assert view["counters"]["carried"] == 5


def test_returning_carried_ref_leaves_today_same_key_upcoming():
    data = _cross_day_data()
    key = "SVC-001:pm"
    depart(data, "2026-10-19", [key], "مشغل", datetime(2026, 10, 19, 17, 1))
    return_(data, "2026-10-20", [f"2026-10-19/{key}"], "مشغل", datetime(2026, 10, 20, 8, 1))
    view = build_ops(data, "2026-10-20", datetime(2026, 10, 20, 8, 2))
    today = next(run for line in view["groups"]["basic"]["pm"]["lines"]
                 for run in line["runs"] if run["key"] == key)
    assert today["state"] == "upcoming"
    assert all(run["key"] != key for run in view["carried"])
    assert data["day_service_runs"]["2026-10-19"][key]["back_at"]


def test_canonical_runs_keep_carried_identity_distinct_from_today():
    data = _cross_day_data()
    key = "SVC-001:pm"
    depart(data, "2026-10-19", [key], "مشغل", datetime(2026, 10, 19, 17, 1))
    view = build_ops(data, "2026-10-20", datetime(2026, 10, 20, 8, 0))
    identities = {run.get("ref") or run["key"] for run in view["runs"]}
    assert key in identities
    assert "2026-10-19/" + key in identities
    assert len(view["runs"]) == len(identities)


def test_custom_section_metadata_preserves_special_and_normal_names():
    data = _data()
    data["day_assignments"]["2026-10-20"] = [
        {"id": "SP-1", "section": "خدمات مباراة المصري", "name": "بوابة المباراة",
         "shift": "صباحية", "time": "8ص", "officer_ids": [], "conscript_count": 2},
        {"id": "IN-1", "section": "تفتيشات", "name": "تفتيش البوابة",
         "shift": "ليلية", "time": "10م", "officer_ids": [], "conscript_count": 1},
    ]
    runs = {run["name"]: run for run in build_ops(data, "2026-10-20")["runs"]}
    assert runs["بوابة المباراة"]["section_name"] == "خدمات مباراة المصري"
    assert runs["بوابة المباراة"]["section_kind"] == "special"
    # التفتيشات تبع الخدمات الطارئة، مش مجموعة لوحدها
    assert runs["تفتيش البوابة"]["section_name"] == "الخدمات الطارئة"
    assert runs["تفتيش البوابة"]["section_id"] == "emergency"
    assert runs["تفتيش البوابة"]["section_kind"] == "emergency"


def test_set_time_finds_line_runs_and_stores_catalog_default_as_hhmm(monkeypatch):
    from backend import day_status
    from backend.ops_board import set_time

    monkeypatch.setattr(day_status, "today_iso", lambda: "2026-10-20")
    data = _data()
    data["service_lines"] = [{"id": "LINE-1", "name": "خط فيصل", "tag": "route",
                               "order": ["SVC-1"], "lorry_id": "LOR-3"}]
    data["service_catalog"][0]["tags"] = ["route"]
    set_time(data, "2026-10-20", "SVC-1:am", "07:45", "default", "مشغل")
    assert data["service_catalog"][0]["report_am"] == "07:45"
    set_time(data, "2026-10-20", "SVC-1:am", "7:30ص", "day", "مشغل")
    run = build_ops(data, "2026-10-20")["groups"]["basic"]["am"]["lines"][0]["runs"][0]
    assert run["report_time"] == "07:30"


def test_set_time_day_scope_writes_emergency_board_row(monkeypatch):
    from backend import day_status
    from backend.ops_board import set_time

    monkeypatch.setattr(day_status, "today_iso", lambda: "2026-10-20")
    data = _data()
    data["day_assignments"]["2026-10-20"] = [
        {"id": "AS-9", "section": "الخدمات الطارئة", "name": "المحكمة", "shift": "صباحية",
         "time": "8ص", "officer_ids": [], "personnel_ids": [], "conscript_count": 5}]
    key = next(r["key"] for r in build_ops(data, "2026-10-20")["groups"]["emergency"]["single"]
               if r["name"] == "المحكمة")
    set_time(data, "2026-10-20", key, "09:30", "day", "مشغل")
    assert data["day_assignments"]["2026-10-20"][0]["time"] == "9:30ص"


def test_board_emergency_rows_get_their_own_key_time_and_shift():
    data = _data()
    data["day_assignments"]["2026-10-20"] = [
        {"id": "AS-7", "section": "الخدمات الطارئة", "name": "ترحيلة السجن", "shift": "ليلية",
         "time": "10م", "officer_ids": [], "personnel_ids": [], "conscript_count": 4},
        {"id": "AS-8", "section": "الخدمات الطارئة", "name": "تأمين مباراة", "shift": "صباحية",
         "time": "2:30م", "officer_ids": [], "personnel_ids": [], "conscript_count": 9}]
    runs = {r["name"]: r for r in build_ops(data, "2026-10-20")["groups"]["emergency"]["single"]}
    assert runs["ترحيلة السجن"]["key"] != runs["تأمين مباراة"]["key"]
    assert runs["ترحيلة السجن"]["shift"] == "pm"
    assert runs["ترحيلة السجن"]["report_time"] == "22:00"
    assert runs["تأمين مباراة"]["report_time"] == "14:30"


def test_optimised_build_is_stable_and_exposes_catalog_id_for_resolved_emergency():
    data = _data()
    data["day_assignments"]["2026-10-20"] = [
        {"id": "AS-7", "section": "الخدمات الطارئة", "name": "خدمة أ",
         "shift": "صباحية", "time": "8ص", "officer_ids": []},
    ]
    now = datetime(2026, 10, 20, 7, 0)
    first = build_ops(data, "2026-10-20", now)
    reference_data = deepcopy(data)
    reference_ctx = _BuildContext(reference_data)
    # مسار مرجعي لنفس البنية لكن من غير كاش الحملة أو فهرس ربط الأسماء.
    reference_ctx.campaign = lambda day: campaign.build_campaign(reference_data, day)
    reference_ctx.service_id = lambda name: resolve_service_id(reference_data, name)
    reference = _build_ops(reference_data, "2026-10-20", now, True, reference_ctx)
    assert first == reference
    run = first["groups"]["emergency"]["single"][0]
    assert run["catalog_id"] == "SVC-1"


def test_set_time_default_resolves_catalog_for_emergency_assignment():
    data = _data()
    data["day_assignments"]["2026-10-20"] = [
        {"id": "AS-9", "section": "الخدمات الطارئة", "name": "خدمة أ",
         "shift": "صباحية", "time": "8ص", "officer_ids": []},
    ]
    set_time(data, "2026-10-20", "AS-9:am", "09:30", "default", "مشغل")
    assert data["service_catalog"][0]["report_am"] == "09:30"


def test_set_time_default_rejects_unresolvable_emergency_cleanly():
    data = _data()
    data["day_assignments"]["2026-10-20"] = [
        {"id": "AS-9", "section": "الخدمات الطارئة", "name": "خدمة مش موجودة",
         "shift": "صباحية", "time": "8ص", "officer_ids": []},
    ]
    with pytest.raises(ValueError, match="مش موجودة في دليل الخدمات"):
        set_time(data, "2026-10-20", "AS-9:am", "09:30", "default", "مشغل")


def test_edit_time_route_builds_response_once(client, monkeypatch):
    def seed(data):
        data["service_catalog"] = [{"id": "SVC-1", "name": "خدمة أ",
                                    "period": "صباحية", "report_am": "08:00", "tags": []}]
        data["day_assignments"] = {"2026-10-20": [{"id": "AS-9",
            "section": "الخدمات الطارئة", "name": "خدمة أ", "shift": "صباحية",
            "time": "8ص", "officer_ids": []}]}
    store.with_data(seed, ())
    revision = client.get("/api/ops/2026-10-20").get_json()["revision"]
    original = ops_board.build_ops
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(ops_board, "build_ops", counted)
    response = client.patch("/api/ops/2026-10-20/time", json={
        "key": "AS-9:am", "time": "09:30", "scope": "day", "revision": revision})
    assert response.status_code == 200
    assert len(calls) == 1


def test_single_shift_afraad_schedule_does_not_leak_into_night():
    data = _data()
    data["reference_lists"] = {"afraad_basic": [{"from": "2026-10-20", "items": [
        {"id": "AFB-1", "name": "خدمة أ", "service_id": "SVC-1"}]}]}
    data["day_afraad"] = {"2026-10-20": {"AFB-1": {"schedule": "7 ص فترة صباحة"}}}
    data["service_counts"]["2026-10-20"]["entries"].append(
        {"id": "CNT-2", "name": "خدمة أ", "block": "ليلية", "count": 2, "weapon": ""})
    groups = build_ops(data, "2026-10-20")["groups"]["basic"]
    assert groups["am"]["single"][0]["report_time"] == "07:00"
    # الليلي مالوش معاد في يومية الأفراد → معاد الدليل (20:00)، مش 7 الصبح
    assert groups["pm"]["single"][0]["report_time"] == "20:00"
