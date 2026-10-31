from copy import deepcopy
from pathlib import Path

from importer import corrections

DAY = "2026-08-01"


def _assignment(name="الاسم القديم", officer="OFF-1", count=1):
    return {"id": "AS-0001", "section": "الخدمات الطارئة", "name": name,
            "time": "8ص", "party": "", "officer_ids": [officer], "personnel_ids": ["IND-1"],
            "conscript_count": count, "weapon": "آلي"}


def _day(row=None):
    return {"assignments": [row or _assignment()],
            "afraad_basic": {"AFB-01": {"morning_person_id": "IND-1", "night_person_id": "IND-2",
                                           "count": "2", "weapon": "آلي", "schedule": "8/8"}},
            "officer_states": {"OFF-1": {"status": "راحة", "taqseera": True, "note": "قديم"}},
            "counts": {"entries": [{"id": "CNT-001", "name": "خدمة", "block": "صباحية",
                                     "count": 1, "party": "", "weapon": "", "order": 1}]},
            "import": {"batch": "original-batch", "at": "original-batch"}}


def _data(row=None):
    blob = _day(row)
    return {"schema": 6, "day_assignments": {DAY: blob["assignments"]},
            "day_afraad": {DAY: blob["afraad_basic"]}, "day_officers": {DAY: blob["officer_states"]},
            "service_counts": {DAY: blob["counts"]}, "day_import": {DAY: blob["import"]},
            "change_log": [{"id": "CHG-1", "ts": "2026-10-01T10:00:00", "entity": "import",
                            "entity_id": "original-batch", "day": None}]}


def _provenance():
    return {"assignments": {"AS-0001": {"path": "2026/8/1/1.docx", "table": 0, "row": 1,
                                               "rule": "board_row"}},
            "counts": [{"path": "2026/8/1/counts.xlsx", "table": 0, "row": 4,
                        "rule": "counts_row", "raw": "خدمة = 1"}]}


def _run(data, archive, *, apply=True, original=None, kinds=("board",)):
    if "afraad_basic" in kinds:
        from backend.dated import afraad_basic_on
        names = {row["id"]: row["name"] for row in afraad_basic_on(data, DAY)}
        archive["_afraad_names"] = {"AFB-01": names["AFB-01"]}
    original = original or _day()
    return corrections.run_import(
        data, Path("/unused"), DAY, DAY, kinds=kinds,
        archive_days={DAY: archive}, archive_provenance={DAY: _provenance()},
        original_loader=lambda marker, day: (deepcopy(original), _provenance()), apply=apply)


def test_extraction_to_field_diff_applies_only_the_archive_value():
    data = _data()
    archive = _day(_assignment(name="الاسم الصحيح", officer="OFF-2", count=3))

    report = _run(data, archive)

    fields = {op.field: (op.stored, op.archive) for op in report.ops}
    assert fields["name"] == ("الاسم القديم", "الاسم الصحيح")
    assert fields["officer_ids"] == (["OFF-1"], ["OFF-2"])
    assert fields["conscript_count"] == (1, 3)
    assert data["day_assignments"][DAY][0]["name"] == "الاسم الصحيح"
    assert corrections.totals(report)["risks"] == {"person_id_swap": 1, "count_change": 1}


def test_field_touched_after_import_is_protected_even_when_reverted():
    data = _data()
    data["change_log"].append({
        "id": "CHG-2", "ts": "2026-10-02T10:00:00", "entity": "assignment",
        "entity_id": "AS-0001", "day": DAY,
        "before": {"name": "الاسم القديم"}, "after": {"name": "تعديل مستخدم"},
    })
    archive = _day(_assignment(name="الاسم الصحيح"))

    report = _run(data, archive)

    op = next(op for op in report.ops if op.field == "name")
    assert op.status == "protected"
    assert "اتعدل بعد" in op.reason
    assert data["day_assignments"][DAY][0]["name"] == "الاسم القديم"


def test_correction_is_idempotent():
    data = _data()
    archive = _day(_assignment(name="الاسم الصحيح"))

    first = _run(data, archive)
    second = _run(data, archive)

    assert corrections.totals(first)["correct"] == 1
    assert corrections.totals(second)["correct"] == 0
    assert data["day_assignments"][DAY][0]["name"] == "الاسم الصحيح"


def test_dry_run_does_not_mutate_data():
    data = _data()
    before = deepcopy(data)
    archive = _day(_assignment(name="الاسم الصحيح"))

    report = _run(data, archive, apply=False)

    assert corrections.totals(report)["correct"] == 1
    assert data == before


def test_basic_officer_and_counts_fields_are_covered():
    data = _data()
    archive = _day()
    archive["afraad_basic"]["AFB-01"].update(morning_person_id="IND-9", count="3", schedule="9/9")
    archive["officer_states"]["OFF-1"].update(status="مأمورية", note="صحيح")
    archive["counts"]["entries"][0]["count"] = 4

    report = _run(data, archive, kinds=("afraad_basic", "officers", "counts"))

    changed = {(op.kind, op.field) for op in report.ops if op.status == "correct"}
    assert {("afraad_basic", "morning_person_id"), ("afraad_basic", "count"),
            ("afraad_basic", "schedule"), ("officers", "status"), ("officers", "note"),
            ("counts", "count")} <= changed
