"""تصدير اليومية التفصيلية كملف Word حقيقي (.docx) بصيغة الأرشيف الأحدث.

القالب `docx_templates/board_roster.docx` نسخة من ملف أرشيف حقيقي (2026/10/20):
الشبكة (5 أعمدة)، الجدول العائم وحدوده، الهيدر (العنوان)، هوامش الصفحة وحدودها،
الأنماط والإعدادات كلها منه. المُصدِّر يبني الصفوف من `build_board` ويستنسخ
خصائص الخلية/الفقرة/الـrun من خلية نموذج في القالب؛ tcW = مجموع الأعمدة
المشمولة، وارتفاع الصف atLeast بلا hRule، ومقاس الخط فقط يُختار بالتقدير.
"""
import re
from copy import deepcopy
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.table import _Cell

from .export_fit import (PageFitError, TextMeter, estimate_table_height, fit_widths,
                         percentile_need)

from .constants import (
    SECTION_ADMIN_WORK, SECTION_BASIC, SECTION_NET, SECTION_OCCASIONAL, SECTION_OUTSIDERS,
    SECTION_INSPECTIONS, SECTION_PRISON, SECTION_RESTS, SECTION_SECURITY, SECTION_GREAT, SECTION_SUBCAMP,
    SECTION_TARGETS, SECTION_TAQSEERA,
)
from .afraad import _time_key
from .board import canonical_section_name
from .labels import officer_label, personnel_label
from .service_sections import block_title, is_structural, split_custom_sections

WEEKDAY_BY_INDEX = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
MONTH_BY_INDEX = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
                  "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]

RIGHT_COLUMN_SECTIONS = {
    SECTION_BASIC, SECTION_TARGETS, SECTION_SUBCAMP, SECTION_GREAT, SECTION_SECURITY,
    SECTION_ADMIN_WORK, SECTION_NET,
}
# الأقسام اللي موضوعها الأساسي «ضابط» (كل صف = ضابط) — اسم الضابط بييجي
# أول عمود (يمين نصفه)، والوصف بعده. عكس أقسام الخدمات/الأهداف/الكتل
# اللي موضوعها الأساسي «خدمة» فاسمها هو اللي بييجي أول عمود.
OFFICER_CENTRIC = {
    SECTION_ADMIN_WORK, SECTION_NET, SECTION_RESTS, SECTION_TAQSEERA, SECTION_OUTSIDERS,
}

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
    label = officer_label(person) if person.get("category") != "personnel" else personnel_label(person)
    return f"{label} + ت" if label and person.get("taqseera") else label


def _people_list(people):
    """تسميات الأشخاص (اسم الشهرة إن وُجد) واحدًا واحدًا — لصف مستقل لكل شخص."""
    return [label for label in (_who(p) for p in (people or []) if p) if label]


def _people_text(people):
    return "، ".join(_people_list(people))


def _command_text(row, who):
    """نص دور الرئاسة، بما فيه الدور المؤكد الذي ما زال شاغرًا."""
    key = f"{who}_command_required"
    people_key = "officers" if who == "officer" else "personnel"
    vacant = "ضابط" if who == "officer" else "فرد"
    people = _people_text(row.get(people_key))
    if not row.get(key) and not people:
        return ""
    return people or vacant


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
    who = "، ".join(filter(None, [_command_text(row, "officer"),
                                  _command_text(row, "personnel")]))
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


def _basic_assignees(row):
    """عمود الخدمات الأساسية في Word: ضابط واحد لكل عنصر (كل واحد في صف مستقل)."""
    officers = _people_list(row.get("officers"))
    if officers:
        return officers
    personnel = _people_list(row.get("personnel"))
    if personnel:
        return personnel
    if row.get("officer_command_required"):
        return ["ضابط"]
    if row.get("personnel_command_required"):
        return ["فرد"]
    source = (row.get("source_manning") or "").strip()
    # نص مستورد حرفي فيه رتبة/اسم يظل كما هو (أرشيف)؛ نص القوام الصرف
    # («2 فرد + 2 مج») مكانه الخدمات الطارئة فقط.
    if "/" in source and not any(token in source for token in ("فرد", "مج")):
        return [source]
    return []


def _basic_assignee(row):
    return "\n".join(_basic_assignees(row))


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
    if row.get("officers") or row.get("officer_command_required"):
        bits.append(_command_text(row, "officer"))
    if row.get("personnel") or row.get("personnel_command_required"):
        # عمود القوام في الورقة أعداد («2فرد + 2 مج») مش أسماء — الأسماء في يومية الأفراد
        count = len(row.get("personnel") or [])
        bits.append(f"{count}فرد" if count > 1 else "فرد")
    for conscript in row.get("conscripts") or []:
        cls = conscript.get("class") or "مج"
        count = conscript.get("count")
        bits.append(f"{count}{cls}" if count else cls)
    if row.get("conscript_count") and not row.get("conscripts"):
        bits.append(f"{row['conscript_count']}مج")
    return " + ".join(filter(None, bits))


def _manning_pieces(row):
    """نص عمود القوام مقسومًا لصف لكل ضابط حين يكون للخدمة ضابطان أو أكثر.

    النص المستورد الحرفي (source_manning الساري) يبقى قطعة واحدة كما هو."""
    text = _compact_manning(row)
    officers = _people_list(row.get("officers"))
    source = (row.get("source_manning") or "").strip()
    if len(officers) < 2 or (source and text == source):
        return [text]
    rest = []
    if row.get("personnel") or row.get("personnel_command_required"):
        count = len(row.get("personnel") or [])
        rest.append(f"{count}فرد" if count > 1 else "فرد")
    for conscript in row.get("conscripts") or []:
        cls = conscript.get("class") or "مج"
        rest.append(f"{conscript['count']}{cls}" if conscript.get("count") else cls)
    if row.get("conscript_count") and not row.get("conscripts"):
        rest.append(f"{row['conscript_count']}مج")
    first = " + ".join(filter(None, [officers[0], *rest]))
    return [first, *officers[1:]]


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
    if section_name == SECTION_NET:
        return ""
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
    if period.get("title") and period.get("label"):
        return period["label"]      # «مأمورية: <الاسم> — <التفاصيل> — من … حتى …»
    start = _fmt_date(period.get("start"))
    end = _fmt_date(period.get("end"))
    if end:
        return f"من {start} حتى {end}" if start else f"حتى {end}"
    return f"من يوم {start}" if start else ""


# ترتيب أنواع «الخوارج»: الراحة ثم الإجازة ثم الفرقة (زي الملفات الحقيقية)
# ثم باقي الحالات؛ أي نوع غير معروف ييجي بعدهم بترتيب أول ظهور.
OUTSIDER_KIND_ORDER = ("راحة", "إجازة", "فرقة", "دورة", "مرضي", "مأمورية", "انتداب", "طارئة", "غياب")


def group_outsiders_by_kind(rows):
    """يجمع صفوف الخوارج بحيث كل نوع حالة في مجموعة واحدة متتالية.

    الترتيب ثابت (stable): ترتيب الأنواع من OUTSIDER_KIND_ORDER ثم أول ظهور،
    وداخل النوع الواحد بيفضل ترتيب الأشخاص الأصلي (الرتبة/الأقدمية)."""
    first = {}
    for row in rows:
        first.setdefault(row.get("status_type") or "", len(first))

    def rank(row):
        kind = row.get("status_type") or ""
        if kind in OUTSIDER_KIND_ORDER:
            return (0, OUTSIDER_KIND_ORDER.index(kind))
        return (1, first[kind])
    return sorted(rows, key=rank)


def _presentation_sections(sections):
    by_name = {section["name"]: section for section in sections}
    admin = by_name.get(SECTION_ADMIN_WORK, {"name": SECTION_ADMIN_WORK, "type": "admin", "rows": []})
    admin_rows = list(admin.get("rows") or [])
    # التقصيرة لا تنشئ قسمًا ولا تُنقل إلى عمل الإدارة: علامة «+ ت» موجودة
    # على الضابط داخل خدمته أو الصافي/عمل الإدارة.
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
    outsiders = group_outsiders_by_kind(outsiders)
    hidden = {SECTION_ADMIN_WORK, SECTION_RESTS, SECTION_TAQSEERA, SECTION_OUTSIDERS}
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


TEMPLATE = Path(__file__).with_name("docx_templates") / "board_roster.docx"
LAST_FIT = {}

# القالب نسخة من ملف أرشيف حقيقي (2026/10/20/20.docx): الشبكة (5 أعمدة)، tblPr
# العائم والحدود، الهيدر، هوامش الصفحة وحدودها، النمط الأساسي والإعدادات كلها من
# الملف الحقيقي. المُصدِّر يبني الصفوف فقط ويستنسخ خصائص الخلية/الفقرة/الـrun
# من خلية النموذج في القالب ويغيّر النص والحجم.
FONT_SIZES_HALF = (24, 22, 20, 18, 16)   # 12..8pt: المدى الحقيقي في الأرشيف
IMPOSSIBLE_RATIO = 1.15   # التقدير تقريبي؛ فوق هذا فقط نرفض بدل أن نفشل التصدير
FIT_TARGET = .94
PAGE_HEIGHT_PT = 841.9
TABLE_TOP_PT = 62          # y بداية الجدول في ملف Word الحقيقي (الهيدر + tblpY)
TRAILING_PT = 45           # 3 فقرات ختامية بعد الجدول (sz24) في الملف الحقيقي
CELL_MARGIN_PT = 5.4       # هامش الخلية من نمط TableGrid (108 twips)
ROW_BORDER_PT = .5
MIN_TITLE, MIN_HEAD, MIN_SUBHEAD, MIN_BODY = 433, 315, 119, 94   # atLeast كما في الأرشيف (twips)
SHADE = "D9D9D9"
ROW_MINIMA = {"title": MIN_TITLE, "head": MIN_HEAD, "tailhead": MIN_SUBHEAD}


def _size_cap_half(row_count):
    """أقصى حجم خط حسب عدد الصفوف في الأرشيف: ≤35 صف حتى 12pt، وأكثر لا يتجاوز 11pt.
    الحجم الفعلي هو الأكبر الذي يتسع في صفحة واحدة (الكاتب اليدوي يملأ الصفحة) فيخرج
    ≈12pt لـ≤30 صف، 10–11pt لـ31–35، و8–9pt لما فوق."""
    return 24 if row_count <= 35 else 22


def _cell(text="", span=1, head=False, vm=None):
    return {"text": "" if text is None else str(text), "span": span, "head": head, "vm": vm}


def _row(cells, kind="body"):
    return {"cells": cells, "kind": kind}


def _group(right, left, rows):
    """مجموعة صفوف لعنصر واحد (يمين) مقابل عنصر واحد (يسار).

    كل جانب = (خلايا_الاسم, قائمة_نصوص_الأشخاص, أعمدة_الأشخاص). لو أي جانب فيه
    أكثر من شخص يتوزع كل شخص على صف مستقل وتُدمج خلية اسم الخدمة رأسيًا
    (vMerge) على كل صفوف المجموعة كما في الأرشيف الحقيقي، والجانب الأقل
    يدمج خلية اسمه على الصفوف كلها ويترك الأشخاص الزائدين فارغين."""
    def side_cells(side, index, count):
        if side is None:
            return None
        name_cells, persons = side
        out = []
        for cell in name_cells:
            vm = None
            if count > 1 and cell["text"]:
                vm = "restart" if index == 0 else "continue"
            out.append(_cell(cell["text"] if index == 0 else "", cell["span"], cell["head"], vm))
        if persons is not None:
            out.append(_cell(persons[index] if index < len(persons) else ""))
        return out

    count = max(1, len((right or ((), []))[1] or []), len((left or ((), []))[1] or []))
    for index in range(count):
        cells = []
        for side, blank in ((right, [_cell(), _cell()]), (left, [_cell("", 2), _cell()])):
            cells.extend(side_cells(side, index, count) or blank)
        rows.append(_row(cells))


def _latest_content(board):
    """صفوف اليومية بالترتيب الأحدث بلا صفوف حشو.

    كل صف: {"kind", "cells": [{"text", "span", "head", "vm"}]} على شبكة الأعمدة
    الخمسة (يمين: عمودان، يسار: ثلاثة). الأقسام الفارغة بلا بيانات تُحذف.
    «الصافي» لا يُطبع في ملف Word، وضابط عظيم/أمن الإدارة يُدرجان داخل
    قائمة «عمل بالادارة» الواحدة بنص دورهما وفترتهما."""
    sections = _presentation_sections(board["sections"])
    sections = [{**section, "name": canonical_section_name(section.get("name"))}
                for section in sections]

    def rows(name, kind="services"):
        return list(_section_by_name(sections, name, kind).get("rows") or [])

    basic, emergency = rows(SECTION_BASIC), rows(SECTION_OCCASIONAL)
    custom = [section for section in sections
              if section.get("type") == "services"
              and not is_structural(section.get("name"))]
    ordinary_custom, special_blocks = split_custom_sections(custom, _time_key)
    # أي قسم عادي (فرد + مج مثلًا) يفضل جوه جدول الطوارئ، أما المباراة/الانتشار
    # فتظهر بعنوان مستقل. التفتيشات تفضل على الشاشة بس ولا تدخل ملف Word.
    emergency.extend(ordinary_custom)
    emergency.sort(key=lambda row: _time_key(row.get("time")))
    targets, prison = rows(SECTION_TARGETS, "targets"), rows(SECTION_PRISON)
    subcamp = rows(SECTION_SUBCAMP, "slots")
    outsiders = rows(SECTION_OUTSIDERS, "officers")
    admin = rows(SECTION_ADMIN_WORK, "admin")
    great = rows(SECTION_GREAT, "slots")
    security = rows(SECTION_SECURITY, "slots")

    def name_of(row):
        return (row or {}).get("label") or (row or {}).get("name") or ""

    def target_people(row):
        return _people_list(row.get("officers")) or _people_list(row.get("commander"))

    def basic_side(row):
        if row is None:
            return None
        return [_cell(name_of(row))], _basic_assignees(row)

    def emergency_side(row):
        if row is None:
            return None
        return [_cell(name_of(row), 2)], _manning_pieces(row)

    block = bool(targets or prison)
    # صف «الاهداف» بياخد آخر صف طارئ (لو فيه كتلة أهداف/سجن)؛ غير كده الطوارئ كلها فوق
    # من غير كتل خاصة: آخر صف طارئ بيتشال لصف الاهداف لو الطوارئ أطول من
    # الأساسية (السلوك القديم). مع كتل خاصة: كل الطوارئ العادية فوق الكتل،
    # عشان صف عادي مايتطبعش بعد كتلة المباراة كأنه منها.
    borrow = block and not special_blocks and len(emergency) > len(basic)
    ordinary_rows = emergency[:-1] if borrow else emergency
    top = max(len(basic), len(ordinary_rows), 0)
    result = [_row([_cell("الخدمات الاساسية", 2, True), _cell("الخدمات الطارئة", 3, True)], "title")]
    for i in range(top):
        _group(basic_side(basic[i] if i < len(basic) else None),
               emergency_side(ordinary_rows[i] if i < len(ordinary_rows) else None), result)
    for special in special_blocks:
        result.append(_row([_cell("", 2), _cell(block_title(special["name"]), 3, True)], "head"))
        for row in special["rows"]:
            _group(None, emergency_side(row), result)
    if block:
        emg = emergency[-1] if borrow else None
        pieces = _manning_pieces(emg) if emg else [""]
        result.append(_row([_cell("الاهداف", 2, True), _cell(name_of(emg), 2),
                            _cell(pieces[0])], "head"))
        # قطع القوام الإضافية (ضابط ثانٍ للخدمة الطارئة في صف الأهداف) تأخذ صفوفًا بعده
        for extra in pieces[1:]:
            result.append(_row([_cell(), _cell(), _cell("", 2), _cell(extra)]))
        count = max(len(targets), 1 + len(prison) if prison else 0)
        for j in range(count):
            if targets and j == 0:
                right = [_cell("مشرف الأهداف")], target_people(targets[0])
            elif j < len(targets):
                right = [_cell(name_of(targets[j]))], target_people(targets[j])
            else:
                right = None
            if prison and j == 0:
                left = [_cell("خدمات سجن قوات الامن", 3, True)], None
            elif prison and j - 1 < len(prison):
                item = prison[j - 1]
                pname = name_of(item)
                ptexts = _manning_pieces(item) if pname else [""]
                if pname.startswith("فرد تأمين") and not ptexts[0]:
                    ptexts = ["ــــــــــــــــــــ"]
                left = [_cell(pname, 2)], ptexts
            else:
                left = None
            _group(right, left, result)
    result.append(_row([_cell("ضابط عظيم وأمن المعسكر الفرعي", 2, True), _cell("الخوارج", 3, True)],
                       "tailhead"))

    # يمين الذيل: قائمة واحدة مسطّحة تحت «عمل بالادارة» — كل ضابط بدوره ونصه؛
    # وضابط عظيم/أمن الإدارة يُضافان بنص «الدور + الفترة» (ويُدمجان في صف
    # الضابط نفسه لو كان فيها أصلًا، كما في الأرشيف الحقيقي).
    entries = {}
    order = []

    def add_entry(person, text):
        key = person.get("id") or id(person)
        if key not in entries:
            entries[key] = [_who(person), []]
            order.append(key)
        if text:
            entries[key][1].append(text)

    for row in admin:
        if row.get("fixedSection"):
            for person in row.get("officers") or []:
                add_entry(person, "")
        else:
            add_entry(row, row.get("text") or "")
    for title, values in ((SECTION_GREAT, great), (SECTION_SECURITY, security)):
        for index, value in enumerate(values):
            shift = str(value.get("shift") or ("صباحية" if index == 0 else "ليلية"))
            shift = shift if shift.startswith("فترة") else f"فترة {shift}"
            role = title if value.get("slot") is not False else (name_of(value) or title)
            for person in value.get("officers") or []:
                add_entry(person, f"{role} {shift}")
    right_entries = [(entries[key][0], " + ".join(entries[key][1])) for key in order]

    tail = max(2 + (1 + len(right_entries) if right_entries else 0), len(outsiders))
    statuses = [o.get("status_type") or o.get("reason") or "" for o in outsiders]
    # عمود الحالة بيتدمج رأسيًا لكل مجموعة متتالية من نفس الحالة (راحة، فرقة…)
    # — حسب البيانات، فمفيش اسم يتخبّى جوّه خلية «continue».
    vmerge = {}
    start = 0
    while start < len(statuses):
        end = start
        while statuses[start] and end + 1 < len(statuses) and statuses[end + 1] == statuses[start]:
            end += 1
        if end > start:
            vmerge[start] = "restart"
            vmerge.update({index: "continue" for index in range(start + 1, end + 1)})
        start = end + 1
    for i in range(tail):
        outsider = outsiders[i] if i < len(outsiders) else None
        mark = vmerge.get(i)
        left = [_cell("" if mark == "continue" else statuses[i] if i < len(statuses) else "",
                      vm=mark),
                _cell(_who(outsider) if outsider else ""),
                _cell(_officer_desc(SECTION_OUTSIDERS, outsider) if outsider else "")]
        if i < 2:
            slot = subcamp[i] if i < len(subcamp) else {}
            result.append(_row([
                _cell(slot.get("shift") or ("فترة صباحية" if i == 0 else "فترة ليلية")),
                _cell(_people_text(slot.get("officers"))), *left]))
            continue
        position = i - 2
        if position == 0 and right_entries:
            result.append(_row([_cell(SECTION_ADMIN_WORK, 2, True), *left], "tailhead"))
            continue
        index = position - 1
        values = right_entries[index] if right_entries and 0 <= index < len(right_entries) \
            else ("", "")
        result.append(_row([_cell(values[0]), _cell(values[1]), *left]))
    return result


# ---------------------------------------------------------------- بناء XML

def _el(tag, **attrs):
    node = OxmlElement(tag)
    for key, value in attrs.items():
        node.set(qn("w:" + key), str(value))
    return node


def _border(name, value, size):
    return _el("w:" + name, val=value, sz=size, space=0, color="auto")


def _tc_borders(start, end, kind, first_body, grid_count):
    """حدود الخلية بنفس تقاسيم الأرشيف: إطار double على الأطراف، فاصل single sz12
    بين كتلتي اليمين واليسار، وحدود علوية/سفلية مميزة لصف العنوان وصفوف العناوين."""
    borders = _el("w:tcBorders")
    top = bottom = None
    if kind == "title":
        top, bottom = ("thinThickSmallGap", 24), ("threeDEmboss", 12)
    elif kind == "head":
        top, bottom = ("threeDEmboss", 12), ("threeDEmboss", 12)
    elif kind == "tailhead":
        top, bottom = ("single", 4), ("single", 4)
    elif first_body:
        top = ("threeDEmboss", 12)
    if top:
        borders.append(_border("top", *top))
    if start == 0:
        borders.append(_border("left", "double", 4))
    elif start == 2:
        borders.append(_border("left", "single", 12))
    if bottom:
        borders.append(_border("bottom", *bottom))
    if end == grid_count:
        borders.append(_border("right", "double", 4))
    elif end == 2:
        borders.append(_border("right", "single", 12))
    return borders if len(borders) else None


def _set_rpr_size(rpr, half):
    for tag in ("w:sz", "w:szCs"):
        node = rpr.find(qn(tag))
        if node is None:
            node = OxmlElement(tag)
            rpr.append(node)
        node.set(qn("w:val"), str(half))


def _prototypes(table):
    """pPr وrPr نموذجين من خلية عادية في القالب (الفقرة بـjc=center وrFonts الحقيقي)."""
    tc = table._tbl.tr_lst[1].tc_lst[1]
    paragraph = tc.find(qn("w:p"))
    ppr = deepcopy(paragraph.find(qn("w:pPr")))
    rpr = deepcopy(paragraph.find(qn("w:r")).find(qn("w:rPr")))
    return ppr, rpr


def _build_tc(cell, start, grid, kind, first_body, protos, half):
    ppr_proto, rpr_proto = protos
    span = cell["span"]
    tc = OxmlElement("w:tc")
    pr = OxmlElement("w:tcPr")
    pr.append(_el("w:tcW", w=sum(grid[start:start + span]), type="dxa"))
    if span > 1:
        pr.append(_el("w:gridSpan", val=span))
    if cell["vm"]:
        pr.append(_el("w:vMerge", val="restart") if cell["vm"] == "restart" else _el("w:vMerge"))
    borders = _tc_borders(start, start + span, kind, first_body, len(grid))
    if borders is not None:
        pr.append(borders)
    if cell["head"]:
        pr.append(_el("w:shd", val="clear", color="auto", fill=SHADE,
                      themeFill="background1", themeFillShade="D9"))
    else:
        pr.append(_el("w:shd", val="clear", color="auto", fill="auto"))
    pr.append(_el("w:vAlign", val="center"))
    tc.append(pr)
    paragraph = OxmlElement("w:p")
    ppr = deepcopy(ppr_proto)
    mark = ppr.find(qn("w:rPr"))
    if mark is not None:
        _set_rpr_size(mark, half)
    paragraph.append(ppr)
    if cell["text"]:
        run = OxmlElement("w:r")
        rpr = deepcopy(rpr_proto)
        _set_rpr_size(rpr, half)
        run.append(rpr)
        text = OxmlElement("w:t")
        text.text = cell["text"]
        text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        run.append(text)
        paragraph.append(run)
    tc.append(paragraph)
    return tc


def _build_tr(row, grid, protos, half, head_half, first_body):
    tr = OxmlElement("w:tr")
    minimum = ROW_MINIMA.get(row["kind"], MIN_BODY)
    tr_pr = OxmlElement("w:trPr")
    tr_pr.append(_el("w:trHeight", val=minimum))      # atLeast: بلا hRule كالأرشيف
    tr.append(tr_pr)
    start = 0
    for cell in row["cells"]:
        size = head_half if cell["head"] else half
        tr.append(_build_tc(cell, start, grid, row["kind"], first_body, protos, size))
        start += cell["span"]
    return tr


MEASURE_FONT = "Times New Roman"   # الحروف العربية تُعرض بـ TNR عريض في Word الحقيقي
# مدى عرض كل عمود (twips) كما لُوحظ في ملفات الأرشيف الحقيقية، والمجموع الثابت.
COLUMN_RANGES = ((1552, 1835), (2694, 3268), (558, 887), (1701, 2290), (2938, 3520))
GRID_TOTAL = 10763
GRID_STEP = 40             # خطوة تعديل الأعمدة في البحث المحلي (twips)
GRID_PASSES = 3
NEED_PERCENTILE = .9


def _row_cells(rows):
    """[(row_index, start_col, cell)] لكل خلية فعلية."""
    for r, row in enumerate(rows):
        start = 0
        for cell in row["cells"]:
            yield r, start, cell
            start += cell["span"]


def _measure(rows, grid_pt, half, head_half):
    """تقدير ارتفاع الجدول (للاختيار بين مقاسات الخط فقط، لا لفرض ارتفاعات)."""
    spans = {}                                   # (row, start) -> عدد الصفوف المدموجة
    open_cells = {}
    for r, start, cell in _row_cells(rows):
        if cell["vm"] == "restart":
            open_cells[start] = (r, start)
            spans[(r, start)] = 1
        elif cell["vm"] == "continue" and start in open_cells:
            spans[open_cells[start]] += 1
        else:
            open_cells.pop(start, None)
    spec = []
    for r, row in enumerate(rows):
        cells = []
        start = 0
        for cell in row["cells"]:
            size = (head_half if cell["head"] else half) / 2
            item = {"text": cell["text"], "size_pt": size, "bold": True,
                    "font": MEASURE_FONT, "colspan": cell["span"],
                    "hmargins": 2 * CELL_MARGIN_PT}
            if spans.get((r, start), 1) > 1:
                item["rowspan"] = spans[(r, start)]
            cells.append(item)
            cells.extend({"text": "", "size_pt": size} for _ in range(cell["span"] - 1))
            start += cell["span"]
        spec.append(cells)
    _total, heights = estimate_table_height(spec, grid_pt)
    heights = [max(height, ROW_MINIMA.get(row["kind"], MIN_BODY) / 20) + ROW_BORDER_PT
               for height, row in zip(heights, rows)]
    return sum(heights)


def _content_grid(rows, half):
    """عرض كل عمود (twips) بحسب أطول نص فعلي فيه، داخل مدى الأرشيف الحقيقي.

    1) احتياج كل عمود = النسبة 90% من عرض نصوص خلاياه في سطر واحد (حتى لا
       يتحكم نص شاذ طويل في العمود)، وخلايا الدمج الأفقي تُحمَّل على عمودها الأخير.
    2) تُقصّ الاحتياجات في المدى ثم تُوزَّع على المجموع الثابت: الزيادة على الأعمدة
       الأكثر احتياجًا، والنقص من الأعمدة فوق حدّها الأدنى بالتناسب."""
    meter = TextMeter()
    size = half / 2
    singles = [[] for _ in COLUMN_RANGES]
    spanned = []
    for _r, start, cell in _row_cells(rows):
        if cell["head"] or not cell["text"] or cell["vm"] == "continue":
            continue
        width = (max(meter.text_width(line, size, True, MEASURE_FONT)
                     for line in cell["text"].splitlines() or [""])
                 + 2 * CELL_MARGIN_PT + 3) * 20
        if cell["span"] == 1:
            singles[start].append(width)
        else:
            spanned.append((start, cell["span"], width))
    need = [percentile_need(values, NEED_PERCENTILE) for values in singles]
    for start, span, width in spanned:
        last = start + span - 1
        need[last] = max(need[last], width - sum(
            min(max(need[c], COLUMN_RANGES[c][0]), COLUMN_RANGES[c][1]) for c in range(start, last)))
    return fit_widths(need, COLUMN_RANGES, GRID_TOTAL)


def _tune_grid(rows, grid, half, head_half):
    """بحث محلي صغير: ينقل GRID_STEP بين عمودين طالما قلّ ارتفاع الجدول المقدَّر
    (فتقلّ الأسطر الملتفّة)، مع بقاء كل عمود داخل مدى الأرشيف والمجموع ثابتًا."""
    best = _measure(rows, [w / 20 for w in grid], half, head_half)
    for _ in range(GRID_PASSES):
        improved = False
        for give in range(len(grid)):
            for take in range(len(grid)):
                if give == take:
                    continue
                trial = list(grid)
                trial[give] -= GRID_STEP
                trial[take] += GRID_STEP
                if (trial[give] < COLUMN_RANGES[give][0] or trial[take] > COLUMN_RANGES[take][1]):
                    continue
                height = _measure(rows, [w / 20 for w in trial], half, head_half)
                if height < best - .01:
                    best, grid, improved = height, trial, True
        if not improved:
            break
    return grid, best


def _choose_size(rows):
    """يرجع (half, head_half, total, usable, grid): أكبر مقاس خط يتسع في صفحة،
    وعرض الأعمدة محسوب من نصوص اليوم نفسها عند ذلك المقاس."""
    usable = PAGE_HEIGHT_PT - TABLE_TOP_PT - TRAILING_PT
    cap = _size_cap_half(len(rows))
    total, grid = 0.0, None
    for half in FONT_SIZES_HALF:
        if half > cap:
            continue
        head_half = 24 if half in (22, 24) else half
        grid = _content_grid(rows, half)
        total = _measure(rows, [w / 20 for w in grid], half, head_half)
        if total > usable * FIT_TARGET:
            grid, total = _tune_grid(rows, grid, half, head_half)
        if total <= usable * FIT_TARGET:
            return half, head_half, total, usable, grid
    # لا مقاس يحقق الهدف: نستخدم أصغر مقاس حقيقي (8pt) — التقدير مجرد دليل
    # والملفات الحقيقية تُعدّل يدويًا؛ نرفض فقط لو التقدير مستحيل بوضوح.
    if total <= usable * IMPOSSIBLE_RATIO:
        return half, head_half, total, usable, grid
    raise PageFitError("تعذر احتواء اليومية في صفحة واحدة (نسبة تقديرية %.2f)" % (total / usable))


def _title_pieces(day):
    d = date.fromisoformat(day)
    return ["الخدمات عن يوم", " ", WEEKDAY_BY_INDEX[d.weekday()], " ", str(d.day), "/",
            str(d.month), f"/{d.year}م"]


def _set_title(document, day):
    """نص الهيدر في runs القالب نفسها (Sultan bold 18pt مسطّر) — النص فقط يتغيّر."""
    paragraph = document.sections[0].header.paragraphs[0]
    runs = paragraph.runs
    try:
        pieces = _title_pieces(day)
    except ValueError:
        pieces = [str(day)]
    for run, text in zip(runs, pieces):
        run.text = text
    for extra in runs[len(pieces):]:
        extra._r.getparent().remove(extra._r)


def clinic_search_ids(data, day):
    """معرّفات أعضاء مجموعتي «طبي» (العيادة) و«بحث» في هذا اليوم."""
    from .constants import ROLE_MEDICAL, ROLE_SEARCH
    from .dated import groups_on
    groups = groups_on(data, day)
    return set(groups.get(ROLE_MEDICAL) or []) | set(groups.get(ROLE_SEARCH) or [])


def strip_clinic_search(board, excluded_ids):
    """نسخة من اليومية بلا العيادة والبحث لملف Word.

    تُحذف: صفوف الضباط (راحات/خارج/عمل بالإدارة/صافي/...) لأعضاء المجموعتين،
    وصفوف الخدمات ذات التصنيف «طبية»، ويُزال هؤلاء الضباط من قوائم ضباط/قادة
    الخدمات والأهداف والفترات الثابتة (تبقى الخدمة نفسها شاغرة)."""
    excluded = set(excluded_ids or ())
    sections = []
    for section in board.get("sections") or []:
        rows = []
        for row in section.get("rows") or []:
            if row.get("kind") == "طبية":
                continue
            if row.get("id") in excluded and "officers" not in row:
                continue
            row = dict(row)
            for key in ("officers", "commander", "personnel"):
                if isinstance(row.get(key), list):
                    row[key] = [p for p in row[key] if (p or {}).get("id") not in excluded]
            rows.append(row)
        sections.append({**section, "rows": rows})
    return {**board, "sections": sections}


def build_docx(board, exclude_ids=()):
    """يومية تفصيلية من قالب نسخة ملف أرشيف حقيقي: الصفوف تُبنى من البيانات.

    `exclude_ids`: ضباط العيادة/البحث الذين لا يظهرون في ملف Word."""
    if exclude_ids:
        board = strip_clinic_search(board, exclude_ids)
    document = Document(TEMPLATE)
    _set_title(document, board.get("date") or "")
    table = document.tables[0]
    protos = _prototypes(table)
    rows = _latest_content(board)
    half, head_half, total, usable, grid = _choose_size(rows)
    for col, width in zip(table._tbl.tblGrid.findall(qn("w:gridCol")), grid):
        col.set(qn("w:w"), str(width))
    for tr in list(table._tbl.tr_lst):
        table._tbl.remove(tr)
    for index, row in enumerate(rows):
        table._tbl.append(_build_tr(row, grid, protos, half, head_half, index == 1))
    order_xml_children(document)
    LAST_FIT.clear()
    LAST_FIT.update(scale=round(half / 24, 2), grid=list(grid), ratio=total / usable, total_pt=total,
                    usable_pt=usable, size_half_points=half, rows=len(rows))
    buf = BytesIO()
    document.save(buf)
    buf.seek(0)
    return buf
