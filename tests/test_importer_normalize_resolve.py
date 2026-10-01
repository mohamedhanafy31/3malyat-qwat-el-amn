import csv
import datetime as dt
import json

import pytest

from importer.ledger import Ledger, atomic_write_jsonl
from importer.normalize import (
    name_compatible,
    normalize_conscripts,
    normalize_grade,
    normalize_name,
    normalize_officer_daily,
    normalize_party,
    normalize_phones,
    normalize_rank,
    normalize_rest,
    normalize_seniority,
    normalize_shift,
    normalize_time,
    normalize_weapons,
    parse_leave,
    run_normalize,
)
from importer.resolve import Observation, cluster_officers, cluster_personnel, collect_observations, run_resolve


@pytest.mark.parametrize(("raw", "expected", "qualifier"), [
    ("م.اول", "ملازم أول", ""), ("م.أول", "ملازم أول", ""),
    ("م اول", "ملازم أول", ""), ("ملازم اول", "ملازم أول", ""),
    ("رايد", "رائد", ""), ("مقدم طبيب", "مقدم", "طبيب"),
    ("مقدم صيدلي", "مقدم", "صيدلي"),
])
def test_rank_normalizer(raw, expected, qualifier):
    value = normalize_rank(raw)
    assert value["value"] == expected
    assert value["qualifier"] == qualifier
    assert value["valid"] is True
    assert value["raw"] == raw


def test_unknown_rank_is_flagged():
    assert normalize_rank("رتبة تجريبية")["flags"] == ["unknown_rank"]


@pytest.mark.parametrize(("raw", "expected"), [
    ("م.ش", "م.ش"), ("م ش", "م.ش"), ("مش", "م.ش"), ("م.ِش", "م.ش"),
    ("ا.ش", "ا.ش"), ("أ.ش", "ا.ش"), ("اش", "ا.ش"), ("ا ش", "ا.ش"),
    ("رقيب أول", "رقيب"), ("مساعد شرطة", "مساعد"), ("مندوب", "مندوب"),
    ("معاون شرطة", "معاون"), ("أمين شرطة ثان", "أمين"),
])
def test_grade_normalizer(raw, expected):
    value = normalize_grade(raw)
    assert value["value"] == expected
    assert value["valid"] is True


def test_name_keeps_display_and_builds_backend_key():
    value = normalize_name("  عبد الـرحمن أحمد  ")
    assert value["value"] == "عبد الرحمن أحمد"
    assert value["key"] == "عبدالرحمن احمد"


def test_phone_extraction_tolerates_formatting_and_rejects_bad_length():
    value = normalize_phones("'010 1234-5678' و(01123456789) و01012")
    assert value["value"] == ["01012345678", "01123456789"]
    assert value["flags"] == []


@pytest.mark.parametrize(("raw", "code", "qualifier"), [
    ("2016|1211/", "1211/2016", ""), ("765 / 2002", "765/2002", ""),
    ("2681/2010", "2681/2010", ""),
    ("2016|1211/60", "1211/2016", "/60"),
])
def test_seniority_normalizer(raw, code, qualifier):
    value = normalize_seniority(raw)
    assert (value["value"], value["qualifier"]) == (code, qualifier)


@pytest.mark.parametrize(("raw", "expected"), [
    ("صبح", ["صباحية"]), ("فترة صباحية", ["صباحية"]), ("ص", ["صباحية"]),
    ("ليل", ["ليلية"]), ("مسائية", ["ليلية"]), ("فترة ليلية", ["ليلية"]),
    ("صباحية + ليلية", ["صباحية", "ليلية"]),
])
def test_shift_normalizer(raw, expected):
    assert normalize_shift(raw)["value"] == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("8ص", ["8ص"]), ("8 ص", ["8ص"]), ("12ظ", ["12ظ"]),
    ("2:30م", ["2:30م"]), ("8 ص / 8 م", ["8ص", "8م"]),
    ("11 ص حتى الانتهاء", ["11ص"]),
])
def test_time_normalizer(raw, expected):
    assert normalize_time(raw)["value"] == expected


def test_party_normalizer_handles_quotes_and_stadium_suffix():
    assert normalize_party('ترحيلة "عتاقة"')["value"] == ["عتاقة"]
    assert normalize_party("الخدمة باستاد الجيش")["value"] == ["استاد الجيش"]


@pytest.mark.parametrize(("raw", "entries", "total"), [
    ("2 مج", [{"class": "مج", "count": 2}], 2),
    ("1 وحدة فض", [{"class": "وحدة فض", "count": 1}], 1),
    ("1 خفيفة + 5 طلبة", [{"class": "خفيفة", "count": 1}, {"class": "طلبة", "count": 5}], 6),
    ("(3 مجند)", [{"class": "مج", "count": 3}], 3),
    ("+ 1 سائق", [{"class": "سائق", "count": 1}], 1),
    ("فرد + مج", [{"class": "فرد", "count": 1}, {"class": "مج", "count": 1}], 2),
])
def test_conscript_normalizer(raw, entries, total):
    value = normalize_conscripts(raw)
    assert value["value"] == entries
    assert value["conscript_count"] == total


def test_conscript_total_can_coexist_with_weapon_breakdown():
    value = normalize_conscripts("5 مجند (1 الي + 4 دونك)")
    assert value["conscript_count"] == 5
    assert value["flags"] == []


@pytest.mark.parametrize(("raw", "expected"), [
    ("ألي + الى", "آلي"), ("خرطوش + فدرال", "خرطوش + فيدرال"),
    ("دونك + كلبش + مايك فض", "دونك + كلبش + مايك فض"),
    ("فض + بريتا + رياضي", "فض + بريتا + رياضي"),
])
def test_weapon_normalizer(raw, expected):
    assert normalize_weapons(raw)["value"] == expected


def test_leave_dates_use_document_year_and_roll_december_to_january():
    leave = parse_leave("راحة شهرية من 29/12 عودة 5/1 (2/7)", dt.date(2025, 12, 30))
    assert leave == {
        "raw": "راحة شهرية من 29/12 عودة 5/1 (2/7)", "type": "شهرية",
        "start": "2025-12-29", "end": "2026-01-04", "return_date": "2026-01-05",
        "counter": {"current": 2, "total": 7},
    }


def test_officer_daily_splits_status_taqseera_leave_and_service():
    value = normalize_officer_daily("خدمة تجريبية + تقصيره + اجازة طارئة حتى 3/9",
                                    dt.date(2026, 9, 2))
    assert value["taqseera"] is True
    assert value["status"] == "طارئة"
    assert value["leaves"][0]["type"] == "إجازة طارئة"
    assert value["services"] == ["خدمة تجريبية"]


@pytest.mark.parametrize(("raw", "system", "day"), [
    ("الخميس", "أسبوعية", "الخميس"), ("نصف شهرية", "نصف شهرية", ""),
    ("شهرية", "شهرية", ""), ("---", "—", ""),
])
def test_rest_normalizer(raw, system, day):
    assert normalize_rest(raw)["value"] == {"rest_system": system, "rest_day": day}


def test_name_compatibility_requires_first_two_and_ordered_subsequence():
    assert name_compatible("أحمد محمد", "أحمد محمد علي حسن")
    assert name_compatible("أحمد محمد حسن", "أحمد محمد علي حسن")
    assert not name_compatible("أحمد علي", "أحمد محمد علي")
    assert not name_compatible("أحمد", "أحمد محمد")


def _obs(key, kind, day, name, **extra):
    return Observation(key, kind, day, extra.pop("role", "roster"), name, normalize_name(name)["key"], **extra)


def test_officer_clustering_prefers_code_exact_name_and_short_board_form():
    values = [
        _obs("a", "officer", "2026-09-01", "جمال محمد حسن أمين", code="10/2020", rank_grade="رائد"),
        _obs("b", "officer", "2026-09-02", "جمال محمد حسن امين", code="10/2020", rank_grade="رائد"),
        _obs("c", "officer", "2026-09-02", "جمال امين", role="board", rank_grade="رائد"),
        _obs("d", "officer", "2026-09-02", "جمال آخر", role="board", rank_grade="رائد"),
    ]
    clusters, mapping = cluster_officers(values)
    assert len(clusters) == 1
    assert mapping["a"] == mapping["b"] == mapping["c"]
    assert "d" not in mapping


def test_officer_fuzzy_consolidation_allows_promotion():
    values = [
        _obs("a", "officer", "2024-01-01", "أحمد محمد علي", rank_grade="ملازم"),
        _obs("b", "officer", "2025-01-01", "أحمد محمد علي حسن", rank_grade="رائد"),
    ]
    assert len(cluster_officers(values)[0]) == 1


def test_cooccurrence_vetoes_fuzzy_officer_merge():
    values = [
        _obs("a", "officer", "2026-01-01", "أحمد السيد عبداللطيف", rank_grade="رائد"),
        _obs("b", "officer", "2026-01-01", "أحمد سيد عبداللطيف خالد", rank_grade="رائد"),
    ]
    clusters, mapping = cluster_officers(values)
    assert len(clusters) == 2
    assert mapping["a"] != mapping["b"]


def test_fuzzy_variant_merges_into_anchor_without_cooccurrence():
    anchors = [
        _obs("anchor", "officer", "", "عبدالرحمن رفعت الحسيني", anchor_id="OFF-016", role="snapshot"),
    ]
    values = [
        _obs("archive", "officer", "2025-01-01", "عبدالرحمن رافت الحسيني"),
    ]
    clusters, mapping = cluster_officers(values, anchors)
    assert len(clusters) == 1
    assert mapping["archive"] == "0"


def test_personnel_cooccurrence_veto_uses_document():
    values = [
        _obs("a", "personnel", "2026-01-01", "أحمد السيد عبداللطيف", role="afraad", document="a.docx"),
        _obs("b", "personnel", "2026-01-01", "أحمد سيد عبداللطيف خالد", role="afraad", document="a.docx"),
    ]
    assert len(cluster_personnel(values)[0]) == 2


def test_trailing_non_name_tokens_are_cut_before_identity_use():
    records = [{
        "date": "2026-01-01", "role": "roster", "path": "a.docx",
        "table_index": 0, "row_index": 1, "raw_cells": [],
        "normalized": {"officer": {
            "name": {"value": "أشرف الشريف تقصيره"}, "seniority": {"value": ""},
            "rank": {"value": "رائد"}, "phones": {"value": []}, "post": {"value": ""},
        }},
    }]
    officers, _personnel = collect_observations(records)
    assert officers[0].name == "أشرف الشريف"
    assert officers[0].name_key == "اشرف الشريف"


def test_shared_officer_code_does_not_collapse_incompatible_names():
    values = [
        _obs("a", "officer", "2026-01-01", "أحمد محمود كامل", code="10/2020", rank_grade="رائد"),
        _obs("b", "officer", "2026-01-01", "محمد علي حسن", code="10/2020", rank_grade="رائد"),
    ]
    assert len(cluster_officers(values)[0]) == 2


def test_snapshot_year_is_compatible_but_not_a_strong_code_key():
    anchors = [
        _obs("anchor:1", "officer", "", "خالد خلف الله خليفة", code="2012",
             anchor_id="OFF-001", role="snapshot"),
        _obs("anchor:2", "officer", "", "ضابط مختلف تماما", code="2012",
             anchor_id="OFF-002", role="snapshot"),
    ]
    values = [
        _obs("a", "officer", "2026-01-01", "خالد خلف خليفة", code="1803/2012"),
    ]
    clusters, mapping = cluster_officers(values, anchors)
    matched = next(group for group in clusters if any(item.key == "a" for item in group))
    assert {item.anchor_id for item in matched if item.anchor_id} == {"OFF-001"}
    assert mapping["a"] is not None
    assert len(clusters) == 2


def test_personnel_short_name_does_not_chain_two_phones():
    values = [
        _obs("a", "personnel", "2026-01-01", "فرد تجريبي أول", phone="01000000000"),
        _obs("b", "personnel", "2026-01-02", "فرد تجريبي", phone="01000000000"),
        _obs("c", "personnel", "2026-01-03", "فرد تجريبي", phone="01111111111"),
    ]
    clusters, _ = cluster_personnel(values)
    assert len(clusters) == 2


def test_short_officer_forms_cannot_bridge_two_strong_clusters():
    values = [
        _obs("a", "officer", "2026-09-02", "محمد فؤاد وحيد", code="1/2020", rank_grade="رائد"),
        _obs("b", "officer", "2026-09-02", "محمد عبدالعزيز محمود", code="2/2020", rank_grade="رائد"),
        _obs("short-a", "officer", "2026-09-02", "محمد فؤاد", role="board", rank_grade="رائد"),
        _obs("short-b", "officer", "2026-09-02", "محمد عبدالعزيز", role="board", rank_grade="رائد"),
    ]
    clusters, mapping = cluster_officers(values)
    assert len(clusters) == 2
    assert mapping["a"] == mapping["short-a"]
    assert mapping["b"] == mapping["short-b"]
    assert mapping["a"] != mapping["b"]


def test_shared_phone_does_not_merge_incompatible_full_names():
    values = [
        _obs("a", "personnel", "2026-01-01", "أحمد محمود كامل", phone="01000000000"),
        _obs("b", "personnel", "2026-01-01", "محمد علي حسن", phone="01000000000"),
    ]
    clusters, mapping = cluster_personnel(values)
    assert len(clusters) == 2
    assert mapping["a"] != mapping["b"]


def test_stage_outputs_bom_csv_decisions_override_and_proposed_map(tmp_path):
    data = tmp_path / "data"
    ledger = Ledger(data, "batch")
    state = ledger.initialise({}, {})
    (data / "core.json").write_text(json.dumps({
        "officers": [{"id": "OFF-001", "name": "ضابط تجريبي كامل", "code": "10/2020"}],
        "personnel": [{"id": "IND-001", "name": "فرد تجريبي كامل", "phone": "01000000000"}],
    }, ensure_ascii=False), encoding="utf-8")
    atomic_write_jsonl(ledger.staging_path("extract"), [{
        "record_type": "roster_row", "date": "2026-09-02", "role": "roster", "path": "sample.docx",
        "fields": {"الرتبة": "رائد", "رقم الأقدمية": "10/2020", "الاسم": "ضابط تجريبي كامل",
                   "العمل المسند إليه": "قسم تجريبي", "التشغيل اليومي": "عمل", "الراحات": "الخميس"},
        "raw_cells": [], "raw_text": None,
    }, {
        "record_type": "afraad_basic_row", "date": "2026-09-02", "role": "afraad", "path": "afraad.docx",
        "aligned": {"الخدمة الصباحية": "م.ش/ فرد تجريبي كامل 01000000000"},
        "raw_cells": [], "raw_text": None,
    }])
    run_normalize(ledger, state)
    first = run_resolve(ledger, state)
    assert first["officers"]["matched_existing"] == 1
    assert first["personnel"]["matched_existing"] == 1
    assert (ledger.root / "review" / "officers.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    decision_path = ledger.root / "decisions" / "officers.csv"
    rows = list(csv.DictReader(decision_path.open(encoding="utf-8-sig")))
    rows[0]["chosen_id"] = "OFF-999"
    with decision_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader(); writer.writerows(rows)
    personnel_decision = ledger.root / "decisions" / "personnel.csv"
    personnel_rows = list(csv.DictReader(personnel_decision.open(encoding="utf-8-sig")))
    personnel_rows[0]["status"] = "تجاهل"
    with personnel_decision.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=personnel_rows[0])
        writer.writeheader(); writer.writerows(personnel_rows)
    second = run_resolve(ledger, state)
    review = list(csv.DictReader((ledger.root / "review" / "officers.csv").open(encoding="utf-8-sig")))
    assert review[0]["proposed_id"] == "OFF-999"
    assert second["officers"]["clusters"] == 1
    assert second["personnel"]["clusters"] == 0
    assert second["personnel"]["unresolved_observations"] == 1
    proposed = json.loads((ledger.root / "staging" / "batch" / "id_map.proposed.json").read_text())
    assert proposed["personnel"] == {}
    assert (ledger.root / "staging" / "batch" / "id_map.proposed.json").exists()


def test_short_roster_name_without_candidate_becomes_its_own_officer():
    # «هشام عيسي» مكتوب مختصرًا في يومية الضباط ومالوش مرشح — شخص مستقل، بينما
    # الاسم المختصر على اللوحة من غير مرشح يفضل غير محسوم
    values = [
        _obs("r1", "officer", "2023-10-01", "هشام عيسي", rank_grade="عميد"),
        _obs("r2", "officer", "2023-10-02", "هشام عيسي", rank_grade="عميد"),
        _obs("b1", "officer", "2023-10-02", "سامح فؤاد", role="board", rank_grade="رائد"),
    ]
    clusters, mapping = cluster_officers(values)
    assert mapping["r1"] == mapping["r2"]
    assert "b1" not in mapping


def test_short_roster_name_attaches_to_single_compatible_identity_ignoring_article():
    values = [
        _obs("a", "officer", "2024-08-01", "طارق عادل جاويش", rank_grade="عميد"),
        _obs("b", "officer", "2024-08-02", "طارق عادل جاويش", rank_grade="عميد"),
        _obs("c", "officer", "2024-07-31", "طارق الجاويش", rank_grade="عميد"),
    ]
    clusters, mapping = cluster_officers(values)
    assert mapping["c"] == mapping["a"] == mapping["b"]


def test_identity_decisions_for_vanished_clusters_are_kept(tmp_path):
    import csv
    from importer.resolve import _write_current_decisions
    path = tmp_path / "officers.csv"
    prior = {"officer:قديم:2024-01-01": {"cluster_key": "officer:قديم:2024-01-01", "chosen_id": "",
                                        "status": "تجاهل", "note": "قرار سابق"}}
    _write_current_decisions(path, [{"cluster_key": "officer:جديد:2024-01-02"}], prior)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["cluster_key"] for row in rows] == ["officer:جديد:2024-01-02", "officer:قديم:2024-01-01"]
    assert rows[1]["status"] == "تجاهل"
