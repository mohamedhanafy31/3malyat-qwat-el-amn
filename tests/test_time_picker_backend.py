from backend.assignments import apply_assignment, blank


def _row(time=""):
    return blank("AS-1", "خدمة", "قسم", time=time)


def test_assignment_time_is_normalized_to_archive_format():
    row, error, status = apply_assignment({}, "2026-10-20", _row(), {"time": "08:15"})

    assert (error, status) == (None, None)
    assert row["time"] == "8:15ص"


def test_assignment_time_can_be_cleared():
    row, error, status = apply_assignment({}, "2026-10-20", _row("8ص"), {"time": ""})

    assert (error, status) == (None, None)
    assert row["time"] == ""


def test_assignment_time_rejects_new_unparseable_text():
    row, error, status = apply_assignment({}, "2026-10-20", _row(), {"time": "بعد الفجر"})

    assert row is None
    assert status == 400
    assert error == "اختر معاد الانتظام من لوحة الساعة."


def test_legacy_assignment_time_is_preserved_when_unchanged():
    row, error, status = apply_assignment({}, "2026-10-20", _row("بعد الفجر"), {"time": "بعد الفجر"})

    assert (error, status) == (None, None)
    assert row["time"] == "بعد الفجر"
