"""تصدير اليومية التفصيلية كملف Word حقيقي (.docx) بصيغة الأرشيف الأحدث.
كل يوم يستخدم نفس شبكة الستة أعمدة، ترتيب المناطق، والصفحة الواحدة؛
النص فقط يُشتق من مخرج `build_board` الحالي.
"""
import re
from datetime import date, timedelta
from io import BytesIO

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, Twips
from docx.table import _Cell

from .export_fit import (apply_fit_to_docx_table, fit_table, usable_height_pt,
                         estimate_table_height)

from .constants import (
    SECTION_ADMIN_WORK, SECTION_BASIC, SECTION_OCCASIONAL, SECTION_OUTSIDERS,
    SECTION_PRISON, SECTION_RESTS, SECTION_SECURITY, SECTION_GREAT, SECTION_SUBCAMP,
    SECTION_TARGETS, SECTION_TAQSEERA,
)
from .afraad import _time_key
from .labels import officer_label, personnel_label

WEEKDAY_BY_INDEX = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
MONTH_BY_INDEX = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
                  "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]

RIGHT_COLUMN_SECTIONS = {SECTION_BASIC, SECTION_TARGETS, SECTION_SUBCAMP, SECTION_ADMIN_WORK}
# الأقسام اللي موضوعها الأساسي «ضابط» (كل صف = ضابط) — اسم الضابط بييجي
# أول عمود (يمين نصفه)، والوصف بعده. عكس أقسام الخدمات/الأهداف/الكتل
# اللي موضوعها الأساسي «خدمة» فاسمها هو اللي بييجي أول عمود.
OFFICER_CENTRIC = {SECTION_ADMIN_WORK, SECTION_RESTS, SECTION_TAQSEERA, SECTION_OUTSIDERS}

HEADER_FILL = "E9E9E9"


def set_run_font(run, name="Arial", size_pt=11, bold=False):
    """Set the four Word font properties needed by Arabic complex-script runs."""
    run.bold = bold
    run.font.name = name
    run.font.size = Pt(size_pt)
    rpr = run._r.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.append(fonts)
    for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
        fonts.set(qn("w:" + attr), name)
    for tag in ("w:sz", "w:szCs"):
        node = rpr.find(qn(tag))
        if node is None:
            node = OxmlElement(tag)
            rpr.append(node)
        node.set(qn("w:val"), str(round(size_pt * 2)))
    for tag in ("w:b", "w:bCs"):
        node = rpr.find(qn(tag))
        if node is None:
            node = OxmlElement(tag)
            rpr.append(node)
        node.set(qn("w:val"), "1" if bold else "0")
    return run


# ترتيب أبناء العناصر حسب مخطط OOXML — Word بيرفض (أو يتجاهل) العنصر لو جه في
# غير مكانه، والإضافة بـappend كانت بتحط rFonts بعد sz وbidi بعد jc.
_ORDERS = {
    "rPr": ["rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike",
            "outline", "shadow", "emboss", "imprint", "noProof", "snapToGrid", "vanish", "webHidden",
            "color", "spacing", "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect",
            "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang", "eastAsianLayout",
            "specVanish", "oMath"],
    "pPr": ["pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl", "numPr",
            "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens", "kinsoku", "wordWrap",
            "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd",
            "snapToGrid", "spacing", "ind", "contextualSpacing", "mirrorIndents", "suppressOverlap",
            "jc", "textDirection", "textAlignment", "textboxTightWrap", "outlineLvl", "divId",
            "cnfStyle", "rPr", "sectPr", "pPrChange"],
    "tcPr": ["cnfStyle", "tcW", "gridSpan", "hMerge", "vMerge", "tcBorders", "shd", "noWrap", "tcMar",
             "textDirection", "tcFitText", "vAlign", "hideMark"],
    "tblPr": ["tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize",
              "tblStyleColBandSize", "tblW", "jc", "tblCellSpacing", "tblInd", "tblBorders", "shd",
              "tblLayout", "tblCellMar", "tblLook", "tblCaption", "tblDescription"],
}


def order_xml_children(document):
    """يرتّب أبناء rPr/pPr/tcPr/tblPr في كل المستند بترتيب المخطط (ثابت وآمن)."""
    body = document.element.body
    for tag, order in _ORDERS.items():
        rank = {qn("w:" + name): index for index, name in enumerate(order)}
        for element in body.iter(qn("w:" + tag)):
            children = list(element)
            ordered = sorted(children, key=lambda child: rank.get(child.tag, len(rank)))
            if ordered != children:
                for child in children:
                    element.remove(child)
                for child in ordered:
                    element.append(child)


def style_tables_bold_rtl(document):
    """كل الجداول: خط عريض (bold) واتجاه يمين لشمال (RTL) — الجدول والفقرات والخطوط."""
    for table in document.tables:
        if table._tbl.tblPr.find(qn("w:bidiVisual")) is None:
            table._tbl.tblPr.append(OxmlElement("w:bidiVisual"))
        for row in table.rows:
            for tc in row._tr.tc_lst:
                for paragraph in _Cell(tc, table).paragraphs:
                    ppr = paragraph._p.get_or_add_pPr()
                    if ppr.find(qn("w:bidi")) is None:
                        ppr.append(OxmlElement("w:bidi"))
                    for run in paragraph.runs:
                        set_run_font(run, run.font.name or "Arial",
                                     run.font.size.pt if run.font.size else 10, True)
                        rpr = run._r.get_or_add_rPr()
                        if rpr.find(qn("w:rtl")) is None:
                            rpr.append(OxmlElement("w:rtl"))
    order_xml_children(document)


def normalize_document_runs(document):
    """Repair template/hand-created runs, including complex-script settings."""
    for paragraph in document.paragraphs:
        for run in paragraph.runs:
            set_run_font(run, run.font.name or "Arial",
                         run.font.size.pt if run.font.size else 10,
                         bool(run.bold))
    for table in document.tables:
        for row in table.rows:
            # الخلايا الفعلية بس: الدمج الرأسي بيرجّع خلية الصف اللي فوق كاسم مستعار
            for tc in row._tr.tc_lst:
                cell = _Cell(tc, table)
                # كل الجداول: نص الخلايا في النص أفقيًا ورأسيًا
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                for paragraph in cell.paragraphs:
                    _format_cell_paragraph(paragraph)
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    for run in paragraph.runs:
                        set_run_font(run, run.font.name or "Arial",
                                     run.font.size.pt if run.font.size else 10,
                                     bool(run.bold))
    style_tables_bold_rtl(document)


def _format_cell_paragraph(paragraph, exact_line=None):
    ppr = paragraph._p.get_or_add_pPr()
    bidi = ppr.find(qn("w:bidi"))
    if bidi is None:
        ppr.append(OxmlElement("w:bidi"))
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.line_spacing = 1
    if exact_line is not None:
        spacing = ppr.find(qn("w:spacing"))
        if spacing is None:
            spacing = OxmlElement("w:spacing")
        spacing.set(qn("w:lineRule"), "exact")
        spacing.set(qn("w:line"), str(round(exact_line * 20)))
        if spacing.getparent() is None:
            ppr.append(spacing)


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
    person = person or {}
    return officer_label(person) if person.get("category") != "personnel" else personnel_label(person)


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


def _cell_text(cell, text, bold=False, size=11, center=False, font_name="Bahnschrift SemiBold"):
    cell.text = ""
    if text in (None, ""):
        return
    p = cell.paragraphs[0]
    _rtl_right(p)
    _format_cell_paragraph(p)
    if center:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(str(text))
    set_run_font(run, font_name, size, bold)


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


def _basic_assignee(row):
    """The basic-services Word column contains the officer only."""
    officers = _people_text(row.get("officers"))
    if officers:
        return officers
    personnel = _people_text(row.get("personnel"))
    if personnel:
        return personnel
    source = (row.get("source_manning") or "").strip()
    # A source string containing a rank/name is still an officer assignment;
    # pure strength text ("2 فرد + 2 مج") belongs only in emergency services.
    if "/" in source and not any(token in source for token in ("فرد", "مج")):
        return source
    return ""


def _conscript_total(row):
    return row.get("conscript_count") or sum(
        (entry.get("count") or 0) for entry in row.get("conscripts") or [])


def _source_strength_is_current(row, source):
    """نص القوام المستورد («2فرد + 2 مج») يفضل صالح للطباعة طول ما أرقامه
    بتطابق اللي مربوط بالسيستم. لو المشغّل عدّل الأفراد أو المجندين بعد
    الاستيراد، الأرقام بتختلف فنطبع المحسوب من الداتا الحالية بدل النص القديم."""
    linked_people = len(row.get("officers") or []) + len(row.get("personnel") or [])
    linked_conscripts = _conscript_total(row)
    if not linked_people and not linked_conscripts:
        return True                      # مفيش حاجة مربوطة نقارن بيها
    people = re.search(r"(\d+)\s*فرد", source)
    conscripts = re.search(r"(\d+)\s*مج", source)
    if people and int(people.group(1)) != linked_people:
        return False
    if conscripts and int(conscripts.group(1)) != linked_conscripts:
        return False
    return True


def _compact_manning(row):
    """Word's emergency column: personnel strength, without service details."""
    source = (row.get("source_manning") or "").strip()
    if (source and not ("/" in source and not any(token in source for token in ("فرد", "مج")))
            and _source_strength_is_current(row, source)):
        return source
    bits = []
    if row.get("officers"):
        bits.append(_people_text(row.get("officers")))
    if row.get("personnel"):
        # عمود القوام في الورقة أعداد («2فرد + 2 مج») مش أسماء — الأسماء في يومية الأفراد
        count = len(row["personnel"])
        bits.append(f"{count}فرد" if count > 1 else "فرد")
    for conscript in row.get("conscripts") or []:
        cls = conscript.get("class") or "مج"
        count = conscript.get("count")
        bits.append(f"{count}{cls}" if count else cls)
    if row.get("conscript_count") and not row.get("conscripts"):
        bits.append(f"{row['conscript_count']}مج")
    return " + ".join(filter(None, bits))


def _officer_desc(section_name, row):
    if section_name == SECTION_ADMIN_WORK:
        if row.get("fixedSection"):
            return _people_text(row.get("officers"))
        return row.get("text") or ""
    if section_name == SECTION_OUTSIDERS:
        return row.get("detail") or row.get("reason") or ""
    if section_name == SECTION_RESTS:
        span = " → ".join(filter(None, [_fmt_date(row.get("start")), _fmt_date(row.get("end"))]))
        return f"{row.get('type') or 'راحة'} ({span})" if span else (row.get("type") or "راحة")
    if section_name == SECTION_TAQSEERA:
        return row.get("note") or "تقصيرة"
    return ""


def leave_text(leave_type, start, end, return_date):
    """نص الراحة/الإجازة المطبوع: «راحة شهرية من 17/9 والعودة 22/9» أو
    «إجازة مصيف من 11/9 والعودة 16/9». الأسبوعية يوم واحد فبتتكتب من غير مدة."""
    kind = str(leave_type or "").strip() or "راحة"
    label = kind if kind.startswith(("إجازة", "اجازة", "راحة")) or kind in ("مرضي", "طارئة") \
        else f"راحة {kind}"
    if not start or (kind == "أسبوعية" and (not end or end == start)):
        return label
    back = return_date
    if not back and end:
        try:
            back = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
        except ValueError:
            back = ""
    text = f"{label} من {_fmt_date(start)}"
    return f"{text} والعودة {_fmt_date(back)}" if back else text


def status_period_text(period):
    """تفاصيل الحالة الممتدة: المفتوحة من يوم البداية، والمحددة من/حتى."""
    period = period or {}
    start = _fmt_date(period.get("start"))
    end = _fmt_date(period.get("end"))
    if end:
        return f"من {start} حتى {end}" if start else f"حتى {end}"
    return f"من يوم {start}" if start else ""


def _presentation_sections(sections):
    by_name = {section["name"]: section for section in sections}
    admin = by_name.get(SECTION_ADMIN_WORK, {"name": SECTION_ADMIN_WORK, "type": "admin", "rows": []})
    admin_rows = list(admin.get("rows") or [])
    # التقصيرة مش بتتطبع كقسم: اللي مالوش خدمة بيتضاف لعمل بالإدارة بنص عمله،
    # واللي عليه خدمة ظاهر في مكان خدمته أصلًا.
    taqseera = by_name.get(SECTION_TAQSEERA, {})
    admin_rows.extend({key: row.get(key) for key in ("id", "name", "role", "short_name", "category")
                       if key in row} | {"text": row.get("text") or row.get("note") or ""}
                      for row in taqseera.get("rows", []) if not row.get("has_service"))
    for name in (SECTION_GREAT, SECTION_SECURITY):
        source = by_name.get(name)
        for row in source.get("rows", []) if source else []:
            admin_rows.append({**row, "fixedSection": name, "fixedLabel": name})
    outsiders = []
    for name in (SECTION_RESTS, SECTION_OUTSIDERS):
        source = by_name.get(name)
        for row in source.get("rows", []) if source else []:
            if name == SECTION_RESTS:
                detail = leave_text(row.get("type"), row.get("start"), row.get("end"),
                                    row.get("return_date"))
                status_type = "إجازة" if str(row.get("type") or "").startswith(("إجازة", "اجازة")) else "راحة"
            else:
                status_type = row.get("reason") or "خارج"
                if row.get("start"):
                    detail = leave_text(row.get("leave_type"), row.get("start"), row.get("end"),
                                        row.get("return_date"))
                    if row.get("note") and row["note"] not in detail:
                        detail = f"{detail} — {row['note']}"
                elif row.get("status_period"):
                    detail = status_period_text(row["status_period"])
                    if row.get("note") and row["note"] not in detail:
                        detail = f"{detail} — {row['note']}"
                elif row.get("course"):
                    from .duty import course_with_note
                    detail = course_with_note(row["course"], row.get("note"))
                else:
                    detail = row.get("note") or row.get("reason") or ""
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
                               "—", _compact_manning(row)))
        elif sec_type in {"officers", "admin"}:
            result.append((False, _who(row) or "—", _officer_desc(name, row), None))
        elif sec_type == "targets":
            result.append((False, row.get("label") or row.get("name") or "—",
                           _people_text(row.get("officers")) or _people_text(row.get("commander")), None))
        else:
            if left:
                result.append((False, row.get("label") or row.get("name") or "—", "—",
                               _compact_manning(row)))
            else:
                result.append((False, row.get("label") or row.get("name") or "—",
                               _basic_assignee(row), None))
    if len(result) == 1:
        result.append((False, "لا يوجد", None, None))
    return result


def _unique_cells(row):
    cells, seen = [], set()
    for cell in row.cells:
        if id(cell._tc) not in seen:
            cells.append(cell)
            seen.add(id(cell._tc))
    return cells


def _physical_cells(row):
    """خلايا الصف الفعلية في الـXML — من غير الأسماء المستعارة اللي
    python-docx بيرجّعها للخلايا المدموجة رأسيًا (continue بترجّع خلية الصف
    اللي فوقها، فالكتابة عليها كانت بتمسح نص الخلية الأصلية)."""
    return [_Cell(tc, row.table) for tc in row._tr.tc_lst]


def _merge_shape(table, row_index, spans):
    cells = table.rows[row_index].cells
    start = 0
    for span in spans:
        if span > 1:
            cells[start].merge(cells[start + span - 1])
        start += span


def _set_vmerge(cell, value):
    tc_pr = cell._tc.get_or_add_tcPr()
    node = tc_pr.find(qn("w:vMerge"))
    if node is None:
        node = OxmlElement("w:vMerge")
        tc_pr.append(node)
    if value:
        node.set(qn("w:val"), value)


def _section_by_name(sections, name, default_type="services"):
    return next((s for s in sections if s["name"] == name),
                {"name": name, "type": default_type, "rows": []})


TAIL_START = 20          # أول صف في الجزء الأخير (كتلة المعسكر الفرعي / الخوارج)
ADMIN_MIN_ROWS = 11      # صفوف «عمل بالادارة» في الورقة الرسمية
TAIL_MIN_ROWS = 14


def tail_row_count(admin_count, outsider_count):
    """عدد صفوف الجزء الأخير: صفّين فرعي + عنوان + صفوف الإدارة (ولا أقل من
    11)، أو عدد الخوارج لو أكتر. الأدنى 14 = ٣٤ صف في الورقة الرسمية."""
    return max(TAIL_MIN_ROWS, 3 + max(ADMIN_MIN_ROWS, admin_count), outsider_count)


def _latest_content(board):
    """الـ20 صف الثابتة بترتيب الورقة الأحدث + الجزء الأخير الديناميكي.

    بيرجّع (المحتوى، مجموعات دمج الحالة رأسيًا [(أول صف، آخر صف)])."""
    sections = _presentation_sections(board["sections"])

    def rows(name, kind="services"):
        return list(_section_by_name(sections, name, kind).get("rows") or [])

    basic, emergency = rows(SECTION_BASIC), rows(SECTION_OCCASIONAL)
    # أي قسم خدمات المشغّل ضافه بإيده (ماتش، انتشار، تفتيشات…) بينضم لجدول الطوارئ —
    # زي يومية الأفراد — والكل مترتب بمعاد الانتظام (ترتيب مستقر لنفس الساعة)
    known = {SECTION_BASIC, SECTION_OCCASIONAL, SECTION_TARGETS, SECTION_PRISON, SECTION_SUBCAMP,
             SECTION_GREAT, SECTION_SECURITY, SECTION_ADMIN_WORK, SECTION_RESTS, SECTION_TAQSEERA,
             SECTION_OUTSIDERS}
    for section in sections:
        if section["name"] not in known and section.get("type") == "services":
            emergency.extend(section.get("rows") or [])
    emergency.sort(key=lambda row: _time_key(row.get("time")))
    targets, prison = rows(SECTION_TARGETS, "targets"), rows(SECTION_PRISON)
    subcamp = rows(SECTION_SUBCAMP, "slots")
    outsiders = rows(SECTION_OUTSIDERS, "officers")
    admin = rows(SECTION_ADMIN_WORK, "admin")
    for name in (SECTION_GREAT, SECTION_SECURITY):
        for item in rows(name, "slots"):
            admin.append({**item, "fixedSection": name})

    def pair(row, left):
        if not row:
            return "", ""
        return (row.get("label") or row.get("name") or "",
                left(row))

    def assignee(row):
        return _basic_assignee(row)

    def manning(row):
        return _compact_manning(row)

    # الصفوف الأساسية/الطارئة 9 في الورقة الرسمية، وبتكبر لو أي منهم أكتر (قبل كده
    # الزيادة كانت بتتقطع من الطباعة)؛ صف «الاهداف» بياخد آخر صف طارئ
    top = max(9, len(basic), len(emergency) - 1)
    prison_n = max(7, len(prison))
    shift = (top - 9) + (prison_n - 7)
    content = [["الخدمات الاساسية", "الخدمات الطارئة"]]
    for i in range(top):
        content.append([*pair(basic[i] if i < len(basic) else None, assignee),
                        *pair(emergency[i] if i < len(emergency) else None, manning)])
    content.append(["الاهداف", *pair(emergency[top] if len(emergency) > top else None, manning)])

    target_rows = targets[:8] + [{}] * max(0, 8 - len(targets))
    prison_rows = prison + [{}] * (prison_n - len(prison))
    target_person = lambda r: _people_text(r.get("officers")) or _people_text(r.get("commander"))
    content.append(["مشرف الأهداف", target_person(target_rows[0]), "خدمات سجن قوات الامن"])
    for i in range(prison_n):
        p = prison_rows[i]
        pname = p.get("label") or p.get("name") or ""
        ptext = manning(p) if pname else ""
        if pname.startswith("فرد تأمين") and not ptext:
            ptext = "ــــــــــــــــــــ"
        target = target_rows[i + 1] if i < 7 else {}
        content.append([target.get("label") or target.get("name") or "",
                        target_person(target), pname, ptext])
    content.append(["ضابط عظيم وأمن المعسكر الفرعي", "الخوارج"])

    # الجزء الأخير: يمين = كتلة المعسكر الفرعي (صفّين) ثم عنوان «عمل بالادارة»
    # وتحته صفوف العمل بالإدارة؛ شمال = قايمة الخوارج من أول صف. عدد الصفوف
    # بيكبر مع البيانات (الأدنى زي الورقة الرسمية: 11 صف عمل بالإدارة) بدل
    # ما يتقطّع أي حد — العمود الأول للحالة بيتدمج رأسيًا لكل مجموعة متتالية.
    tail = tail_row_count(len(admin), len(outsiders))
    statuses = [o.get("status_type") or o.get("reason") or "" for o in outsiders]
    groups, continued, start = [], set(), 0
    while start < len(statuses):
        end = start
        while statuses[start] and end + 1 < len(statuses) and statuses[end + 1] == statuses[start]:
            end += 1
        if end > start:
            groups.append((TAIL_START + shift + start, TAIL_START + shift + end))
            continued.update(range(start + 1, end + 1))
        start = end + 1
    for i in range(tail):
        outsider = outsiders[i] if i < len(outsiders) else {}
        left = ["" if i in continued else statuses[i] if i < len(statuses) else "",
                _who(outsider), _officer_desc(SECTION_OUTSIDERS, outsider)]
        if i < 2:
            slot = subcamp[i] if i < len(subcamp) else {}
            right = [slot.get("shift") or ("فترة صباحية" if i == 0 else "فترة ليلية"),
                     _people_text(slot.get("officers"))]
        elif i == 2:
            content.append(["عمل بالادارة", *left])
            continue
        else:
            row = admin[i - 3] if i - 3 < len(admin) else {}
            description = row.get("text") or row.get("name") or ""
            if row.get("fixedSection") and row.get("shift"):
                description = f"{description} {row['shift']}".strip()
            right = [_who(row), description]
        content.append([*right, *left])
    return content, groups, top, prison_n


def build_docx(board):
    """Build every day using the 9/28–9/29 six-column archive family."""
    document = Document()
    _set_rtl_doc(document)
    sect = document.sections[0]
    sect.orientation = WD_ORIENT.PORTRAIT
    sect.page_width, sect.page_height = Twips(11906), Twips(16838)
    sect.top_margin, sect.right_margin = Twips(249), Twips(720)
    sect.bottom_margin, sect.left_margin = Twips(142), Twips(567)
    sect.header_distance = sect.footer_distance = Twips(720)
    style = document.styles["Normal"]
    style.font.name = "Bahnschrift SemiBold"
    style.font.size = Pt(10.5)
    document.add_paragraph()

    content, groups, top, prison_n = _latest_content(board)
    shift = (top - 9) + (prison_n - 7)
    row_count = len(content)
    table = document.add_table(rows=row_count, cols=6)
    table.style = "Table Grid"
    table.autofit = False
    _rtl_table(table)
    widths = [Twips(x) for x in (1694, 9, 2974, 711, 2129, 3248)]
    for col, width in zip(table.columns, widths):
        col.width = width
    # الصفوف الأساسية/الطارئة (top) وخدمات السجن (prison_n) بتكبر مع البيانات؛ الأدنى زي الورقة
    shapes = ([[3, 3]] + [[2, 1, 2, 1]] * (top - 1) + [[1, 2, 2, 1], [3, 2, 1], [2, 1, 3]] +
              [[2, 1, 2, 1]] * prison_n + [[3, 3], [2, 1, 1, 1, 1], [2, 1, 1, 1, 1],
                                           [3, 1, 1, 1]] +
              [[2, 1, 1, 1, 1]] * (row_count - 23 - shift))
    for index, shape in enumerate(shapes):
        _merge_shape(table, index, shape)

    # عمود الحالة في قايمة الخوارج بيتدمج رأسيًا لكل مجموعة متتالية من نفس
    # الحالة (راحة، فرقة…) — حسب البيانات مش شكل ثابت، فمفيش اسم يتخبّى
    # جوّه خلية «continue». الخلية دي هي قبل الأخيرة التلاتة من يمين الصف.
    for first, last in groups:
        for index in range(first, last + 1):
            status_cell = _physical_cells(table.rows[index])[-3]
            _set_vmerge(status_cell, "restart" if index == first else "continue")

    header_rows = {0, top + 1, top + 2, 19 + shift, 22 + shift}
    for index, values in enumerate(content):
        for cell, value in zip(_physical_cells(table.rows[index]), values):
            _cell_text(cell, value, bold=True, size=10.5, center=index in header_rows)
        if index in header_rows:
            # صف 22 عنوانه بس على اليمين؛ باقيه خاص بقايمة الخوارج
            cells = _physical_cells(table.rows[index])
            for cell in (cells[:1] if index == 22 + shift else cells):
                _shade(cell, "D9D9D9")

    widths_pt = [width.pt for width in widths]
    spec_rows = []
    for shape, row in zip(shapes, table.rows):
        measured = []
        for cell, span in zip(_physical_cells(row), shape):
            measured.append({"text": cell.text, "size_pt": 10.5, "bold": True,
                             "font": "Bahnschrift SemiBold", "colspan": span})
            measured.extend({"text": "", "size_pt": 10.5, "colspan": 1}
                            for _ in range(span - 1))
        spec_rows.append(measured)
    fit = fit_table({"rows": spec_rows, "grid_widths_pt": widths_pt},
                    usable_height_pt(sect))
    apply_fit_to_docx_table(table, fit)
    tail = document.add_paragraph()
    tail.paragraph_format.space_before = Pt(0)
    tail.paragraph_format.space_after = Pt(0)
    set_run_font(tail.add_run(), "Bahnschrift SemiBold", 1, False)
    normalize_document_runs(document)
    LAST_FIT.clear()
    LAST_FIT.update(scale=fit.scale, ratio=fit.ratio, total_pt=fit.total_pt,
                    usable_pt=fit.usable_pt)
    buf = BytesIO()
    document.save(buf)
    buf.seek(0)
    return buf


LAST_FIT = {}
