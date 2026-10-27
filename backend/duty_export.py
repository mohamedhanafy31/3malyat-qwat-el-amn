"""تصدير يومية تشغيل الضباط بصيغة أرشيف 22/9/2026 وما بعدها."""
from copy import deepcopy
from datetime import date
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.table import _Cell
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from .board_export import (WEEKDAY_BY_INDEX, normalize_document_runs, set_run_font,
                           style_tables_bold_rtl)
from .constants import (OFFICER_SECTIONS, SECTION_FORCE, SECTION_GUARDS,
                        SECTION_OUTSIDE, SECTION_SUBCAMP, SUBCAMP_SERVICES)
from .export_fit import PageFitError, docx_table_spec, estimate_table_height, usable_height_pt
from .labels import RANK_SHORT, officer_label

TEMPLATE = Path(__file__).with_name("docx_templates") / "duty_roster.docx"
LAST_FIT = {}
ROSTER_SLOTS = {SECTION_FORCE: 24, SECTION_GUARDS: 8, SECTION_OUTSIDE: 2}


def _unique_cells(row):
    seen, cells = set(), []
    for cell in row.cells:
        if id(cell._tc) not in seen:
            seen.add(id(cell._tc))
            cells.append(cell)
    return cells


def _physical_cells(row):
    """Return this row's XML cells without python-docx vertical-merge aliases."""
    return [_Cell(tc, row) for tc in row._tr.tc_lst]


def _title(day):
    d = date.fromisoformat(day)
    return (f"يومية تشغيل الضبـــاط بإدارة قـوات أمن السويس عـن يوم "
            f"{WEEKDAY_BY_INDEX[d.weekday()]}  الموافق {d.day} /{d.month}/{d.year}م")


def _rest_text(row):
    system = str(row.get("rest_system") or "").strip()
    if not system or system == "—" or (system == "أسبوعية" and not row.get("rest_day")):
        return "------------"
    if system == "أسبوعية":
        return row["rest_day"]
    return system


def _status_period_text(row):
    """صياغة الحالة الممتدة في Word؛ المفتوحة تذكر يوم البداية فقط."""
    period = row.get("persistent_status") or {}
    if row.get("status_source") != "period" or not period:
        return ""
    status = period.get("status") or row.get("status") or "خارج"
    if period.get("title") and period.get("label"):
        return period["label"]      # «مأمورية: <الاسم> — <التفاصيل> — من … حتى …»
    try:
        start = date.fromisoformat(period.get("start") or "").strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        start = period.get("start") or ""
    if not period.get("end"):
        return f"{status} من يوم {start}" if start else status
    try:
        end = date.fromisoformat(period["end"]).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        end = period["end"]
    return f"{status} من {start} حتى {end}" if start else f"{status} حتى {end}"


def _daily_text(row):
    """«التشغيل اليومي»: الخدمة التلقائية من اللوحة + التشغيل الإضافي اليدوي."""
    # الفرقة المحسوبة من سجل الالتحاق ليس لها حالة يومية مكتوبة؛ من دون
    # هذا الفرع كان ملف Word يطبع «خوارج» فقط رغم أن الشاشة تعرض الاسم
    # والمدة والمكان. التكليف الفعلي يظل أقوى من مدى الفرقة، لذلك نطبقها
    # فقط عندما كانت الخانة النهائية نفسها «خوارج/فرقة».
    if (row.get("group"), row.get("bucket")) == ("خوارج", "فرقة") and row.get("course"):
        from .duty import course_with_note
        return course_with_note(row["course"], row.get("text"))
    period_text = _status_period_text(row)
    if period_text:
        return period_text
    if row.get("text"):
        return row["text"]
    if row.get("leave"):
        return row["leave"].get("type") or "راحة"
    return row.get("status") or row.get("group") or "عمل"


def _grouped_rows(rows):
    by_section = {}
    for row in rows:
        by_section.setdefault(row.get("section") or SECTION_FORCE, []).append(row)
    return [(section, by_section.get(section, [])) for section in OFFICER_SECTIONS]


def _write_cell(cell, text, *, bold=False, size=9, center=False):
    """Replace text while retaining the archive cell's run/font properties."""
    old_run = next((run for paragraph in cell.paragraphs for run in paragraph.runs), None)
    rpr = deepcopy(old_run._r.rPr) if old_run is not None and old_run._r.rPr is not None else None
    paragraph = cell.paragraphs[0]
    for extra in cell.paragraphs[1:]:
        cell._tc.remove(extra._p)
    for child in list(paragraph._p):
        if child.tag != qn("w:pPr"):
            paragraph._p.remove(child)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER if center else WD_ALIGN_PARAGRAPH.RIGHT
    ppr = paragraph._p.get_or_add_pPr()
    if ppr.find(qn("w:bidi")) is None:
        ppr.append(OxmlElement("w:bidi"))
    if text is None or text == "":
        return
    run = paragraph.add_run(str(text))
    if rpr is not None:
        run._r.insert(0, deepcopy(rpr))
    set_run_font(run, "Arial", size, bold)


def _summary_values(summary):
    external, internal = summary["خارجية"], summary["داخلية"]
    medical, outside = summary["طبية"], summary["خوارج"]
    morning = str(external["صباحية"])
    if external.get("بحث"):
        morning += f"+ {external['بحث']} بحث"
    fixed_outside = {"تقصيرة", "راحة", "طارئة", "غياب", "مرضي", "فرقة", "انتداب"}
    other_emergency = sum(value for key, value in outside.items() if key not in fixed_outside)
    return [summary["أصل القوة"], morning, external["ليلية"], internal["صباحية"],
            internal["ليلية"], medical["موجود"], medical["راحة"], outside["تقصيرة"],
            outside["راحة"], outside["طارئة"] + other_emergency, outside["غياب"], outside["مرضي"],
            outside["فرقة"], outside["انتداب"], summary["حراسات"], ""]


def _sparse_summary(rows):
    subcamp = 0
    deputed = False
    for row in rows:
        services = row.get("services") or []
        if any(service.get("name") in SUBCAMP_SERVICES or
               service.get("section") == SECTION_SUBCAMP for service in services):
            subcamp += 1
        deputed = deputed or row.get("status") == "انتداب"
    return (f"{subcamp} معسكر فرعي" if subcamp else ""), ("منتدب" if deputed else "")


def _fill_summary(table, summary, rows):
    header, names_row, total, sparse = (_physical_cells(table.rows[index]) for index in range(4))
    for index, value in enumerate(_summary_values(summary)):
        _write_cell(total[index], value, bold=index == 0, size=8, center=True)
    names = "\n".join(officer_label(row, full=False) for row in rows if row.get("group") == "صافي")
    _write_cell(names_row[15], names, size=6, center=True)
    _write_cell(header[6], "الصافي", bold=True, size=8, center=True)
    subcamp, deputed = _sparse_summary(rows)
    for index in range(len(sparse)):
        _write_cell(sparse[index], subcamp if index == 3 else deputed if index == 4 else "",
                    size=7, center=True)


def _fit_measure(document):
    roster, summary = document.tables[:2]
    roster_rows, roster_widths = docx_table_spec(roster, 9)
    summary_rows, summary_widths = docx_table_spec(summary, 8)
    usable = usable_height_pt(document.sections[0])
    roster_height = estimate_table_height(roster_rows, roster_widths)[0]
    summary_height = estimate_table_height(summary_rows, summary_widths)[0]
    ratio = (roster_height + summary_height) / usable
    scale = 1.0
    while ratio > .94 and scale >= .54:
        scale = round(scale - .02, 2)
        rscaled = [[{**cell, "size_pt": max(3.5, cell.get("size_pt", 9) * scale)
                     } for cell in row] for row in roster_rows]
        sscaled = [[{**cell, "size_pt": max(3.5, cell.get("size_pt", 8) * scale)
                     } for cell in row] for row in summary_rows]
        ratio = (estimate_table_height(rscaled, roster_widths)[0]
                 + estimate_table_height(sscaled, summary_widths)[0]) / usable
    if ratio > .94:
        raise PageFitError("تعذر احتواء يومية الضباط في صفحة واحدة")
    # Cell runs inherited from the archive contain a few smaller role-specific
    # sizes, while newly written cells use the role's base size. Leave margin
    # for that difference so the final serialized DOCX stays under the gate.
    scale = max(.55, round(scale - .10, 2))
    LAST_FIT.clear()
    LAST_FIT.update(scale=scale, ratio=ratio, total_pt=ratio * usable,
                    usable_pt=usable)
    return scale


def _scale_runs(document, scale):
    if scale >= 1:
        return
    for paragraph in document.paragraphs:
        for run in paragraph.runs:
            size = run.font.size.pt if run.font.size else 9
            set_run_font(run, "Arial", max(3.5, size * scale), bool(run.bold))
    for table in document.tables:
        for row in table.rows:
            for cell in _unique_cells(row):
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        size = run.font.size.pt if run.font.size else 9
                        set_run_font(run, "Arial", max(3.5, size * scale), bool(run.bold))


def build_docx(duty):
    document = Document(TEMPLATE)
    for paragraph in document.paragraphs:
        if "يومية تشغيل الضب" in paragraph.text:
            paragraph.text = ""
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            set_run_font(paragraph.add_run(_title(duty["date"])), "Arial", 11, True)
            break

    table = document.tables[0]
    grouped = dict(_grouped_rows(duty["rows"]))
    number = 0
    for section in OFFICER_SECTIONS:
        if section != SECTION_FORCE:
            section_row = table.rows[25 if section == SECTION_GUARDS else 34]
            label = ("الحراسات المشددة" if section == SECTION_GUARDS
                     else "الخــــــــــــــــــــــــــوارج")
            _write_cell(_unique_cells(section_row)[0], label, bold=True, size=9, center=True)
        for offset in range(ROSTER_SLOTS[section]):
            item = grouped.get(section, [])[offset] if offset < len(grouped.get(section, [])) else None
            row_index = offset + (1 if section == SECTION_FORCE else
                                  26 if section == SECTION_GUARDS else 35)
            cells = _unique_cells(table.rows[row_index])
            number += 1
            values = [f"{number}-", "", "", "", "", ""]
            if item:
                values = [f"{number}-", RANK_SHORT.get(item.get("role"), item.get("role") or ""),
                          item.get("name") or "", item.get("post") or "", _daily_text(item),
                          _rest_text(item)]
            for index, value in enumerate(values):
                _write_cell(cells[index], value, bold=index == 2, size=9,
                            center=index in (0, 1, 5))

    _fill_summary(document.tables[1], duty["summary"], duty["rows"])
    style_tables_bold_rtl(document)          # العرض بيتقاس وهو bold
    _scale_runs(document, _fit_measure(document))
    normalize_document_runs(document)
    buf = BytesIO()
    document.save(buf)
    buf.seek(0)
    return buf
