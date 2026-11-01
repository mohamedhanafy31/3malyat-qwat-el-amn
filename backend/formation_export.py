"""تصدير ورقة ملء خط التشكيل، بنفس منطق ورقة الأرشيف."""
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
LINE_FACTOR = 1.3
GAP_PT = 10


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
    table.alignment = WD_TABLE_ALIGNMENT.RIGHT
    table.autofit = False
    _child(props, "tblLayout").set(qn("w:type"), "fixed")


def _cell_margins(cell, horizontal=2, vertical=0):
    tcpr = cell._tc.get_or_add_tcPr()
    mar = _child(tcpr, "tcMar")
    for side, value in (("top", vertical), ("bottom", vertical),
                        ("start", horizontal), ("end", horizontal)):
        node = mar.find(qn("w:" + side))
        if node is None:
            node = OxmlElement("w:" + side)
            mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def _no_borders(cell):
    tcpr = cell._tc.get_or_add_tcPr()
    borders = _child(tcpr, "tcBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = borders.find(qn("w:" + side))
        if node is None:
            node = OxmlElement("w:" + side)
            borders.append(node)
        node.set(qn("w:val"), "nil")


def _shade(cell, fill="D9EAD3"):
    tcpr = cell._tc.get_or_add_tcPr()
    shd = _child(tcpr, "shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)


def _set_text(cell, text, size, *, bold=False, no_wrap=False,
              align=WD_ALIGN_PARAGRAPH.CENTER):
    cell.text = str(text or "")
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    _cell_margins(cell)
    tcpr = cell._tc.get_or_add_tcPr()
    nowrap = tcpr.find(qn("w:noWrap"))
    if no_wrap and nowrap is None:
        tcpr.append(OxmlElement("w:noWrap"))
    for paragraph in cell.paragraphs:
        paragraph.alignment = align
        ppr = paragraph._p.get_or_add_pPr()
        if ppr.find(qn("w:bidi")) is None:
            ppr.append(OxmlElement("w:bidi"))
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0)
        paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        paragraph.paragraph_format.line_spacing = Pt(size * LINE_FACTOR)
        for run in paragraph.runs:
            set_run_font(run, FONT, size, bold)
            rpr = run._r.get_or_add_rPr()
            if rpr.find(qn("w:rtl")) is None:
                rpr.append(OxmlElement("w:rtl"))


def _widths(page_width, sets):
    """الاسم بيتكتب بالإيد فواخد أكبر مساحة، والتسليح ورقم السلاح عرض كفاية للكتابة."""
    pane = (page_width - GAP_PT * (sets - 1)) / sets
    return [pane * .5, pane * .25, pane * .25]


def _unit_rows(block, *, section=False):
    if section:
        return [{"type": "section", "text": "خدمات طارئة قبل 12ظ"}]
    title = block["title"]
    if block["kind"] == "emergency":
        title = f"{title} ({block['time'] or 'بدون ميعاد'})"
    rows = [{"type": "title", "text": title}]
    # عدد الخانات = القوام دايمًا، حتى لو التسليح ناقص.
    weapons = list(block.get("weapons") or [])
    rows.extend({"type": "slot", "values": [f"{i}-", weapons[i - 1] if i <= len(weapons) else "", ""]}
                for i in range(1, int(block.get("count") or 0) + 1))
    return rows


def _units(dto):
    blocks = dto.get("blocks") or []
    units = []
    emergency_seen = False
    for block in blocks:
        if (dto["shift"] == "morning" and block["kind"] == "emergency" and not emergency_seen
                and not dto.get("big_page")):
            units.append(("section", None))
            emergency_seen = True
        units.append(("block", block))
    return [(_unit_rows(value, section=True) if kind == "section" else _unit_rows(value),
             len(_unit_rows(value, section=True)) if kind == "section" else 1 + int(value["count"]))
            for kind, value in units]


def _cut_big_units(units, limit):
    """خدمة قوامها أكبر من عمود كامل (زي ندوة 80 مجند) بتتقسم، والجزء التاني عنوانه «(تابع)»."""
    out = []
    for items, rows in units:
        if rows <= limit or items[0]["type"] != "title":
            out.append((items, rows))
            continue
        title, slots = items[0], items[1:]
        step = max(1, limit - 1)
        for start in range(0, len(slots), step):
            head = title if start == 0 else {"type": "title", "text": f"{title['text']} (تابع)"}
            piece = [head] + slots[start:start + step]
            out.append((piece, len(piece)))
    return out


def _pack(units, capacity):
    """يملا الأعمدة بالترتيب، وكل عمود لحد capacity صف."""
    panes, used = [[]], 0
    for items, rows in units:
        if panes[-1] and used + rows > capacity:
            panes.append([]); used = 0
        panes[-1].append(items); used += rows
    return panes


def _split_panes(dto, sets):
    """أقل ارتفاع عمود ممكن مع الحفاظ على ترتيب الخدمات؛ الخدمة الضخمة بس هي اللي تتقسم."""
    units = _units(dto)
    total = sum(rows for _items, rows in units)
    capacity = max(1, (total + sets - 1) // sets)
    while True:
        panes = _pack(_cut_big_units(units, capacity), capacity)
        if len(panes) <= sets:
            return panes + [[] for _ in range(sets - len(panes))]
        capacity += 1


MAX_SIZE, MIN_SIZE = 12.0, 6.5


COMFORT_SIZE = 8.0  # لو عمودين بيدّوا خط أصغر من كده، نجرّب 3 أو 4 أعمدة بخط أكبر


def _fit(dto, page_width, usable_height):
    """ارتفاع الصف = المساحة المتاحة ÷ أطول عمود، والخط بيتناسب معاه (لحد 12pt)."""
    options = []
    for sets in (2, 3, 4):
        widths = _widths(page_width, sets)
        panes = _split_panes(dto, sets)
        max_rows = max((sum(len(unit) for unit in pane) for pane in panes), default=1) or 1
        row_height = min(MAX_SIZE * LINE_FACTOR + 2, usable_height * .98 / max_rows)
        size = min(MAX_SIZE, int((row_height - 1.5) / LINE_FACTOR * 2) / 2)
        option = (sets, widths, panes, size, row_height, max_rows * row_height / usable_height, max_rows)
        if size >= COMFORT_SIZE:
            return option
        if size >= MIN_SIZE:
            options.append(option)
    if options:
        return max(options, key=lambda item: (item[3], -item[0]))
    raise PageFitError("تعذر احتواء خط التشكيل في صفحة واحدة حتى بعد تقسيمه إلى أربعة أقسام؛ راجع عدد الخدمات أو أسماءها.")


def _title_size(text, width, size, meter):
    """العنوان سطر واحد دايمًا؛ لو طويل بنصغّر خطه هو بس."""
    need = meter.text_width(text, size, True, FONT)
    room = max(1.0, (width - 6) * .75)  # هامش أمان: المقياس التقريبي بيقلل عرض العربي شوية
    return size if need <= room else max(5.0, int(size * room / need * 2) / 2)


def _set_grid(table, widths):
    grid = table._tbl.tblGrid
    cols = grid.findall(qn("w:gridCol"))
    while len(cols) < len(widths):
        node = OxmlElement("w:gridCol")
        grid.append(node)
        cols.append(node)
    for col, width in zip(cols, widths):
        col.set(qn("w:w"), str(max(1, int(round(width * 20)))))


def _add_sheet(document, dto, heading, page_break=False):
    """صفحة كاملة: عنوان + جدول الخانات + سطر الإجمالي. بترجع بيانات الملاءمة."""
    section = document.sections[0]
    title = document.add_paragraph()
    title.paragraph_format.page_break_before = page_break
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    ppr = title._p.get_or_add_pPr()
    ppr.append(OxmlElement("w:bidi"))
    title.paragraph_format.space_after = Pt(4)
    title.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    title.paragraph_format.line_spacing = Pt(18.2)
    run = title.add_run(heading)
    set_run_font(run, FONT, 14, True)
    run._r.get_or_add_rPr().append(OxmlElement("w:rtl"))

    page_width = section.page_width.pt - section.left_margin.pt - section.right_margin.pt
    page_height = section.page_height.pt - section.top_margin.pt - section.bottom_margin.pt
    usable_height = page_height - (18.2 + 4) - (10 + 3) - 12
    sets, widths, panes, size, row_height, ratio, max_rows = _fit(dto, page_width, usable_height)
    meter = TextMeter()
    grid_widths = []
    for index in range(sets):
        if index:
            grid_widths.append(GAP_PT)
        grid_widths.extend(widths)
    total_rows = max_rows
    table = document.add_table(rows=total_rows, cols=len(grid_widths))
    _bidi_table(table)
    table.style = "Table Grid"
    _set_grid(table, grid_widths)
    flat_panes = [[row for unit in pane for row in unit] for pane in panes]
    for row_index, row in enumerate(table.rows):
        row.height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
        row.height = Pt(row_height)
        col = 0
        for pane_index, pane_rows in enumerate(flat_panes):
            if pane_index:
                gap = row.cells[col]
                _set_text(gap, "", size, no_wrap=True)
                _no_borders(gap)
                col += 1
            item = pane_rows[row_index] if row_index < len(pane_rows) else {"type": "blank"}
            if item["type"] == "slot":
                for index, (value, width) in enumerate(zip(item["values"], widths)):
                    cell = row.cells[col]
                    _set_text(cell, value, size, no_wrap=True,
                              align=WD_ALIGN_PARAGRAPH.RIGHT if index == 0 else WD_ALIGN_PARAGRAPH.CENTER)
                    cell.width = Pt(width)
                    col += 1
            elif item["type"] in {"title", "section"}:
                cell = row.cells[col]
                merged = cell
                for extra in range(1, 3):
                    merged = merged.merge(row.cells[col + extra])
                _set_text(merged, item["text"], _title_size(item["text"], sum(widths), size, meter),
                          bold=True, no_wrap=True, align=WD_ALIGN_PARAGRAPH.RIGHT)
                _shade(merged, "D9EAD3" if item["type"] == "title" else "EDEDED")
                col += 3
            else:
                for _ in widths:
                    cell = row.cells[col]
                    _set_text(cell, "", size, no_wrap=True)
                    _no_borders(cell)
                    col += 1

    total = document.add_paragraph()
    total.alignment = WD_ALIGN_PARAGRAPH.CENTER
    ppr = total._p.get_or_add_pPr(); ppr.append(OxmlElement("w:bidi"))
    total.paragraph_format.space_before = Pt(3)
    total.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    total.paragraph_format.line_spacing = Pt(10)
    blocks = dto.get("blocks") or []
    run = total.add_run(f"الإجمالي: {len(blocks)} خدمة / {sum(int(b['count']) for b in blocks)} مجند")
    set_run_font(run, FONT, min(size + 1, 10), True)
    run._r.get_or_add_rPr().append(OxmlElement("w:rtl"))
    return {"size_pt": size, "ratio": ratio, "halves": sets}


BIG_STRENGTH = 15  # الخدمة اللي قوامها 15 أو أكتر بتروح الصفحة المنفصلة


def build_docx(dto):
    document = Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width, section.page_height = Inches(8.27), Inches(11.69)
    section.left_margin = section.right_margin = Inches(.28)
    section.top_margin = section.bottom_margin = Inches(.25)
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
