"""محرك كشوف Word العامة لسجلات المنظومة."""
from datetime import date
from io import BytesIO

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from . import people_export as people
from .export_fit import fit_widths


def register_file_name(label, day=None):
    value = date.fromisoformat(day) if day else date.today()
    return f"{label} {value.day:02d}-{value.month:02d}-{value.year}.docx"


def _add(parent, tag, **attrs):
    node = OxmlElement(tag)
    for key, value in attrs.items():
        node.set(qn(f"w:{key}"), str(value))
    parent.append(node)
    return node


def _set_cell(cell, text, *, ltr=False, header=False):
    cell.text = ""
    for index, line in enumerate(str(text or "").split("\n")):
        paragraph = cell.paragraphs[0] if index == 0 else cell.add_paragraph()
        people._paragraph(paragraph, align=WD_ALIGN_PARAGRAPH.CENTER)
        people._run_font(paragraph.add_run(line), 9, bold=header,
                         font=people.HEADING_FONT if header else people.BODY_FONT,
                         ltr=ltr)
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER


def _landscape(weights):
    if len(weights) > 7:
        return True
    # نسب عرض شديدة تمنع الأعمدة من الانكماش بدرجة معقولة في الوضع الرأسي.
    return bool(weights and max(weights) / max(1, min(weights)) > 8 and len(weights) > 5)


def build_register_docx(title, columns, rows, *, subtitle="", footer_note="",
                         orientation="auto", ltr_columns=()):
    columns = list(columns)
    rows = [list(row) for row in rows]
    if not columns:
        raise ValueError("لازم الكشف يحتوي على عمود واحد على الأقل.")
    if any(len(row) != len(columns) for row in rows):
        raise ValueError("عدد قيم الصف لازم يساوي عدد الأعمدة.")
    weights = [max(0.01, float(weight)) for _name, weight in columns]
    landscape = orientation == "landscape" or (orientation == "auto" and _landscape(weights))
    document = Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE if landscape else WD_ORIENT.PORTRAIT
    section.page_width, section.page_height = ((Cm(29.7), Cm(21)) if landscape
                                                else (Cm(21), Cm(29.7)))
    section.left_margin = section.right_margin = Cm(.8)
    section.top_margin, section.bottom_margin = Cm(1.1), Cm(1.2)
    sectpr = section._sectPr
    if sectpr.find(qn("w:bidi")) is None:
        people._insert_before(sectpr, OxmlElement("w:bidi"),
                              ("rtlGutter", "docGrid", "printerSettings", "sectPrChange"))
    heading = document.add_paragraph()
    people._paragraph(heading)
    people._run_font(heading.add_run(title), 14, bold=True, font=people.HEADING_FONT)
    if subtitle:
        p = document.add_paragraph()
        people._paragraph(p)
        people._run_font(p.add_run(subtitle), 10, bold=True, font=people.HEADING_FONT)

    all_columns = [("م", .6), *columns]
    usable_cm = section.page_width.cm - section.left_margin.cm - section.right_margin.cm
    total = sum(weight for _name, weight in all_columns)
    usable_pt = usable_cm * 28.3464567
    needs_pt = [usable_pt * weight / total for _name, weight in all_columns]
    widths = [width / 28.3464567 for width in
              fit_widths(needs_pt, [(1, usable_pt)] * len(needs_pt), usable_pt)]
    table = document.add_table(rows=1, cols=len(all_columns))
    people._table_setup(table, widths)
    people._table_borders(table)
    for col, width in zip(table.columns, widths):
        for cell in col.cells:
            cell.width = Cm(width)
    header = table.rows[0]
    _add(header._tr.get_or_add_trPr(), "w:tblHeader")
    people._row_height(header, .7, "atLeast")
    for cell, (label, _weight) in zip(header.cells, all_columns):
        _set_cell(cell, label, header=True)
        people._cell_borders(cell, size=12, value="double", sides=("bottom",))
        tcpr = cell._tc.get_or_add_tcPr()
        _add(tcpr, "w:shd", fill="D9E2F3", val="clear")
    if not rows:
        rows = [["لا توجد بيانات"] + [""] * (len(columns) - 1)]
    for serial, values in enumerate(rows, 1):
        row = table.add_row()
        people._row_height(row, .6)
        vals = [str(serial), *[str(value or "") for value in values]]
        for index, (cell, value) in enumerate(zip(row.cells, vals)):
            _set_cell(cell, value, ltr=(index - 1) in ltr_columns and index > 0)
    footer = section.footer.paragraphs[0]
    people._paragraph(footer)
    note = footer_note or "تاريخ التصدير: " + date.today().strftime("%d-%m-%Y")
    people._run_font(footer.add_run(note), 8)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()
