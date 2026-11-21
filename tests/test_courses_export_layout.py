"""تنسيق تصدير الفرق والدورات وكشف بيانات الضباط (عرض الأعمدة وسطر الالتحاق)."""
from io import BytesIO

from docx import Document
from docx.oxml.ns import qn

from backend import people_export
from backend.routes.courses import _short_date, _term_line


def test_term_line_has_short_dates_and_no_empty_brackets():
    base = {"officer_role": "رائد", "officer_name": "محمد أحمد"}
    assert _short_date("2026-09-05") == "5/9/26"
    assert _term_line({**base, "start": "2026-09-05", "end": "2026-09-17"}) == "رائد/ محمد أحمد (5/9/26 – 17/9/26)"
    assert _term_line({**base, "start": "", "end": ""}) == "رائد/ محمد أحمد"
    assert _term_line({**base, "start": "2026-09-05", "end": ""}) == "رائد/ محمد أحمد (5/9/26)"


def test_term_line_shortens_first_lieutenant_for_exports():
    assert _term_line({"officer_role": "ملازم أول", "officer_name": "علي حسن",
                       "start": "", "end": ""}) == "م.أول/ علي حسن"


def test_officers_export_columns_fit_the_usable_width():
    widths = [column[3] for column in people_export.COLUMNS["officers"]]
    assert abs(sum(widths) - people_export.USABLE_WIDTH_CM) < 0.05
    post = next(column for column in people_export.COLUMNS["officers"] if column[0] == "post")
    address = next(column for column in people_export.COLUMNS["officers"] if column[0] == "address")
    assert post[3] > address[3]  # العمل المسند أطول نصًا من العنوان فياخد عرض أكبر


def _doc(response):
    assert response.status_code == 200
    return Document(BytesIO(response.data))


def _add_third_officer():
    from backend import store

    def add(data):
        data["officers"].append({
            "id": "OFF-003", "name": "علي حسن", "role": "ملازم أول", "code": "3",
            "phone": "0102", "join_date": "2020-01-01", "post": "",
            "status": "active", "rest_system": "—", "rest_day": "",
        })

    store.with_data(add)


def _course(client, name="فرقة الحماية"):
    response = client.post("/api/courses", json={"name": name, "place": "معهد التدريب"})
    assert response.status_code == 201
    return response.get_json()


def _term(client, course_id, officer_id, start, end):
    response = client.post("/api/course-terms", json={
        "course_id": course_id, "officer_id": officer_id, "start": start, "end": end,
    })
    assert response.status_code == 201, response.get_data(as_text=True)


def test_course_export_has_ordered_numbered_grid_and_no_removed_headers(client):
    _add_third_officer()
    course = _course(client)
    for officer_id in ("OFF-003", "OFF-002", "OFF-001"):
        _term(client, course["id"], officer_id, "2026-04-05", "2026-04-15")

    doc = _doc(client.get("/api/courses/export.docx?view=course"))
    table = doc.tables[0]
    assert [cell.text for cell in table.rows[0].cells] == [
        "م", "اسم الفرقة", "المكان", "الضباط والالتحاقات"]
    assert all(header not in "\n".join(cell.text for row in table.rows for cell in row.cells)
               for header in ("ملاحظات", "النوع"))

    grouped = table.rows[1].cells[3]
    assert len(grouped.tables) == 1
    nested = grouped.tables[0]
    assert len(nested.columns) == 2
    assert len(nested._tbl.tblGrid.findall(qn("w:gridCol"))) == 2
    assert nested._tbl.tblPr.find(qn("w:bidiVisual")) is not None
    assert grouped._tc[-1].tag == qn("w:p")
    assert grouped._tc[-1].text in (None, "")
    assert all(border.get(qn("w:val")) == "nil"
               for border in nested._tbl.tblPr.find(qn("w:tblBorders")))
    assert all(cell.text.startswith(expected) for cell, expected in zip(
        [cell for row in nested.rows for cell in row.cells],
        ["1- عقيد/", "2- نقيب/", "3- م.أول/"]))
    nested_text = "\n".join(cell.text for row in nested.rows for cell in row.cells)
    assert "5/4/26 – 15/4/26" in nested_text


def test_officer_export_numbers_courses_and_includes_each_period(client):
    first = _course(client, "فرقة أولى")
    second = _course(client, "فرقة ثانية")
    _term(client, first["id"], "OFF-001", "2026-05-05", "2026-05-15")
    _term(client, second["id"], "OFF-001", "2026-04-05", "2026-04-15")

    doc = _doc(client.get("/api/courses/export.docx?view=officer"))
    table = doc.tables[0]
    assert "النوع" not in table.rows[0].cells[0].text
    row = next(row for row in table.rows[1:] if "أحمد محمد" in row.cells[1].text)
    text = " ".join(row.cells[6]._tc.itertext())  # يشمل الجدول المتداخل (عمودين)
    assert "1- فرقة ثانية" in text and "5/4/26 – 15/4/26" in text
    assert "2- فرقة أولى" in text and "5/5/26 – 15/5/26" in text

    _add_third_officer()
    third_course = _course(client, "فرقة ملازم أول")
    _term(client, third_course["id"], "OFF-003", "2026-06-05", "2026-06-15")
    doc = _doc(client.get("/api/courses/export.docx?view=officer"))
    row = next(row for row in doc.tables[0].rows[1:] if "علي حسن" in row.cells[1].text)
    assert row.cells[2].text == "م.أول"
