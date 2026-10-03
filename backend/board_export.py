"""تصدير اليومية التفصيلية كملف Word حقيقي (.docx) — نفس شكل الورقة
الرسمية اللي بتتكتب بالإيد بالظبط (عنوان غليظ تحته خط، وجدول واحد
متواصل بعمودين: يمين الخدمات، شمال الأهداف/الراحات/الكتل الثابتة —
مش كروت منفصلة بفراغات بينها)، مبني من نفس البيانات اللي بتتعرض في
`/board` (`build_board`). هيكل الملف اتاخد حرفيًا من فحص عيّنة حقيقية
(`2026/6/3/3.docx`): جدول واحد أربعة أعمدة — العمودين اليمين لقسم واحد
شغّال في كل لحظة (الخدمات)، والعمودين الشمال لقسم تاني (الأهداف وما
بعدها) — كل نصّ بيتقدّم لوحده وياخد صف عنوان جديد لما قسمه يخلص، من غير
ما يستنى القسم التاني.

القسم بيتحدد نوعه من `sec["type"]` بالظبط زي `sectionCard()` في
`static/js/board.js` — نفس منطق العرض، لغة تانية.
"""
from datetime import date
from io import BytesIO

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from .constants import (
    SECTION_ADMIN_WORK, SECTION_BASIC, SECTION_OCCASIONAL, SECTION_OUTSIDERS,
    SECTION_PRISON, SECTION_RESTS, SECTION_SECURITY, SECTION_GREAT, SECTION_SUBCAMP,
    SECTION_TARGETS, SECTION_TAQSEERA,
)

WEEKDAY_BY_INDEX = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
MONTH_BY_INDEX = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
                  "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]

RIGHT_COLUMN_SECTIONS = {SECTION_BASIC, SECTION_TARGETS, SECTION_SUBCAMP, SECTION_ADMIN_WORK}
# الأقسام اللي موضوعها الأساسي «ضابط» (كل صف = ضابط) — اسم الضابط بييجي
# أول عمود (يمين نصفه)، والوصف بعده. عكس أقسام الخدمات/الأهداف/الكتل
# اللي موضوعها الأساسي «خدمة» فاسمها هو اللي بييجي أول عمود.
OFFICER_CENTRIC = {SECTION_ADMIN_WORK, SECTION_RESTS, SECTION_TAQSEERA, SECTION_OUTSIDERS}

HEADER_FILL = "E9E9E9"


def _day_title(day):
    try:
        d = date.fromisoformat(day)
        return f"الخدمات عن يوم {WEEKDAY_BY_INDEX[d.weekday()]} الموافق {d.day}/{d.month}/{d.year}م"
    except ValueError:
        return day


def _fmt_date(iso):
    try:
        d = date.fromisoformat(iso)
        return f"{d.day}/{d.month}"
    except (TypeError, ValueError):
        return iso or ""


def _who(person):
    role, name = (person or {}).get("role", ""), (person or {}).get("name", "")
    return f"{role}/ {name}" if role else (name or "")


def _people_text(people):
    return "، ".join(_who(p) for p in (people or []) if p) or ""


def _set_rtl_doc(document):
    for sect in document.sections:
        sect._sectPr.append(OxmlElement("w:bidi"))


def _rtl_table(table):
    """بيقلب ترتيب أعمدة الجدول بصريًا — أول عمود بيتحط بيظهر يمين، زي
    صفحة الويب بالظبط (`direction:rtl`)."""
    table._tbl.tblPr.append(OxmlElement("w:bidiVisual"))


def _rtl_right(paragraph):
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    paragraph._p.get_or_add_pPr().append(OxmlElement("w:bidi"))


def _shade(cell, hex_color):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def _cell_text(cell, text, bold=False, size=11, center=False):
    cell.text = ""
    p = cell.paragraphs[0]
    _rtl_right(p)
    if center:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(str(text) if text not in (None, "") else "—")
    run.bold = bold
    run.font.size = Pt(size)
    run.font.name = "Arial"
    rFonts = run._r.get_or_add_rPr().find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        run._r.get_or_add_rPr().append(rFonts)
    rFonts.set(qn("w:cs"), "Arial")


def _service_desc(row):
    """كل تفاصيل الخدمة في خانة واحدة حرة — نفس أسلوب الورقة الرسمية
    («مج +فرد»، «فرد + مج») بدل أعمدة منفصلة لكل تفصيلة."""
    bits = []
    who = "، ".join(filter(None, [_people_text(row.get("officers")), _people_text(row.get("personnel"))]))
    if who:
        bits.append(who)
    for c in row.get("conscripts") or []:
        cls = c.get("class") or "مجند"
        bits.append(f"{cls} ×{c['count']}" if c.get("count") else cls)
    if row.get("conscript_count"):
        bits.append(f"مج ×{row['conscript_count']}")
    for extra in ("weapon", "time", "party", "note"):
        if row.get(extra):
            bits.append(row[extra])
    return " + ".join(bits) if bits else "شاغرة"


def _officer_desc(section_name, row):
    if section_name == SECTION_ADMIN_WORK:
        if row.get("fixedSection"):
            return _people_text(row.get("officers")) or "—"
        return row.get("text") or "—"
    if section_name == SECTION_OUTSIDERS:
        return row.get("detail") or row.get("reason") or "—"
    if section_name == SECTION_RESTS:
        span = " → ".join(filter(None, [_fmt_date(row.get("start")), _fmt_date(row.get("end"))]))
        return f"{row.get('type') or 'راحة'} ({span})" if span else (row.get("type") or "راحة")
    if section_name == SECTION_TAQSEERA:
        return row.get("note") or "تقصيرة"
    return "—"


def _presentation_sections(sections):
    by_name = {section["name"]: section for section in sections}
    admin = by_name.get(SECTION_ADMIN_WORK, {"name": SECTION_ADMIN_WORK, "type": "admin", "rows": []})
    admin_rows = list(admin.get("rows") or [])
    for name in (SECTION_GREAT, SECTION_SECURITY):
        source = by_name.get(name)
        for row in source.get("rows", []) if source else []:
            admin_rows.append({**row, "fixedSection": name, "fixedLabel": name})
    outsiders = []
    for name in (SECTION_RESTS, SECTION_TAQSEERA, SECTION_OUTSIDERS):
        source = by_name.get(name)
        for row in source.get("rows", []) if source else []:
            if name == SECTION_RESTS:
                detail = row.get("type") or "راحة"
                status_type = "راحة"
            elif name == SECTION_TAQSEERA:
                detail = row.get("note") or "تقصيرة"
                status_type = "تقصيرة"
            else:
                detail = row.get("note") or row.get("reason") or ""
                status_type = row.get("reason") or "خارج"
            outsiders.append({**row, "status_type": status_type, "detail": detail})
    hidden = {SECTION_ADMIN_WORK, SECTION_GREAT, SECTION_SECURITY,
              SECTION_RESTS, SECTION_TAQSEERA, SECTION_OUTSIDERS}
    out = [section for section in sections if section["name"] not in hidden]
    out.extend([
        {"name": SECTION_ADMIN_WORK, "type": "admin", "rows": admin_rows},
        {"name": SECTION_OUTSIDERS, "type": "officers", "rows": outsiders},
    ])
    return out


def _section_blocks(sec):
    """قسم واحد -> [(is_header, نص_يمين, نص_شمال), ...] — صف عنوان واحد
    ممتد على العمودين، وبعده صف لكل عنصر (أو «لا يوجد» لو فاضي)."""
    name, sec_type = sec["name"], sec["type"]
    rows = list(sec.get("rows") or [])

    out = [(True, f"{name}  ({len(rows)})", None)]

    if sec_type in {"officers", "admin"}:
        for r in rows:
            out.append((False, _who(r) or "—", _officer_desc(name, r)))
    elif sec_type == "targets":
        for r in rows:
            person = _people_text(r.get("officers")) or _people_text(r.get("commander")) or "—"
            out.append((False, r.get("label") or r.get("name"), person))
    elif sec_type == "slots":
        for r in rows:
            if r.get("slot"):
                out.append((False, r.get("shift"), _people_text(r.get("officers")) or "—"))
            else:
                out.append((False, r.get("label") or r.get("name"), _service_desc(r)))
    else:
        for r in rows:
            out.append((False, r.get("label") or r.get("name"), _service_desc(r)))

    if len(out) == 1:
        out.append((False, "لا يوجد", None))
    return out


def _word_rows(sec, *, left=False):
    """Rows in the five-column roster template.

    The printed roster reserves two columns on the right for basic/target
    services and three on the left for emergency/prison/status details.
    Keeping the shape here (rather than exporting the web cards) makes the
    downloaded document match the operational Word form.
    """
    name, sec_type = sec["name"], sec["type"]
    rows = list(sec.get("rows") or [])
    result = [(True, name, None, None)]
    for row in rows:
        if left:
            if sec_type in {"officers", "admin"}:
                result.append((False, row.get("status_type") or row.get("reason") or name,
                               _who(row) or _people_text(row.get("officers")),
                               row.get("detail") or _officer_desc(name, row)))
            else:
                result.append((False, row.get("label") or row.get("name") or "—",
                               _people_text(row.get("officers")), _service_desc(row)))
        elif sec_type in {"officers", "admin"}:
            result.append((False, _who(row) or "—", _officer_desc(name, row), None))
        elif sec_type == "targets":
            result.append((False, row.get("label") or row.get("name") or "—",
                           _people_text(row.get("officers")) or _people_text(row.get("commander")), None))
        else:
            result.append((False, row.get("label") or row.get("name") or "—", _service_desc(row), None))
    if len(result) == 1:
        result.append((False, "لا يوجد", None, None))
    return result


def build_docx(board):
    """`board` هو نفسه مخرج `build_board(data, day)` — نفس الـJSON اللي
    الواجهة بترسمه بالظبط. جدول واحد بعمودين مستقلين (يمين/شمال) بدل
    كروت منفصلة، زي الورقة الرسمية الحقيقية بالظبط."""
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
    run = title.add_run(_day_title(board["date"]))
    run.bold = True
    run.underline = True
    run.font.size = Pt(18)
    run.font.name = "Arial"
    document.add_paragraph()

    # نفس ترتيب Word والواجهة: أساسية/أهداف/المعسكر/عمل الإدارة يمين،
    # والطوارئ/السجن/الخوارج شمال.
    sections = _presentation_sections(board["sections"])
    right_names = [SECTION_BASIC, SECTION_TARGETS, SECTION_SUBCAMP, SECTION_ADMIN_WORK]
    left_names = [SECTION_OCCASIONAL, SECTION_PRISON, SECTION_OUTSIDERS]
    right = [next((s for s in sections if s["name"] == name), None) for name in right_names]
    right = [s for s in right if s]
    left = [next((s for s in sections if s["name"] == name), None) for name in left_names]
    left = [s for s in left if s]

    right_rows, left_rows = [], []
    for sec in right:
        right_rows.extend(_word_rows(sec))
    for sec in left:
        left_rows.extend(_word_rows(sec, left=True))

    total = max(len(right_rows), len(left_rows), 1)
    # Official roster template: two right columns + three left columns.
    tbl = document.add_table(rows=total, cols=5)
    tbl.style = "Table Grid"
    tbl.autofit = False
    _rtl_table(tbl)
    widths = [Cm(4.2), Cm(3.8), Cm(3.5), Cm(3.5), Cm(3.6)]
    for col, w in zip(tbl.columns, widths):
        col.width = w

    for i in range(total):
        cells = tbl.rows[i].cells
        for cells_pair, seq in ((cells[0:2], right_rows), (cells[2:5], left_rows)):
            if i >= len(seq):
                continue
            is_header, a, b, c = seq[i]
            if is_header:
                merged = cells_pair[0]
                for extra in cells_pair[1:]:
                    merged = merged.merge(extra)
                _shade(merged, HEADER_FILL)
                _cell_text(merged, a, bold=True, size=12, center=True)
            else:
                _cell_text(cells_pair[0], a, bold=True, size=10.5)
                _cell_text(cells_pair[1], b, size=10.5)
                if len(cells_pair) == 3:
                    _cell_text(cells_pair[2], c, size=10.5)

    buf = BytesIO()
    document.save(buf)
    buf.seek(0)
    return buf
