"""تصدير يومية الأفراد بصيغة أرشيف 28-9-2026 الثابتة."""
from copy import deepcopy
from datetime import date
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.shared import Pt

from .afraad import BASIC_SERVICE_NAMES, emergency_horizontal_pairs
from .board_export import (WEEKDAY_BY_INDEX, _cell_text, normalize_document_runs,
                           set_run_font, style_tables_bold_rtl)
from .export_fit import apply_fit_to_docx_table, docx_table_spec, fit_table, usable_height_pt
from .labels import officer_label, personnel_label


TEMPLATE = Path(__file__).with_name("docx_templates") / "afraad_roster.docx"
LAST_FIT = {}
EMPTY_BASIC = "ــــــــــــ"
EMPTY_VALUE = "ــــــــ"
ARCHIVE_BASIC_FONT = "Times New Roman"
ARCHIVE_EMERGENCY_FONT = "Bahnschrift SemiBold"


def _title(day):
    try:
        d = date.fromisoformat(day)
        return (f"يومية الخدمات عن يوم {WEEKDAY_BY_INDEX[d.weekday()]} "
                f"{d.day}/{d.month}/{d.year}م خدمات الاساسية والطارئة")
    except ValueError:
        return f"يومية الأفراد — {day}"


def _person_text(person):
    person = person or {}
    if person.get("person_id"):
        who = {**person, "name": person.get("full_name") or person.get("name", "")}
        name = personnel_label(who) if person.get("role") else person.get("name", "")
    else:
        name = person.get("name", "")
    bits = [name]
    if person.get("phone"):
        bits.append(str(person["phone"]))
    return "\n".join(bits) if any(bits) else EMPTY_BASIC


def _emergency_person(person):
    person = person or {}
    if person.get("category") == "officers":
        return officer_label(person)
    if person.get("person_id") or person.get("role"):
        value = personnel_label(person)
        if person.get("phone"):
            value += "\n" + str(person["phone"])
        return value
    return str(person.get("name") or "")


def _occasional_who(row):
    people = [officer_label(o) for o in row.get("officers") or []]
    people.extend(_emergency_person(p) for p in row.get("personnel") or [])
    value = "، ".join(item for item in people if item)
    return value or EMPTY_BASIC


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


def _set_empty(cell):
    cell.text = ""


def _write(cell, value, *, size, bold=False, font=ARCHIVE_BASIC_FONT, empty=EMPTY_VALUE):
    value = str(value) if value not in (None, "") else empty
    _cell_text(cell, value, bold=bold, size=size, center=True)
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            set_run_font(run, font, size, bold)


def _literal(value, empty=EMPTY_VALUE):
    return str(value) if value not in (None, "") else empty


def _strength(row):
    return _literal(row.get("count"))


def _occasional_count(row):
    count = row.get("conscript_count")
    if not count:
        count = sum((entry.get("count") or 0) for entry in row.get("conscripts") or [])
    return count or EMPTY_VALUE


def _occasional_weapon(row):
    if row.get("weapon"):
        return row["weapon"]
    classes = [entry.get("class", "") for entry in row.get("conscripts") or []]
    return " + ".join(dict.fromkeys(value for value in classes if value)) or EMPTY_VALUE


def _occasional_time(row):
    value = str(row.get("time") or "")
    party = str(row.get("party") or "")
    if party and party not in value:
        value = f'{value} "{party}"'.strip()
    return value or EMPTY_VALUE


def _basic_values(row):
    name = str(row.get("name") or "")
    split = name.startswith("كمين 109 -")
    if split:
        parent, _, child = name.partition(" - ")
        return ["", parent, child or EMPTY_VALUE, _person_text(row.get("morning")),
                _person_text(row.get("night")), _strength(row),
                _literal(row.get("weapon")), _literal(row.get("schedule"))]
    return ["", name, _person_text(row.get("morning")), _person_text(row.get("night")),
            _strength(row), _literal(row.get("weapon")), _literal(row.get("schedule"))]


def _export_basic_rows(rows):
    if rows:
        normalized = []
        for row in rows:
            value = dict(row)
            name = " ".join(str(value.get("name") or "").split())
            if name == "كمين 109":
                value["name"] = "كمين 109 - بيك اب"
            elif name == "مدرعة" and normalized:
                previous = str(normalized[-1].get("name") or "")
                if previous.startswith("كمين 109 -"):
                    value["name"] = "كمين 109 - مدرعة"
            normalized.append(value)
        return normalized
    return [{"name": name, "morning": {}, "night": {}, "count": "", "weapon": "",
             "schedule": ""} for name in BASIC_SERVICE_NAMES]


def _write_basic_row(row, values):
    for index, (cell, value) in enumerate(zip(_unique_cells(row), values)):
        if index == 0:
            _set_empty(cell)
            continue
        size = 8 if index == 1 else (6 if index == 5 else 7)
        _write(cell, value, size=size, bold=True)


def _horizontal_values(pair_group):
    values = []
    for pair in pair_group:
        values.extend([pair.get("label") or pair.get("name") or EMPTY_VALUE,
                       pair.get("person") or pair.get("who") or EMPTY_VALUE])
    return values


def _write_emergency_row(row, values):
    for cell, value in zip(_unique_cells(row), values):
        _write(cell, value, size=7, bold=False, font=ARCHIVE_EMERGENCY_FONT)


def build_docx(afraad):
    document = Document(TEMPLATE)
    for paragraph in document.paragraphs:
        if "يومية الخدمات" in paragraph.text:
            _replace_paragraph(paragraph, _title(afraad["date"]))
            break

    table = document.tables[0]
    regular_proto = deepcopy(table.rows[1]._tr)
    split_proto = deepcopy(table.rows[8]._tr)
    heading_proto = deepcopy(table.rows[22]._tr)
    horizontal_proto = deepcopy(table.rows[23]._tr)
    emergency_proto = deepcopy(table.rows[24]._tr)
    for row in list(table.rows[1:]):
        table._tbl.remove(row._tr)

    for basic in _export_basic_rows(afraad.get("basic")):
        prototype = split_proto if basic.get("name", "").startswith("كمين 109 -") else regular_proto
        table._tbl.append(deepcopy(prototype))
        _write_basic_row(table.rows[-1], _basic_values(basic))

    table._tbl.append(deepcopy(heading_proto))
    _write(table.rows[-1].cells[0], "الخدمـــــــــــات الطارئــــــــــــــــــــــــــة",
           size=8, bold=True)

    officer_pairs = afraad.get("officer_pairs") or []
    for start in range(0, len(officer_pairs), 3):
        table._tbl.append(deepcopy(horizontal_proto))
        values = _horizontal_values(officer_pairs[start:start + 3])
        values += [EMPTY_VALUE] * (6 - len(values))
        _write_emergency_row(table.rows[-1], values)

    for source in afraad.get("occasional") or []:
        pairs = emergency_horizontal_pairs(source)
        if len(pairs) > 1:
            for start in range(0, len(pairs), 3):
                table._tbl.append(deepcopy(horizontal_proto))
                values = _horizontal_values(pairs[start:start + 3])
                values += [EMPTY_VALUE] * (6 - len(values))
                _write_emergency_row(table.rows[-1], values)
            continue
        table._tbl.append(deepcopy(emergency_proto))
        values = [source.get("label") or source.get("name") or EMPTY_VALUE,
                  _occasional_who(source), _occasional_count(source),
                  _occasional_weapon(source), _occasional_time(source)]
        _write_emergency_row(table.rows[-1], values)

    style_tables_bold_rtl(document)          # العرض بيتقاس وهو bold
    rows, widths = docx_table_spec(table, 8)
    fit = fit_table({"rows": rows, "grid_widths_pt": widths},
                    usable_height_pt(document.sections[0]))
    apply_fit_to_docx_table(table, fit)
    tail = document.add_paragraph()
    tail.paragraph_format.space_before = Pt(0)
    tail.paragraph_format.space_after = Pt(0)
    set_run_font(tail.add_run(), ARCHIVE_BASIC_FONT, 1, False)
    normalize_document_runs(document)
    LAST_FIT.clear()
    LAST_FIT.update(scale=fit.scale, ratio=fit.ratio, total_pt=fit.total_pt,
                    usable_pt=fit.usable_pt)

    buf = BytesIO()
    document.save(buf)
    buf.seek(0)
    return buf
