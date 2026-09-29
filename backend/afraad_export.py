"""تصدير يومية الأفراد كملف Word حقيقي — نفس شكل ورقة «افراد» الحقيقية:
جدول واحد متواصل، الأساسية أول (الخدمة/الصباحية/الليلية/القوام/التسليح/
الانتظام)، وتحتها صف عنوان «الخدمات الطارئة» ممتد على العرض وبعده صفوف
الطوارئ (+ أي قسم مخصّص) بنفس الأعمدة. بيستخدم نفس أدوات RTL/الحدود
اللي `board_export.py` بنى بيها ملف الضباط، عشان الاتنين يفضلوا بنفس
الشكل بالظبط."""
from datetime import date
from io import BytesIO

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

from .board_export import (
    HEADER_FILL, MONTH_BY_INDEX, WEEKDAY_BY_INDEX, _cell_text, _rtl_right, _rtl_table,
    _set_rtl_doc, _shade,
)


def _title(day):
    try:
        d = date.fromisoformat(day)
        return (f"يومية الأفراد عن يوم {WEEKDAY_BY_INDEX[d.weekday()]} الموافق "
                f"{d.day}/{d.month}/{d.year}م — الاساسية والطارئة")
    except ValueError:
        return f"يومية الأفراد — {day}"

HEAD = ["الخدمة", "الخدمة الصباحية", "الخدمة الليلية", "قوام الخدمة", "التسليح", "الانتظام"]


def _person_text(p):
    bits = [b for b in (p.get("name"), p.get("phone")) if b]
    return " — ".join(bits) if bits else "شاغرة"


def _occasional_who(row):
    who = "، ".join(filter(None, [
        "، ".join(f"{o.get('role')}/ {o.get('name')}" if o.get("role") else o.get("name", "")
                 for o in row.get("officers") or []),
        "، ".join(f"{p.get('role')}/ {p.get('name')}" if p.get("role") else p.get("name", "")
                 for p in row.get("personnel") or []),
    ])) or "شاغرة"
    return who


def build_docx(afraad):
    document = Document()
    _set_rtl_doc(document)
    sect = document.sections[0]
    sect.orientation = WD_ORIENT.PORTRAIT
    sect.page_width, sect.page_height = Cm(21.0), Cm(29.7)
    sect.left_margin = sect.right_margin = Cm(1.2)
    sect.top_margin = sect.bottom_margin = Cm(1.2)

    style = document.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(11)

    title = document.add_paragraph()
    _rtl_right(title)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run(_title(afraad["date"]))
    run.bold = True
    run.underline = True
    run.font.size = Pt(16)
    run.font.name = "Arial"
    document.add_paragraph()

    basic, occasional = afraad["basic"], afraad["occasional"]
    total = 1 + len(basic) + (1 + len(occasional) if occasional else 0)
    tbl = document.add_table(rows=total, cols=6)
    tbl.style = "Table Grid"
    tbl.autofit = False
    _rtl_table(tbl)
    for col, w in zip(tbl.columns, [Cm(4.5), Cm(4), Cm(4), Cm(2.5), Cm(2.5), Cm(2.5)]):
        col.width = w

    r = 0
    for i, h in enumerate(HEAD):
        _shade(tbl.rows[r].cells[i], HEADER_FILL)
        _cell_text(tbl.rows[r].cells[i], h, bold=True, size=10, center=True)
    r += 1

    for row in basic:
        cells = tbl.rows[r].cells
        _cell_text(cells[0], row["name"], bold=True, size=10)
        _cell_text(cells[1], _person_text(row["morning"]), size=9.5)
        _cell_text(cells[2], _person_text(row["night"]), size=9.5)
        _cell_text(cells[3], row.get("count") or "—", size=9.5, center=True)
        _cell_text(cells[4], row.get("weapon") or "—", size=9.5, center=True)
        _cell_text(cells[5], row.get("schedule") or "—", size=9.5, center=True)
        r += 1

    if occasional:
        header_cells = tbl.rows[r].cells
        merged = header_cells[0]
        for c in header_cells[1:]:
            merged = merged.merge(c)
        _shade(merged, HEADER_FILL)
        _cell_text(merged, f"الخدمات الطارئة  ({len(occasional)})", bold=True, size=12, center=True)
        r += 1

        for row in occasional:
            cells = tbl.rows[r].cells
            _cell_text(cells[0], row.get("label") or row.get("name"), bold=True, size=10)
            who = _occasional_who(row)
            merged_who = cells[1].merge(cells[2])
            _cell_text(merged_who, who, size=9.5)
            count = row.get("conscript_count") or sum(
                (c.get("count") or 1) for c in row.get("conscripts") or [])
            _cell_text(cells[3], count or "—", size=9.5, center=True)
            _cell_text(cells[4], row.get("weapon") or "—", size=9.5, center=True)
            _cell_text(cells[5], row.get("time") or "—", size=9.5, center=True)
            r += 1

    buf = BytesIO()
    document.save(buf)
    buf.seek(0)
    return buf
