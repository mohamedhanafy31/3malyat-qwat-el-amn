"""تصدير يومية الأفراد كملف Word حقيقي — نفس شكل ورقة «افراد» الحقيقية:
جدول واحد متواصل، الأساسية أول (الخدمة/الصباحية/الليلية/القوام/التسليح/
الانتظام)، وتحتها صف عنوان «الخدمات الطارئة» ممتد على العرض وبعده صفوف
الطوارئ (+ أي قسم مخصّص) بنفس الأعمدة. بيستخدم نفس أدوات RTL/الحدود
اللي `board_export.py` بنى بيها ملف الضباط، عشان الاتنين يفضلوا بنفس
الشكل بالظبط."""
from copy import deepcopy
from datetime import date
from io import BytesIO
from pathlib import Path

from docx import Document

from .board_export import WEEKDAY_BY_INDEX, _cell_text


TEMPLATE = Path(__file__).with_name("docx_templates") / "afraad_roster.docx"


def _title(day):
    try:
        d = date.fromisoformat(day)
        return (f"يومية الخدمات عن يوم {WEEKDAY_BY_INDEX[d.weekday()]} "
                f"{d.day}/{d.month}/{d.year}م خدمات الاساسية والطارئة")
    except ValueError:
        return f"يومية الأفراد — {day}"

def _person_text(p):
    bits = [b for b in (p.get("name"), p.get("phone")) if b]
    return "\n".join(bits) if bits else "ـــــــــــــــــــــــــــــ"


def _occasional_who(row):
    who = "، ".join(filter(None, [
        "، ".join(f"{o.get('role')}/ {o.get('name')}" if o.get("role") else o.get("name", "")
                 for o in row.get("officers") or []),
        "، ".join(f"{p.get('role')}/ {p.get('name')}" if p.get("role") else p.get("name", "")
                 for p in row.get("personnel") or []),
    ])) or "ـــــــــــــــــ"
    return who


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


def _strength(row):
    value = row.get("count")
    return str(value).strip() if value else "ــــــــ"


def _occasional_count(row):
    count = row.get("conscript_count")
    if not count:
        count = sum((entry.get("count") or 0) for entry in row.get("conscripts") or [])
    return count or "ــــــــ"


def _occasional_weapon(row):
    if row.get("weapon"):
        return row["weapon"]
    classes = [entry.get("class", "").strip() for entry in row.get("conscripts") or []]
    return " + ".join(dict.fromkeys(value for value in classes if value)) or "ــــــــ"


def _occasional_time(row):
    value = str(row.get("time") or "").strip()
    party = str(row.get("party") or "").strip()
    if party and party not in value:
        value = f'{value} "{party}"'.strip()
    return value or "ــــــــ"


def build_docx(afraad):
    document = Document(TEMPLATE)
    for paragraph in document.paragraphs:
        if "يومية الخدمات" in paragraph.text:
            _replace_paragraph(paragraph, _title(afraad["date"]))
            break
    table = document.tables[0]
    basic, occasional = afraad["basic"], afraad["occasional"]
    regular_basic_proto = deepcopy(table.rows[1]._tr)
    split_basic_proto = deepcopy(table.rows[8]._tr)
    emergency_heading_proto = deepcopy(table.rows[22]._tr)
    occasional_proto = deepcopy(table.rows[24]._tr)
    for row in list(table.rows[1:]):
        table._tbl.remove(row._tr)

    # Rebuild the basic block so a newly configured fixed service is exported
    # instead of being silently dropped. The 109 checkpoint keeps the source
    # form's split service/sub-service columns.
    for row in basic:
        split = row["name"].startswith("كمين 109 -")
        table._tbl.append(deepcopy(split_basic_proto if split else regular_basic_proto))
        cells = _unique_cells(table.rows[-1])
        name = row["name"]
        if split:
            parent, _, child = name.partition(" - ")
            values = ["", parent, child or "—", _person_text(row["morning"]),
                      _person_text(row["night"]), _strength(row),
                      row.get("weapon") or "ــــــــ", row.get("schedule") or "ــــــــ"]
        else:
            values = ["", name, _person_text(row["morning"]), _person_text(row["night"]),
                      _strength(row), row.get("weapon") or "ــــــــ",
                      row.get("schedule") or "ــــــــ"]
        for cell, value in zip(cells, values):
            _cell_text(cell, value, bold=False, size=6.5, center=True)

    # Preserve the merged emergency heading, then rebuild its rows from today's data.
    table._tbl.append(deepcopy(emergency_heading_proto))
    _cell_text(_unique_cells(table.rows[-1])[0], "الخدمـــــــــــات الطارئــــــــــــــــــــــــــة",
               bold=True, size=8, center=True)
    for row in occasional:
        table._tbl.append(deepcopy(occasional_proto))
        cells = _unique_cells(table.rows[-1])
        values = [row.get("label") or row.get("name") or "—", _occasional_who(row),
                  _occasional_count(row), _occasional_weapon(row), _occasional_time(row)]
        for index, (cell, value) in enumerate(zip(cells, values)):
            _cell_text(cell, value, bold=index == 0, size=6.5, center=True)

    buf = BytesIO()
    document.save(buf)
    buf.seek(0)
    return buf
