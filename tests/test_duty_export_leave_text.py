"""صياغة الراحات في خانة «التشغيل اليومي» بملف Word فقط."""
import pytest

from backend.duty_export import _daily_text


@pytest.mark.parametrize(("raw_type", "label", "expected"), [
    ("أسبوعية", "أسبوعية", "راحة أسبوعية"),
    ("نصف شهرية", "نصف شهرية", "راحة نصف شهرية (من 25/10 والعودة 28/10)"),
    ("شهرية", "شهرية", "راحة شهرية (من 25/10 والعودة 28/10)"),
    ("إجازة طارئة", "إجازة طارئة", "إجازة طارئة (من 25/10 والعودة 28/10)"),
    ("إجازة خاصة", "إجازة خاصة — إجازة عيد",
     "إجازة خاصة — إجازة عيد (من 25/10 والعودة 28/10)"),
])
def test_daily_export_formats_leave_type_and_dates(raw_type, label, expected):
    row = {"leave": {
        "raw_type": raw_type, "type": label, "start": "2026-10-25",
        "end": "2026-10-27", "return_date": "2026-10-28",
    }}
    assert _daily_text(row) == expected


def test_daily_export_uses_day_after_end_when_return_date_is_missing():
    row = {"leave": {
        "raw_type": "مجمعة", "type": "مجمعة", "start": "2026-12-31",
        "end": "2027-01-02", "return_date": "",
    }}
    assert _daily_text(row) == "راحة مجمعة (من 31/12 والعودة 3/1)"
