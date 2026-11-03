"""تصدير ورقة ملء خط التشكيل: كل خدمة عنوان وتحتها خانة لكل مجند بعدد القوام."""
from io import BytesIO

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_ALIGN_VERTICAL, WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

from .board_export import order_xml_children, set_run_font
from .export_fit import PageFitError, TextMeter

LAST_FIT = {}
FONT = "Bahnschrift SemiBold"
LINE_FACTOR = 1.3        # ارتفاع السطر كنسبة من حجم الخط (ثابت EXACTLY عشان الملاءمة تبقى مضمونة)
ROW_PAD = .25            # مسافة رأسية جوه كل صف كنسبة من حجم الخط
GAP_PT = 8              # عرض العمود الفاصل بين الأقسام
MAX_SIZE, MIN_SIZE = 14.0, 6.5
BIG_STRENGTH = 15        # الخدمة اللي قوامها 15 أو أكتر بتروح الصفحة المنفصلة
HEADERS = ("الاسم", "التسليح", "رقم السلاح")
THICK = 18               # 2.25pt (بالثُمن نقطة) الحد الفاصل بين مجموعات اللوري
COLORS = {"header": "BFBFBF", "title": "DEEAF6", "section": "F4B183"}


# ---------- XML helpers ----------

def _child(parent, tag):
    node = parent.find(qn("w:" + tag))
    if node is None:
        node = OxmlElement("w:" + tag)
        parent.append(node)
    return node


def _bidi_document(document):
    for section in document.sections:
        if section._sectPr.find(qn("w:bidi")) is None:
            section._sectPr.append(OxmlElement("w:bidi"))


def _bidi_table(table):
    props = table._tbl.tblPr
    if props.find(qn("w:bidiVisual")) is None:
        props.append(OxmlElement("w:bidiVisual"))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    _child(props, "tblLayout").set(qn("w:type"), "fixed")


def _set_grid(table, widths):
    for col, width in zip(table._tbl.tblGrid.findall(qn("w:gridCol")), widths):
        col.set(qn("w:w"), str(max(1, int(round(width * 20)))))


def _cell_margins(cell, horizontal=60):
    mar = _child(cell._tc.get_or_add_tcPr(), "tcMar")
    for side, value in (("top", 0), ("bottom", 0), ("start", horizontal), ("end", horizontal)):
        node = _child(mar, side)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def _borders(cell, *, top=4, bottom=4, sides=4):
    """حدود الخلية بسماكة بالثُمن نقطة؛ 0 = من غير حد."""
    borders = _child(cell._tc.get_or_add_tcPr(), "tcBorders")
    for side, size in (("top", top), ("start", sides), ("left", sides), ("bottom", bottom),
                       ("end", sides), ("right", sides)):
        node = _child(borders, side)
        if size:
            node.set(qn("w:val"), "single")
            node.set(qn("w:sz"), str(size))
            node.set(qn("w:space"), "0")
            node.set(qn("w:color"), "000000")
        else:
            node.set(qn("w:val"), "nil")


def _shade(cell, fill):
    shd = _child(cell._tc.get_or_add_tcPr(), "shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)


def _set_text(cell, text, size, *, bold=False, center=True):
    """center=False يعني من أول السطر (اليمين) في فقرة RTL: من غير jc خالص زي ملف الأرشيف،
    لأن Word بيقرا left/right في الفقرة العربي بالعكس."""
    cell.text = str(text or "")
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    _cell_margins(cell)
    for paragraph in cell.paragraphs:
        if center:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        ppr = paragraph._p.get_or_add_pPr()
        if ppr.find(qn("w:bidi")) is None:
            ppr.append(OxmlElement("w:bidi"))
        fmt = paragraph.paragraph_format
        fmt.space_before = fmt.space_after = Pt(0)
        fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        fmt.line_spacing = Pt(size * LINE_FACTOR)
        for run in paragraph.runs:
            set_run_font(run, FONT, size, bold)
            rpr = run._r.get_or_add_rPr()
            if rpr.find(qn("w:rtl")) is None:
                rpr.append(OxmlElement("w:rtl"))


def _paragraph(document, text, size, *, page_break=False, before=0, after=4):
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph._p.get_or_add_pPr().append(OxmlElement("w:bidi"))
    fmt = paragraph.paragraph_format
    fmt.page_break_before = page_break
    fmt.space_before, fmt.space_after = Pt(before), Pt(after)
    fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    fmt.line_spacing = Pt(size * LINE_FACTOR)
    run = paragraph.add_run(text)
    set_run_font(run, FONT, size, True)
    run._r.get_or_add_rPr().append(OxmlElement("w:rtl"))
    return paragraph


# ---------- المحتوى ----------

def _block_rows(block):
    title = block["title"]
    if block["kind"] == "emergency":
        title = f"{title} ({block['time'] or 'بدون ميعاد'})"
    rows = [{"type": "title", "text": title}]
    # عدد الخانات = القوام دايمًا، حتى لو التسليح ناقص.
    weapons = list(block.get("weapons") or [])
    rows.extend({"type": "slot", "values": [f"{i}-", weapons[i - 1] if i <= len(weapons) else "", ""]}
                for i in range(1, int(block.get("count") or 0) + 1))
    if block.get("group_end"):
        # آخر صف في مجموعة اللوري: حد سفلي سميك يفصلها عن اللي بعدها.
        rows[-1] = {**rows[-1], "thick": True}
    return rows


def _units(dto):
    """وحدات مترتبة، كل وحدة قايمة صفوف. عنوان الطوارئ وحدة لوحده."""
    units, emergency_seen = [], False
    for block in dto.get("blocks") or []:
        if (dto["shift"] == "morning" and block["kind"] == "emergency" and not emergency_seen
                and not dto.get("big_page")):
            units.append([{"type": "section", "text": "خدمات طارئة قبل 12ظ"}])
            emergency_seen = True
        units.append(_block_rows(block))
    return units


def _cut_big_units(units, limit):
    """خدمة قوامها أكبر من عمود كامل بتتقسم، والجزء التاني عنوانه «(تابع)»."""
    out = []
    for unit in units:
        if len(unit) <= limit or unit[0]["type"] != "title":
            out.append(unit)
            continue
        title, slots = unit[0], unit[1:]
        step = max(1, limit - 1)
        for start in range(0, len(slots), step):
            head = title if start == 0 else {"type": "title", "text": f"{title['text']} (تابع)"}
            out.append([head] + slots[start:start + step])
    return out


def _split_panes(units, sets):
    """أقل ارتفاع قسم (بعدد الصفوف) مع الحفاظ على ترتيب الخدمات؛ كل قسم بيبدأ برؤوس الأعمدة."""
    total = sum(len(unit) for unit in units)
    capacity = max(1, (total + sets - 1) // sets)
    while True:
        panes, used = [[]], 0
        for unit in _cut_big_units(units, capacity):
            if panes[-1] and used + len(unit) > capacity:
                panes.append([])
                used = 0
            panes[-1].append(unit)
            used += len(unit)
        if len(panes) <= sets:
            panes += [[] for _ in range(sets - len(panes))]
            return [[{"type": "header"}] + [row for unit in pane for row in unit] if pane else []
                    for pane in panes]
        capacity += 1


# ---------- الملاءمة ----------

def _widths(page_width, sets):
    """الاسم بيتكتب بالإيد فواخد أكبر مساحة."""
    pane = (page_width - GAP_PT * (sets - 1)) / sets
    return [pane * .50, pane * .26, pane * .24]


def _row_height(row, size, pane_width, meter):
    line = size * LINE_FACTOR
    if row["type"] in ("title", "section"):
        # اسم الخدمة بيلف على كذا سطر والخلية تطول بدل ما الخط يصغر.
        room = max(1.0, (pane_width - 8) * .85)
        lines = max(1, len(meter.wrap_lines(row["text"], room, size, True, FONT)))
        return lines * line + ROW_PAD * size
    return line + ROW_PAD * size


def _heights(panes, widths, size, meter):
    pane_width = sum(widths)
    base = size * (LINE_FACTOR + ROW_PAD)
    return [max((_row_height(pane[index], size, pane_width, meter)
                 for pane in panes if index < len(pane)), default=base)
            for index in range(max(len(pane) for pane in panes))]


SETS = 4  # ورقة بالعرض فيها 4 جداول جنب بعض (طلب المالك)


def _fit(dto, page_width, usable_height):
    """أكبر خط (لحد 12) يخلّي الجداول الأربعة تدخل الصفحة."""
    meter = TextMeter()
    widths = _widths(page_width, SETS)
    panes = _split_panes(_units(dto), SETS)
    size = MAX_SIZE
    while size >= MIN_SIZE:
        heights = _heights(panes, widths, size, meter)
        if sum(heights) <= usable_height:
            return SETS, widths, panes, size, heights, sum(heights) / usable_height
        size -= .5
    raise PageFitError("تعذر احتواء خط التشكيل في صفحة واحدة؛ راجع عدد الخدمات أو أسماءها.")


# ---------- الكتابة ----------

_METER = TextMeter()


def _fitted(text, width, size, bold=False):
    """النص القصير (رأس عمود/تسليح) سطر واحد: لو مش داخل بنصغّر خطه هو بس."""
    room = max(1.0, (width - 8) * .75)
    need = _METER.text_width(str(text or ""), size, bold, FONT)
    return size if need <= room else max(5.0, int(size * room / need * 2) / 2)


def _write_pane_row(cells, item, size, widths):
    kind = item["type"] if item else "blank"
    if kind == "slot":
        for index, (cell, value, width) in enumerate(zip(cells, item["values"], widths)):
            # خانة الاسم من أول السطر عشان يتكتب جنب الرقم؛ الباقي في النص.
            _set_text(cell, value, _fitted(value, width, size), center=index != 0)
            _borders(cell, top=2, bottom=THICK if item.get("thick") else 2)
    elif kind == "header":
        for cell, value, width in zip(cells, HEADERS, widths):
            _set_text(cell, value, _fitted(value, width, size, True), bold=True)
            _shade(cell, COLORS["header"])
            _borders(cell, top=12, bottom=8)
    elif kind in ("title", "section"):
        merged = cells[0].merge(cells[-1])
        _set_text(merged, item["text"], size, bold=True)
        _shade(merged, COLORS[kind])
        _borders(merged, top=12, bottom=THICK if item.get("thick") else 4)
    else:
        for cell in cells:
            _set_text(cell, "", size)
            _borders(cell, top=0, bottom=0, sides=0)


def _add_sheet(document, dto, heading, page_break=False):
    """صفحة كاملة: عنوان + جدول الخانات + سطر الإجمالي."""
    section = document.sections[0]
    _paragraph(document, heading, 14, page_break=page_break)
    page_width = section.page_width.pt - section.left_margin.pt - section.right_margin.pt
    page_height = section.page_height.pt - section.top_margin.pt - section.bottom_margin.pt
    usable = page_height - (14 * LINE_FACTOR + 4) - (10 * LINE_FACTOR + 4) - 10
    sets, widths, panes, size, heights, ratio = _fit(dto, page_width, usable)

    grid = []
    for index in range(sets):
        if index:
            grid.append(GAP_PT)
        grid.extend(widths)
    table = document.add_table(rows=len(heights), cols=len(grid))
    _bidi_table(table)
    _set_grid(table, grid)
    for row_index, (row, height) in enumerate(zip(table.rows, heights)):
        row.height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
        row.height = Pt(height)
        cells = row.cells
        for cell, width in zip(cells, grid):
            cell.width = Pt(width)
        col = 0
        for pane_index, pane in enumerate(panes):
            if pane_index:
                _set_text(cells[col], "", size)
                _borders(cells[col], top=0, bottom=0, sides=0)
                col += 1
            _write_pane_row(cells[col:col + 3], pane[row_index] if row_index < len(pane) else None, size, widths)
            col += 3
    blocks = dto.get("blocks") or []
    _paragraph(document, f"الإجمالي: {len(blocks)} خدمة / {sum(int(b['count']) for b in blocks)} مجند",
               10, before=4, after=0)
    return {"size_pt": size, "ratio": ratio, "halves": sets}


def build_docx(dto):
    if dto.get("shift") == "night":
        # الليل على قالب ملف الأرشيف نفسه (طلب المالك)، مش التنسيق الجديد.
        from . import formation_night_export
        output = formation_night_export.build_docx(dto)
        LAST_FIT.clear()
        LAST_FIT.update(formation_night_export.LAST_FIT)
        return output
    document = Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = Inches(11.69), Inches(8.27)
    section.left_margin = section.right_margin = Inches(.3)
    section.top_margin = section.bottom_margin = Inches(.3)
    _bidi_document(document)
    blocks = dto.get("blocks") or []
    small = [b for b in blocks if int(b.get("count") or 0) < BIG_STRENGTH]
    big = [b for b in blocks if int(b.get("count") or 0) >= BIG_STRENGTH]
    fits = [_add_sheet(document, {**dto, "blocks": small}, dto["title"])]
    if big:
        # صفحة منفصلة للخدمات الكبيرة؛ الميعاد مكتوب جنب اسم كل خدمة فمش محتاجين عنوان الطوارئ.
        fits.append(_add_sheet(document, {**dto, "blocks": big, "big_page": True},
                               dto["title"].replace(" عن يوم", " (الخدمات الكبيرة) عن يوم", 1),
                               page_break=True))
    order_xml_children(document)
    LAST_FIT.clear()
    LAST_FIT.update({"page_count": len(fits), "size_pt": min(f["size_pt"] for f in fits),
                     "ratio": max(f["ratio"] for f in fits), "halves": max(f["halves"] for f in fits),
                     "pages": fits})
    output = BytesIO()
    document.save(output)
    output.seek(0)
    return output
