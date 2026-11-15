"""القالب فيه خانات ثابتة (24+8+2)؛ الضابط الزيادة لازم يتطبع مش يختفي."""
from docx import Document

from backend.duty_export import build_docx


def _row(number, section):
    return {"name": f"ضابط {number}", "role": "ملازم أول", "post": "عمل", "status": "عمل",
            "group": "صافي", "bucket": "صافي", "services": [], "section": section}


def _duty(force, guards=0, outside=0):
    rows = [_row(i, "القوة") for i in range(force)]
    rows += [_row(100 + i, "الحراسات المشددة") for i in range(guards)]
    rows += [_row(200 + i, "الخوارج") for i in range(outside)]
    from backend.duty import summarise
    base = summarise({}, "2026-11-15")
    return {"date": "2026-11-15", "rows": rows, "summary": base["summary"], "signatories": {}}


def test_extra_officer_in_each_section_is_printed():
    document = Document(build_docx(_duty(25, 9, 3)))
    text = "\n".join(c.text for r in document.tables[0].rows for c in r.cells)

    for name in ("ضابط 24", "ضابط 108", "ضابط 202"):
        assert name in text
    numbers = [r.cells[0].text.strip() for r in document.tables[0].rows if r.cells[0].text.strip().endswith("-")]
    assert len(numbers) == 37
