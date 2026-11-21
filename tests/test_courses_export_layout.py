"""تنسيق تصدير الفرق والدورات وكشف بيانات الضباط (عرض الأعمدة وسطر الالتحاق)."""
from backend import people_export
from backend.routes.courses import _short_date, _term_line


def test_term_line_has_short_dates_and_no_empty_brackets():
    base = {"officer_role": "رائد", "officer_name": "محمد أحمد"}
    assert _short_date("2026-09-05") == "5/9/26"
    assert _term_line({**base, "start": "2026-09-05", "end": "2026-09-17"}) == "رائد / محمد أحمد (5/9/26 – 17/9/26)"
    assert _term_line({**base, "start": "", "end": ""}) == "رائد / محمد أحمد"
    assert _term_line({**base, "start": "2026-09-05", "end": ""}) == "رائد / محمد أحمد (5/9/26)"


def test_officers_export_columns_fit_the_usable_width():
    widths = [column[3] for column in people_export.COLUMNS["officers"]]
    assert abs(sum(widths) - people_export.USABLE_WIDTH_CM) < 0.05
    post = next(column for column in people_export.COLUMNS["officers"] if column[0] == "post")
    address = next(column for column in people_export.COLUMNS["officers"] if column[0] == "address")
    assert post[3] > address[3]  # العمل المسند أطول نصًا من العنوان فياخد عرض أكبر
