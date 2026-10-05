"""Word export for the officers' daily roster using the approved 30-8-2026 layout."""
from copy import deepcopy
from datetime import date
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.enum.table import WD_ROW_HEIGHT_RULE
from docx.shared import Pt

from .board_export import WEEKDAY_BY_INDEX, _cell_text
from .constants import OFFICER_SECTIONS, SECTION_FORCE, SECTION_GUARDS, SECTION_OUTSIDE


TEMPLATE = Path(__file__).with_name("docx_templates") / "duty_roster.docx"
RANK_SHORT = {"ملازم أول": "م.اول", "ملازم": "ملازم"}


def _unique_cells(row):
    seen, cells = set(), []
    for cell in row.cells:
        key = id(cell._tc)
        if key not in seen:
            seen.add(key)
            cells.append(cell)
    return cells


def _replace_paragraph(paragraph, text):
    runs = list(paragraph.runs)
    if not runs:
        paragraph.add_run(text)
        return
    target = next((run for run in runs if run.text.strip()), runs[0])
    for run in runs:
        run.text = ""
    target.text = text


def _title(day):
    d = date.fromisoformat(day)
    return (f"يومية تشغيل الضبـــاط بإدارة قـوات أمن السويس عـن يوم "
            f"{WEEKDAY_BY_INDEX[d.weekday()]} الموافق {d.day}/{d.month}/{d.year}م")


def _rest_text(row):
    system = str(row.get("rest_system") or "").strip()
    if not system or system == "—":
        return "------------"
    if system == "أسبوعية" and row.get("rest_day"):
        return row["rest_day"]
    return system


def _daily_text(row):
    if row.get("note"):
        return row["note"]
    parts = []
    for service in row.get("services") or []:
        text = service.get("name", "")
        if service.get("shift"):
            text += f" فترة {service['shift']}"
        if text:
            parts.append(text)
    if parts:
        return " + ".join(parts)
    if row.get("leave"):
        return row["leave"].get("type") or "راحة"
    return row.get("status") or row.get("group") or "عمل"


def _grouped_rows(rows):
    order = list(OFFICER_SECTIONS)
    known = set(order)
    order.extend(section for section in dict.fromkeys(
        (row.get("section") or SECTION_FORCE) for row in rows) if section not in known)
    return [(section, [row for row in rows if (row.get("section") or SECTION_FORCE) == section])
            for section in order]


def _compact_row(row, height):
    """Keep the original one-page roster density even when cell text wraps."""
    row.height = Pt(height)
    row.height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
    for cell in _unique_cells(row):
        tc_pr = cell._tc.get_or_add_tcPr()
        margins = tc_pr.first_child_found_in("w:tcMar")
        if margins is not None:
            for edge in margins:
                edge.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}w", "18")


def _fill_summary(table, summary):
    external, internal = summary["خارجية"], summary["داخلية"]
    medical, outside = summary["طبية"], summary["خوارج"]
    morning = str(external["صباحية"])
    if external.get("بحث"):
        morning += f" + {external['بحث']} بحث"
    values = [summary["أصل القوة"], morning, external["ليلية"],
              internal["صباحية"], internal["ليلية"], medical["موجود"], medical["راحة"],
              outside["تقصيرة"], outside["راحة"], outside["طارئة"], outside["غياب"],
              outside["مرضي"], outside["فرقة"], outside["انتداب"], summary["حراسات"],
              "\n".join(summary.get("net_names") or []) or "—"]
    # The source template intentionally floats this compact summary above the
    # first roster rows. Exact heights stop long names from pushing it down and
    # moving the roster onto a second page in Word/LibreOffice.
    for row, height in zip(table.rows, (26.5, 22.8, 12.5, 12.5)):
        _compact_row(row, height)
    _cell_text(table.rows[0].cells[15], f"الصافي ({summary['صافي']})", bold=True,
               size=6.0, center=True)
    for row_index in (2, 3):
        for index, value in enumerate(values):
            _cell_text(table.rows[row_index].cells[index], value, bold=index in (0, 15),
                       size=4.0 if index == 15 else 5.5, center=True)
    _cell_text(table.rows[1].cells[15], values[15], size=4.0, center=True)


def build_docx(duty):
    document = Document(TEMPLATE)
    for paragraph in document.paragraphs:
        if "يومية تشغيل الضب" in paragraph.text:
            _replace_paragraph(paragraph, _title(duty["date"]))
            break

    table = document.tables[0]
    officer_proto = deepcopy(table.rows[1]._tr)
    section_proto = deepcopy(table.rows[25]._tr)
    for row in list(table.rows[1:]):
        table._tbl.remove(row._tr)

    number = 0
    for section, rows in _grouped_rows(duty["rows"]):
        if not rows:
            continue
        if section != SECTION_FORCE:
            table._tbl.append(deepcopy(section_proto))
            _compact_row(table.rows[-1], 9)
            label = "الحراسات المشددة" if section == SECTION_GUARDS else (
                "الخوارج" if section == SECTION_OUTSIDE else section)
            _cell_text(_unique_cells(table.rows[-1])[0], label, bold=True, size=6.2, center=True)
        for item in rows:
            number += 1
            table._tbl.append(deepcopy(officer_proto))
            _compact_row(table.rows[-1], 13)
            cells = _unique_cells(table.rows[-1])
            values = [f"{number}-", RANK_SHORT.get(item.get("role"), item.get("role") or "—"),
                      item.get("name") or "—", item.get("post") or "—",
                      _daily_text(item), _rest_text(item)]
            for index, (cell, value) in enumerate(zip(cells, values)):
                _cell_text(cell, value, bold=index == 2, size=5.25, center=index in (0, 1, 5))

    _fill_summary(document.tables[1], duty["summary"])
    buf = BytesIO()
    document.save(buf)
    buf.seek(0)
    return buf
