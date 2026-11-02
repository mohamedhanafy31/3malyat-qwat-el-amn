"""كشف Word رسمي ببيانات الضباط أو الأفراد اللي على القوة."""
import re
from datetime import date
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Emu, Pt, RGBColor
from lxml import etree

from .constants import PERSONNEL_FAMILIES
from .board_export import _ORDERS, order_xml_children
from .dated import command_on
from .export_fit import (
    apply_fit_to_docx_table, docx_table_spec, estimate_table_height, fit_table, usable_height_pt,
)
from .text import norm


BODY_FONT = "Arial"
HEADING_FONT = "Sultan bold"
TITLES = {"officers": "كشف بيانات السادة الضباط", "personnel": "كشف بيانات الأفراد"}
BLACK = "000000"
TEMPLATE = Path(__file__).with_name("docx_templates") / "duty_roster.docx"
PERSONNEL_FAMILY_ORDER = [
    "أمين", "معاون", "مساعد", "رقيب", "مراقب", "مندوب", "عريف", "شرطي", "جندي",
]
# (المفتاح، العنوان، دالة القيمة، العرض بالسنتيمتر) من اليمين للشمال.
COLUMNS = {
    "officers": [
        (None, "م", None, 0.75),
        ("rank", "الرتبة", lambda p: p.get("role"), 1.6),
        ("name", "الاسم", lambda p: p.get("name"), 4.6),
        ("code", "الأقدمية", lambda p: p.get("code"), 2.1),
        ("post", "العمل المسند", lambda p: p.get("post"), 3.6),
        ("rest", "نظام الراحة", lambda p: _rest(p), 2.6),
        ("phone", "الهاتف", lambda p: p.get("phone"), 2.75),
    ],
    "personnel": [
        (None, "م", None, 0.75),
        ("rank", "الدرجة", lambda p: p.get("role"), 2.6),
        ("name", "الاسم", lambda p: p.get("name"), 4.6),
        ("code", "الكود", lambda p: p.get("code"), 1.7),
        ("post", "العمل", lambda p: p.get("post"), 2.2),
        ("address", "العنوان", lambda p: p.get("address"), 3.4),
        ("phone", "الهاتف", lambda p: _phones(p), 2.75),
    ],
}
USABLE_WIDTH_CM = 19.4


def _rest(person):
    system = str(person.get("rest_system") or "").strip()
    day = str(person.get("rest_day") or "").strip()
    return f"{system} ({day})" if system and day and system != "—" else system


def _phones(person):
    phones = [person.get("phone"), *(person.get("other_phones") or [])]
    return "\n".join(str(phone).strip() for phone in phones if str(phone or "").strip())


def _text(value):
    lines = re.sub(r"ـ", "", str(value or "")).split("\n")
    return "\n".join(" ".join(line.split()) for line in lines).strip()


def export_columns(category):
    """الأعمدة القابلة للاختيار للواجهة."""
    return [{"key": key, "title": title} for key, title, _fn, _width in COLUMNS[category]
            if key is not None]


def selected_columns(category, selected=None):
    """يحافظ على ترتيب الكشف، مهما كان ترتيب الطلب."""
    wanted = None if selected is None else set(selected)
    columns = [column for column in COLUMNS[category]
               if column[0] is None or wanted is None or column[0] in wanted]
    if len(columns) <= 1:
        return columns
    serial = columns[0]
    body_total = sum(column[3] for column in columns[1:])
    available = USABLE_WIDTH_CM - serial[3]
    return [serial, *((key, title, fn, width * available / body_total)
                      for key, title, fn, width in columns[1:])]


def _active(data, category):
    return [person for person in data.get(category) or []
            if (person.get("status") or "active") == "active"]


def rows(data, category, columns=None):
    """صفوف البيانات القديمة من غير فواصل المجموعات."""
    columns = columns or selected_columns(category)
    return [[str(index)] + [_text(fn(person)) for _key, _title, fn, _width in columns[1:]]
            for index, person in enumerate(_active(data, category), 1)]


def file_name(category, day):
    value = date.fromisoformat(day)
    kind = "الضباط" if category == "officers" else "الأفراد"
    return f"بيانات {kind} {value.day}-{value.month}-{value.year}.docx"


def _append(parent, tag, **attrs):
    node = OxmlElement(tag)
    for key, value in attrs.items():
        node.set(qn(f"w:{key}"), str(value))
    parent.append(node)
    return node


def _insert_before(parent, node, successors):
    successor_tags = {qn(f"w:{name}") for name in successors}
    for index, child in enumerate(parent):
        if child.tag in successor_tags:
            parent.insert(index, node)
            return node
    parent.append(node)
    return node


def _order_tree(root):
    """ترتيب عناصر XML في الأجزاء اللي مش جوه body، زي الفوتر."""
    for tag, order in _ORDERS.items():
        rank = {qn("w:" + name): index for index, name in enumerate(order)}
        for element in root.iter(qn("w:" + tag)):
            children = list(element)
            ordered = sorted(children, key=lambda child: rank.get(child.tag, len(rank)))
            if ordered != children:
                for child in children:
                    element.remove(child)
                for child in ordered:
                    element.append(child)


def _run_font(run, size, *, bold=False, color=BLACK, font=BODY_FONT, ltr=False):
    run.font.name = font
    run.font.size = Pt(size)
    run.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    rpr = run._r.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
        fonts.set(qn(f"w:{attr}"), font)
    for tag, value in (("w:sz", round(size * 2)), ("w:szCs", round(size * 2)),
                       ("w:b", int(bold)), ("w:bCs", int(bold))):
        node = rpr.find(qn(tag))
        if node is None:
            node = _append(rpr, tag)
        node.set(qn("w:val"), str(value))
    rtl = rpr.find(qn("w:rtl"))
    if rtl is None:
        rtl = _append(rpr, "w:rtl")
    rtl.set(qn("w:val"), "0" if ltr else "1")
    if ltr:
        lang = rpr.find(qn("w:lang"))
        if lang is None:
            lang = _append(rpr, "w:lang")
        lang.set(qn("w:val"), "en-US")


def _paragraph(paragraph, *, align=WD_ALIGN_PARAGRAPH.CENTER, bidi=True):
    paragraph.alignment = align
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.line_spacing = 1
    ppr = paragraph._p.get_or_add_pPr()
    if bidi and ppr.find(qn("w:bidi")) is None:
        _append(ppr, "w:bidi")
    return paragraph


def _set_text(cell, text, *, size=9, bold=False, color=BLACK,
              align=WD_ALIGN_PARAGRAPH.CENTER, font=BODY_FONT, ltr=False):
    cell.text = ""
    for index, line in enumerate(str(text or "").split("\n")):
        paragraph = cell.paragraphs[0] if index == 0 else cell.add_paragraph()
        _paragraph(paragraph, align=align)
        run = paragraph.add_run(line)
        _run_font(run, size, bold=bold, color=color, font=font, ltr=ltr)
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER


def _cell_borders(cell, *, color=BLACK, size=8, value="single",
                  sides=("top", "left", "bottom", "right")):
    tcpr = cell._tc.get_or_add_tcPr()
    borders = tcpr.find(qn("w:tcBorders"))
    if borders is None:
        borders = _append(tcpr, "w:tcBorders")
    for side in sides:
        node = borders.find(qn(f"w:{side}"))
        if node is None:
            node = _append(borders, f"w:{side}")
        node.set(qn("w:val"), value)
        node.set(qn("w:sz"), str(size))
        node.set(qn("w:color"), color)


def _table_borders(table):
    tblpr = table._tbl.tblPr
    borders = tblpr.find(qn("w:tblBorders"))
    if borders is None:
        borders = _append(tblpr, "w:tblBorders")
    outer_sides = {"top", "left", "bottom", "right"}
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = borders.find(qn(f"w:{side}"))
        if node is None:
            node = _append(borders, f"w:{side}")
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), "12" if side in outer_sides else "4")
        node.set(qn("w:color"), BLACK)


def _table_setup(table, widths, *, rtl=True, margins=80):
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    tblpr = table._tbl.tblPr
    if rtl and tblpr.find(qn("w:bidiVisual")) is None:
        _append(tblpr, "w:bidiVisual")
    layout = tblpr.find(qn("w:tblLayout"))
    if layout is None:
        layout = _append(tblpr, "w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    cell_mar = tblpr.find(qn("w:tblCellMar"))
    if cell_mar is None:
        cell_mar = _append(tblpr, "w:tblCellMar")
    for side in ("top", "left", "bottom", "right"):
        node = cell_mar.find(qn(f"w:{side}"))
        if node is None:
            node = _append(cell_mar, f"w:{side}")
        node.set(qn("w:w"), "40" if side in {"top", "bottom"} else str(margins))
        node.set(qn("w:type"), "dxa")
    for grid, width in zip(table._tbl.tblGrid.findall(qn("w:gridCol")), widths):
        grid.set(qn("w:w"), str(Cm(width).twips))


def _row_height(row, cm, rule="atLeast"):
    trpr = row._tr.get_or_add_trPr()
    _append(trpr, "w:trHeight", val=Cm(cm).twips, hRule=rule)
    if trpr.find(qn("w:cantSplit")) is None:
        _append(trpr, "w:cantSplit")


def _no_wrap(cell):
    tcpr = cell._tc.get_or_add_tcPr()
    if tcpr.find(qn("w:noWrap")) is None:
        _append(tcpr, "w:noWrap")


def _family(role):
    value = norm(str(role or ""))
    for family in PERSONNEL_FAMILY_ORDER:
        if family in PERSONNEL_FAMILIES and value.startswith(norm(family)):
            return family
    return "أخرى"


def _summary_text(people, category):
    if category == "officers":
        leaders = {"لواء", "عميد", "عقيد", "مقدم"}
        aides = {"رائد", "نقيب", "ملازم أول", "ملازم"}
        return (f"إجمالي القوة: {len(people)} ضابط "
                f"(قادة {sum(p.get('role') in leaders for p in people)} — "
                f"أعوان {sum(p.get('role') in aides for p in people)})")
    counts = []
    for family in [*PERSONNEL_FAMILY_ORDER, "أخرى"]:
        count = sum(_family(person.get("role")) == family for person in people)
        if count:
            counts.append(f"{family}: {count}")
    details = " — ".join(counts) or "لا يوجد"
    return f"إجمالي القوة: {len(people)} فرد ({details})"


def _template_logos():
    """بيقرأ الشعارين وأبعادهم من نفس قالب يومية الضباط."""
    namespaces = {
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    with ZipFile(TEMPLATE) as package:
        root = etree.fromstring(package.read("word/document.xml"))
        rels_root = etree.fromstring(package.read("word/_rels/document.xml.rels"))
        relationships = {node.get("Id"): node.get("Target") for node in rels_root}
        logos = []
        for order, drawing in enumerate(root.xpath("//w:drawing", namespaces=namespaces)):
            embeds = drawing.xpath(".//a:blip/@r:embed", namespaces=namespaces)
            extents = drawing.xpath(".//wp:extent", namespaces=namespaces)
            if not embeds or not extents:
                continue
            offsets = drawing.xpath(".//wp:positionH/wp:posOffset/text()",
                                    namespaces=namespaces)
            target = relationships[embeds[0]]
            extent = extents[0]
            logos.append((int(offsets[0]) if offsets else order,
                          package.read(f"word/{target}"),
                          int(extent.get("cx")), int(extent.get("cy"))))
    if len(logos) != 2:
        raise ValueError("قالب يومية الضباط لازم يحتوي على شعارين.")
    return sorted(logos, key=lambda item: item[0])


def _letterhead(document, people, category, value):
    table = document.add_table(rows=1, cols=3)
    widths = [3.2, 13.0, 3.2]
    _table_setup(table, widths, rtl=False, margins=20)
    for cell, width in zip(table.rows[0].cells, widths):
        cell.width = Cm(width)

    left, title, right = table.rows[0].cells
    left_logo, right_logo = _template_logos()
    for cell, logo, align in ((left, left_logo, WD_ALIGN_PARAGRAPH.LEFT),
                              (right, right_logo, WD_ALIGN_PARAGRAPH.RIGHT)):
        cell.text = ""
        paragraph = _paragraph(cell.paragraphs[0], align=align, bidi=False)
        _offset, image, width, height = logo
        paragraph.add_run().add_picture(BytesIO(image), width=Emu(width), height=Emu(height))
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

    title.text = ""
    p = _paragraph(title.paragraphs[0])
    title_run = p.add_run(f"{TITLES[category]} بإدارة قوات أمن السويس")
    _run_font(title_run, 14, bold=True, font=HEADING_FONT)
    title_run.underline = True
    p = _paragraph(title.add_paragraph())
    _run_font(p.add_run(f"حتى تاريخ {value.day}/{value.month}/{value.year}م"), 10,
              bold=True, font=HEADING_FONT)

    summary = document.add_paragraph()
    _paragraph(summary)
    summary.paragraph_format.space_before = Pt(2)
    summary.paragraph_format.space_after = Pt(4)
    _run_font(summary.add_run(_summary_text(people, category)), 10, bold=True,
              font=HEADING_FONT)


def _field(paragraph, instruction, size):
    begin = paragraph.add_run()
    _run_font(begin, size, ltr=True)
    _append(begin._r, "w:fldChar", fldCharType="begin")
    code = paragraph.add_run()
    _run_font(code, size, ltr=True)
    instr = _append(code._r, "w:instrText")
    instr.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    instr.text = f" {instruction} "
    separate = paragraph.add_run()
    _run_font(separate, size, ltr=True)
    _append(separate._r, "w:fldChar", fldCharType="separate")
    result = paragraph.add_run("1")
    _run_font(result, size, ltr=True)
    end = paragraph.add_run()
    _run_font(end, size, ltr=True)
    _append(end._r, "w:fldChar", fldCharType="end")


def _footer(section, value):
    footer = section.footer
    footer.is_linked_to_previous = False
    table = footer.add_table(rows=1, cols=3, width=Cm(USABLE_WIDTH_CM))
    widths = [5.6, 8.2, 5.6]
    _table_setup(table, widths, margins=20)
    cells = table.rows[0].cells
    _set_text(cells[0], f"تاريخ الإصدار: {value.day}/{value.month}/{value.year}م", size=8,
              align=WD_ALIGN_PARAGRAPH.RIGHT)
    center = cells[1]
    center.text = ""
    paragraph = _paragraph(center.paragraphs[0])
    run = paragraph.add_run("صفحة ")
    _run_font(run, 8)
    _field(paragraph, "PAGE", 8)
    run = paragraph.add_run(" من ")
    _run_font(run, 8)
    _field(paragraph, "NUMPAGES", 8)
    _set_text(cells[2], "", size=8)
    for cell in cells:
        ppr = cell.paragraphs[0]._p.get_or_add_pPr()
        pbdr = _append(ppr, "w:pBdr")
        _append(pbdr, "w:top", val="single", sz="4", space="3", color=BLACK)


def _main_table(document, data, people, category, columns, day):
    widths = [column[3] for column in columns]
    table = document.add_table(rows=1, cols=len(columns))
    _table_setup(table, widths)
    _table_borders(table)
    for index, width in enumerate(widths):
        for cell in table.columns[index].cells:
            cell.width = Cm(width)

    header = table.rows[0]
    _row_height(header, .7, "exact")
    _append(header._tr.get_or_add_trPr(), "w:tblHeader")
    for index, (cell, (_key, heading, _fn, _width)) in enumerate(zip(header.cells, columns)):
        _set_text(cell, heading, size=9, bold=True, font=HEADING_FONT)
        _cell_borders(cell, size=12, value="double", sides=("bottom",))
        if index == 0 or columns[index][0] in {"rank", "code", "phone"}:
            _no_wrap(cell)

    command = command_on(data, day) if category == "officers" else {}
    command_by_id = {person_id: role for role, person_id in command.items() if person_id}
    for serial, person in enumerate(people, 1):
        row = table.add_row()
        _row_height(row, .6)
        is_command = person.get("id") in command_by_id
        values = []
        for key, _title, fn, _width in columns:
            if key is None:
                values.append(str(serial))
                continue
            value = _text(fn(person))
            if key == "post" and is_command:
                role = command_by_id[person.get("id")]
                value = f"{role} — {value}" if value else role
            values.append(value)
        for index, (cell, text) in enumerate(zip(row.cells, values)):
            key = columns[index][0]
            align = WD_ALIGN_PARAGRAPH.RIGHT if key == "name" else WD_ALIGN_PARAGRAPH.CENTER
            size = ({"rank": 7.75, "code": 7.5, "phone": 8.5}.get(key, 9)
                    if category == "personnel" else
                    {"rank": 8.5, "code": 8.5, "phone": 8.5}.get(key, 9))
            _set_text(cell, text, size=size, bold=key == "name",
                      align=align, ltr=key == "phone")
            if key is None or key in {"rank", "code", "phone"}:
                _no_wrap(cell)
    return table


# الترويسة (اللوجوهات + العنوان + سطر الإجمالي) والفوتر من مساحة الصفحة.
LETTERHEAD_PT = 175


def _fit_one_page(table, section, columns):
    """كشف الضباط لازم صفحة واحدة: الخط بحجمه الطبيعي والصفوف بتتمد تملا
    الصفحة؛ ولو مش هيكفي بس، نصغّر الخط بأداة الملاءمة."""
    rows, _widths = docx_table_spec(table, default_size=9)
    widths = [Cm(column[3]).pt for column in columns]
    rows = [[{**cell, "hmargins": 8} for cell in row] for row in rows]
    usable = (usable_height_pt(section) - LETTERHEAD_PT) * .82
    total, heights = estimate_table_height(rows, widths)
    if total > usable:
        fit = fit_table({"rows": rows, "grid_widths_pt": widths}, usable, target=1)
        apply_fit_to_docx_table(table, fit)
        heights = fit.heights_pt
    # ارتفاع موحّد يملا الصفحة؛ الصف اللي بيلف سطرين بس هو اللي Word يطوّله.
    single = min(heights[1:])
    wrapped = sum(height - single for height in heights[1:]) * .6   # التقدير بيبالغ في اللف
    floor = max(single, (usable - heights[0] - wrapped) / max(1, len(heights) - 1))
    for row in table.rows[1:]:
        node = row._tr.trPr.find(qn("w:trHeight"))
        node.set(qn("w:val"), str(round(floor * 20)))
        node.set(qn("w:hRule"), "atLeast")
        for paragraph in (p for cell in row.cells for p in cell.paragraphs):
            spacing = paragraph._p.pPr.find(qn("w:spacing"))
            if spacing is not None:
                spacing.set(qn("w:lineRule"), "auto")
                spacing.set(qn("w:line"), "240")


def build_docx(data, category, day, selected=None):
    columns = selected_columns(category, selected)
    document = Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.left_margin = section.right_margin = Cm(.8)
    section.top_margin = Cm(.7)
    section.bottom_margin = Cm(.9)
    section.header_distance = Cm(.3)
    section.footer_distance = Cm(.35)
    sectpr = section._sectPr
    if sectpr.find(qn("w:bidi")) is None:
        _insert_before(sectpr, OxmlElement("w:bidi"),
                       ("rtlGutter", "docGrid", "printerSettings", "sectPrChange"))
    settings = document.settings.element
    zoom = settings.find(qn("w:zoom"))
    if zoom is not None and zoom.get(qn("w:percent")) is None:
        zoom.set(qn("w:percent"), "100")

    value = date.fromisoformat(day)
    people = _active(data, category)
    _letterhead(document, people, category, value)
    table = _main_table(document, data, people, category, columns, day)
    if category == "officers":
        _fit_one_page(table, section, columns)
    _footer(section, value)
    order_xml_children(document)
    _order_tree(section.footer._element)

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()
