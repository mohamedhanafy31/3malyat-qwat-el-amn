"""تصدير «أمر صرف وجبات جافة» إلى نموذج Word عربي RTL من صفحة واحدة."""
from datetime import date
from io import BytesIO

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt

from .assignments_roster_export import _signature_name, normalize_ooxml_order
from .export_fit import PageFitError, TextMeter


# The scan is an Egyptian official form.  Keep one font family throughout the
# document; Word has Simplified Arabic, while LibreOffice may substitute it.
FONT_NAME = "Simplified Arabic"
PAGE_WIDTH_MM = 210
PAGE_HEIGHT_MM = 297
MARGIN_MM = 12
CONTENT_WIDTH_MM = PAGE_WIDTH_MM - 2 * MARGIN_MM
BODY_FONT_PT = 17
TITLE_FONT_PT = 22
LETTERHEAD_FONT_PT = 12
TABLE_FONT_PT = 16
MIN_DATA_FONT_PT = 14
MIN_PARAGRAPH_FONT_PT = 15
HEADER_ROW_PT = 22.7  # approximately 0.8 cm
DATA_ROW_PT = 28.35  # approximately 1.0 cm
MIN_ROW_PT = 21.3  # approximately 0.75 cm
SIGNATURE_FONT_PT = 11   # مطابق لصناديق التوقيع في يومية التعيينات (Times New Roman عريض، 11)
SIGNATURE_FONT_NAME = "Times New Roman"
SIGNATURE_BOX_CM = 7.05   # 4000 twips كما في يومية التعيينات
SIGNATURE_PT = 60
GREY_BORDER = "7F7F7F"

_ARABIC_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def ar_digits(value):
    """Convert display numerals only; payload/API values stay Western digits."""
    return str(value or "").translate(_ARABIC_DIGITS)


def _set_attr(node, name, value):
    node.set(qn(f"w:{name}"), str(value))


def _ppr(paragraph):
    return paragraph._p.get_or_add_pPr()


def _bidi(paragraph):
    ppr = _ppr(paragraph)
    node = ppr.find(qn("w:bidi"))
    if node is None:
        node = OxmlElement("w:bidi")
        ppr.append(node)
    return paragraph


def _set_spacing(paragraph, before=0, after=0, line=None, line_twips=None):
    fmt = paragraph.paragraph_format
    fmt.space_before = Pt(before)
    fmt.space_after = Pt(after)
    if line is not None:
        fmt.line_spacing = Pt(line)
    if line_twips is not None:
        spacing = _ppr(paragraph).find(qn("w:spacing"))
        if spacing is None:
            spacing = OxmlElement("w:spacing")
            _ppr(paragraph).append(spacing)
        _set_attr(spacing, "line", line_twips)
        _set_attr(spacing, "lineRule", "exact")


def _set_toggle(rpr, tag, enabled):
    node = rpr.find(qn(f"w:{tag}"))
    if enabled:
        if node is None:
            node = OxmlElement(f"w:{tag}")
            rpr.append(node)
        _set_attr(node, "val", "1")
    elif node is not None:
        rpr.remove(node)


def _run(paragraph, text, *, size=12, bold=False, underline=False, font_name=None):
    # All emitted document text passes through this one helper, including
    # numerals, so the application payload remains unchanged.
    run = paragraph.add_run(ar_digits(text))
    font_name = font_name or FONT_NAME
    run.font.name = font_name
    run.font.size = Pt(size)
    run.bold = bold
    run.underline = underline
    rpr = run._r.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    for key in ("ascii", "hAnsi", "cs", "eastAsia"):
        _set_attr(fonts, key, font_name)
    # python-docx does not always emit the complex-script companions.  Add
    # them explicitly because Arabic Word rendering uses szCs/bCs.
    size_node = rpr.find(qn("w:sz"))
    if size_node is None:
        size_node = OxmlElement("w:sz")
        rpr.append(size_node)
    _set_attr(size_node, "val", round(size * 2))
    size_cs = rpr.find(qn("w:szCs"))
    if size_cs is None:
        size_cs = OxmlElement("w:szCs")
        rpr.append(size_cs)
    _set_attr(size_cs, "val", round(size * 2))
    _set_toggle(rpr, "b", bold)
    _set_toggle(rpr, "bCs", bold)
    if underline:
        underline_node = rpr.find(qn("w:u"))
        if underline_node is None:
            underline_node = OxmlElement("w:u")
            rpr.append(underline_node)
        _set_attr(underline_node, "val", "single")
    rtl = rpr.find(qn("w:rtl"))
    if rtl is None:
        rtl = OxmlElement("w:rtl")
        rpr.append(rtl)
    return run


def _paragraph(document, text="", *, size=12, bold=False, underline=False,
               align=WD_ALIGN_PARAGRAPH.CENTER, before=0, after=0,
               line=None, line_twips=None):
    paragraph = document.add_paragraph()
    paragraph.alignment = align
    _set_spacing(paragraph, before, after, line=line, line_twips=line_twips)
    _bidi(paragraph)
    if text:
        _run(paragraph, text, size=size, bold=bold, underline=underline)
    return paragraph


def _table_direction(table):
    tbl_pr = table._tbl.tblPr
    bidi = tbl_pr.find(qn("w:bidiVisual"))
    if bidi is None:
        bidi = OxmlElement("w:bidiVisual")
        tbl_pr.append(bidi)
    layout = tbl_pr.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        tbl_pr.append(layout)
    _set_attr(layout, "type", "fixed")
    tbl_width = tbl_pr.find(qn("w:tblW"))
    if tbl_width is None:
        tbl_width = OxmlElement("w:tblW")
        tbl_pr.append(tbl_width)
    _set_attr(tbl_width, "type", "dxa")
    _set_attr(tbl_width, "w", round(CONTENT_WIDTH_MM * 56.6929))


def _cell_borders(cell, *, color=GREY_BORDER, size=4, none=False):
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = borders.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            borders.append(node)
        _set_attr(node, "val", "nil" if none else "single")
        if not none:
            _set_attr(node, "sz", size)
            _set_attr(node, "color", color)


def _cell_width(cell, width_mm):
    tc_pr = cell._tc.get_or_add_tcPr()
    width = tc_pr.find(qn("w:tcW"))
    if width is None:
        width = OxmlElement("w:tcW")
        tc_pr.insert(0, width)
    _set_attr(width, "type", "dxa")
    _set_attr(width, "w", round(width_mm * 56.6929))


def _cell_margin(cell, *, right=0, left=0):
    tc_pr = cell._tc.get_or_add_tcPr()
    margins = tc_pr.find(qn("w:tcMar"))
    if margins is None:
        margins = OxmlElement("w:tcMar")
        tc_pr.append(margins)
    for side, value in (("top", 0), ("bottom", 0), ("start", left), ("end", right)):
        node = margins.find(qn(f"w:{side}"))
        if node is None:
            node = OxmlElement(f"w:{side}")
            margins.append(node)
        _set_attr(node, "type", "dxa")
        _set_attr(node, "w", value)


def _set_no_wrap(cell):
    tc_pr = cell._tc.get_or_add_tcPr()
    node = tc_pr.find(qn("w:noWrap"))
    if node is None:
        node = OxmlElement("w:noWrap")
        tc_pr.append(node)


def _cell_text(cell, text, *, size=TABLE_FONT_PT, bold=False,
               align=WD_ALIGN_PARAGRAPH.CENTER, right_padding=0, left_padding=0):
    cell.text = ""
    paragraph = cell.paragraphs[0]
    paragraph.alignment = align
    _set_spacing(paragraph, 0, 0, line=size + 2)
    _bidi(paragraph)
    if text not in (None, ""):
        _run(paragraph, text, size=size, bold=bold)
    _cell_margin(cell, right=right_padding, left=left_padding)
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER


def _merge_horizontal(cell, span):
    if span <= 1:
        return
    tc_pr = cell._tc.get_or_add_tcPr()
    grid = tc_pr.find(qn("w:gridSpan"))
    if grid is None:
        grid = OxmlElement("w:gridSpan")
        tc_pr.append(grid)
    _set_attr(grid, "val", span)


def _row_height(row, points, exact=True):
    tr_pr = row._tr.get_or_add_trPr()
    height = tr_pr.find(qn("w:trHeight"))
    if height is None:
        height = OxmlElement("w:trHeight")
        tr_pr.append(height)
    _set_attr(height, "val", round(points * 20))
    _set_attr(height, "hRule", "exact" if exact else "atLeast")


def _set_page_frame(section):
    sect_pr = section._sectPr
    borders = sect_pr.find(qn("w:pgBorders"))
    if borders is None:
        borders = OxmlElement("w:pgBorders")
        page_margin = sect_pr.find(qn("w:pgMar"))
        if page_margin is None:
            sect_pr.append(borders)
        else:
            sect_pr.insert(list(sect_pr).index(page_margin) + 1, borders)
    _set_attr(borders, "offsetFrom", "page")
    for side, value, size in (
        ("top", "thickThinSmallGap", 12),
        ("right", "single", 6),
        ("bottom", "single", 6),
        ("left", "single", 6),
    ):
        node = borders.find(qn(f"w:{side}"))
        if node is None:
            node = OxmlElement(f"w:{side}")
            borders.append(node)
        _set_attr(node, "val", value)
        _set_attr(node, "sz", size)
        _set_attr(node, "space", 24)
        _set_attr(node, "color", "000000")


SIGNATURE_RESERVED_PT = 2.6 * 72 / 2.54
MIN_COMPACT_ROW_PT = 17.6  # approximately 0.62 cm


def _layout_estimate(layout, fixed_count, emergency_count, emergency_enabled):
    """Conservative page budget: three body lines and a reserved signature block."""
    body_height = 3 * layout["paragraph_font"] * 1.3
    title_height = layout["title_line"] + layout["title_after"]

    def table_height(data_count):
        return (2 * layout["header_row"]
                + (data_count + 1) * layout["data_row"])

    used = (36 + layout["header_gap"] + title_height + body_height
            + layout["paragraph_after"] + table_height(fixed_count))
    if emergency_enabled:
        used += (2 * layout["separator_space"] + 4 + title_height
                 + body_height + layout["paragraph_after"]
                 + table_height(emergency_count))
    return used + SIGNATURE_RESERVED_PT


def _table_layout(payload):
    """Shrink emergency forms in order: rows, fonts, then vertical gaps."""
    fixed_count = len(list(payload.get("fixed_rows") or []))
    emergency_enabled = bool(payload.get("emergency_enabled"))
    emergency_input_count = len(list(payload.get("emergency_rows") or [])) if emergency_enabled else 0
    emergency_count = max(4, emergency_input_count) if emergency_enabled else 0
    table_rows = 3 + fixed_count + (3 + emergency_count if emergency_enabled else 0)
    layout = {
        "data_row": DATA_ROW_PT,
        "header_row": HEADER_ROW_PT,
        "data_font": TABLE_FONT_PT,
        "header_font": 15,
        "paragraph_font": BODY_FONT_PT,
        "signature_font": SIGNATURE_FONT_PT,
        "table_rows": table_rows,
        "header_gap": 26 if emergency_enabled else 37,  # 0.9 cm for emergency forms
        "title_line": 25,
        "title_after": 8,
        "paragraph_after": 11,
        "separator_space": 8,
    }
    usable = (PAGE_HEIGHT_MM - 2 * MARGIN_MM) * 72 / 25.4
    target = usable * 0.92
    estimate = _layout_estimate(layout, fixed_count, emergency_count, emergency_enabled)

    if emergency_enabled and estimate > target:
        # Stage 1: reduce rows, first to the established 0.75 cm minimum.
        layout["data_row"] = MIN_ROW_PT
        layout["header_row"] = MIN_ROW_PT
        estimate = _layout_estimate(layout, fixed_count, emergency_count, emergency_enabled)
    if emergency_enabled and estimate > target:
        # Stage 1b: the large totals need the 0.62 cm floor.
        layout["data_row"] = MIN_COMPACT_ROW_PT
        layout["header_row"] = MIN_COMPACT_ROW_PT
        estimate = _layout_estimate(layout, fixed_count, emergency_count, emergency_enabled)
    if emergency_enabled and estimate > target:
        # Stage 2: reduce data/header/body/signature fonts.
        layout["data_font"] = 13
        layout["header_font"] = 14
        layout["paragraph_font"] = 14
        layout["signature_font"] = SIGNATURE_FONT_PT
        estimate = _layout_estimate(layout, fixed_count, emergency_count, emergency_enabled)
    if emergency_enabled and estimate > target:
        # Stage 3: tighten only emergency vertical gaps; off remains untouched.
        layout["header_gap"] = 17
        layout["title_after"] = 3
        layout["paragraph_after"] = 5
        layout["separator_space"] = 3
        estimate = _layout_estimate(layout, fixed_count, emergency_count, emergency_enabled)

    layout["fit_estimate"] = estimate
    layout["fit_target"] = target
    return layout


def _table_widths():
    return [
        CONTENT_WIDTH_MM * 0.05,
        CONTENT_WIDTH_MM * 0.38,
        CONTENT_WIDTH_MM * 0.09,
        CONTENT_WIDTH_MM * 0.09,
        CONTENT_WIDTH_MM * 0.11,
        CONTENT_WIDTH_MM * 0.12,
        CONTENT_WIDTH_MM * 0.16,
    ]


def _set_table_grid_widths(table, widths_mm):
    """Make tblGrid and every tcW agree, including merged cells.

    python-docx creates equal grid columns by default.  Word/LibreOffice use
    tblGrid for layout even when individual tcW values look correct, so the
    real RTL paper widths must be written to both representations.
    """
    widths = [round(width * 56.6929) for width in widths_mm]
    widths[-1] += round(CONTENT_WIDTH_MM * 56.6929) - sum(widths)
    grid = table._tbl.tblGrid
    columns = grid.findall(qn("w:gridCol"))
    while len(columns) < len(widths):
        node = OxmlElement("w:gridCol")
        grid.append(node)
        columns.append(node)
    for node in columns[len(widths):]:
        grid.remove(node)
    for node, width in zip(columns[:len(widths)], widths):
        _set_attr(node, "w", width)
    for tr in table._tbl.tr_lst:
        position = 0
        for cell in tr.findall(qn("w:tc")):
            tc_pr = cell.find(qn("w:tcPr"))
            span_node = tc_pr.find(qn("w:gridSpan")) if tc_pr is not None else None
            span = int(span_node.get(qn("w:val"), "1")) if span_node is not None else 1
            span_width = sum(widths[position:position + span])
            if tc_pr is None:
                tc_pr = OxmlElement("w:tcPr")
                cell.insert(0, tc_pr)
            tcw = tc_pr.find(qn("w:tcW"))
            if tcw is None:
                tcw = OxmlElement("w:tcW")
                tc_pr.insert(0, tcw)
            _set_attr(tcw, "type", "dxa")
            _set_attr(tcw, "w", span_width)
            position += span


def _make_table(document, rows, total_label, *, emergency, layout):
    # RTL visual order: م، اسم الخدمة، ضباط، أفراد، مجندين، الإجمالي، ملاحظات.
    widths = _table_widths()
    table = document.add_table(rows=2, cols=7)
    table.autofit = False
    _table_direction(table)
    for row in table.rows:
        for cell, width in zip(row.cells, widths):
            _cell_width(cell, width)
            _cell_borders(cell)

    top, second = table.rows
    for index, label in enumerate(("م", "اسم الخدمة")):
        merged = top.cells[index].merge(second.cells[index])
        _cell_text(merged, label, size=layout["header_font"], bold=True,
                   right_padding=80 if index == 0 else 0,
                   left_padding=80 if index == 0 else 0)
        _set_no_wrap(merged)
        _cell_borders(merged)
    numbers = top.cells[2].merge(top.cells[4])
    _cell_text(numbers, "الأعـــــداد", size=layout["header_font"], bold=True)
    _merge_horizontal(numbers, 3)
    _set_no_wrap(numbers)
    for index, label in enumerate(("ضباط", "أفراد", "مجندين"), 2):
        _cell_text(second.cells[index], label, size=layout["header_font"], bold=True)
        _set_no_wrap(second.cells[index])
    for index, label in ((5, "الإجمالي"), (6, "ملاحظات")):
        merged = top.cells[index].merge(second.cells[index])
        _cell_text(merged, label, size=layout["header_font"], bold=True)
        _set_no_wrap(merged)
        _cell_borders(merged)
    _row_height(top, layout["header_row"])
    _row_height(second, layout["header_row"])

    for number, item in enumerate(rows, 1):
        row = table.add_row()
        filled = bool(item.get("name"))
        values = [
            number,
            item.get("name", ""),
            item.get("officers", 0),
            item.get("personnel", 0),
            item.get("conscripts", 0),
            sum(int(item.get(key, 0) or 0)
                for key in ("officers", "personnel", "conscripts")),
            item.get("notes", ""),
        ]
        for index, (cell, value) in enumerate(zip(row.cells, values)):
            if index == 0:
                display = value
                align = WD_ALIGN_PARAGRAPH.RIGHT
            elif index == 1:
                display = value
                align = WD_ALIGN_PARAGRAPH.RIGHT
            elif index in (2, 3, 4, 5):
                display = "" if emergency and not filled else (value if value else "ـــــ")
                align = WD_ALIGN_PARAGRAPH.CENTER
            else:
                display = value
                align = WD_ALIGN_PARAGRAPH.CENTER
            _cell_text(cell, display, size=layout["data_font"],
                       bold=not emergency, align=align,
                       right_padding=80 if index == 0 else (140 if index == 1 else 0),
                       left_padding=80 if index == 0 else (140 if index == 1 else 0))
            _cell_borders(cell)
        _row_height(row, layout["data_row"], exact=False)

    total = sum(sum(int(item.get(key, 0) or 0)
                    for key in ("officers", "personnel", "conscripts"))
                for item in rows)
    row = table.add_row()
    _cell_text(row.cells[0], "ـــ", size=layout["data_font"], bold=True,
               right_padding=80, left_padding=80)
    _cell_borders(row.cells[0])
    label = row.cells[1].merge(row.cells[3])
    _cell_text(label, total_label, size=layout["data_font"], bold=True)
    _set_no_wrap(label)
    _cell_borders(label)
    count = row.cells[4].merge(row.cells[5])
    suffix = "وجبه" if emergency else "وجبة"
    _cell_text(count, f"{total} {suffix}", size=layout["data_font"], bold=True)
    _cell_borders(count)
    _cell_text(row.cells[6], "", size=layout["data_font"], bold=True)
    _cell_borders(row.cells[6])
    _row_height(row, layout["data_row"], exact=False)
    _set_table_grid_widths(table, widths)
    return table, total


def _separator(document, *, spacing=8):
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_spacing(paragraph, spacing, spacing, line=4)
    _bidi(paragraph)
    p_bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    _set_attr(bottom, "val", "single")
    _set_attr(bottom, "sz", 32)
    _set_attr(bottom, "space", 1)
    _set_attr(bottom, "color", "000000")
    p_bdr.append(bottom)
    _ppr(paragraph).append(p_bdr)
    ind = OxmlElement("w:ind")
    _set_attr(ind, "left", 650)
    _set_attr(ind, "right", 650)
    _ppr(paragraph).append(ind)
    return paragraph


def _signature_table(container, payload, *, font_size=SIGNATURE_FONT_PT):
    try:
        table = container.add_table(rows=1, cols=3)
    except TypeError:
        table = container.add_table(rows=1, cols=3, width=Mm(CONTENT_WIDTH_MM))
    table.autofit = False
    _table_direction(table)
    widths = [SIGNATURE_BOX_CM * 10, CONTENT_WIDTH_MM - 2 * SIGNATURE_BOX_CM * 10, SIGNATURE_BOX_CM * 10]
    for cell, width in zip(table.rows[0].cells, widths):
        _cell_borders(cell, none=True)
        _cell_width(cell, width)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    right = payload.get("ops_signer") or {}
    left = payload.get("chief") or {}
    # نفس نص يومية التعيينات بالظبط: العنوان، «الرتبة/»، «(اسم من كلمتين)»
    for cell, title, person, short in (
        (table.cell(0, 0), "بلوكامين قسم العمليات", right, False),
        (table.cell(0, 2), "رئيس قسم العمليات", left, True),
    ):
        cell.text = ""
        if not person:
            lines = (title, "", "")
        else:
            lines = (title, f"{person.get('rank') or ''}/",
                     f"({_signature_name(person, short)})")
        for index, text in enumerate(lines):
            paragraph = cell.paragraphs[0] if index == 0 else cell.add_paragraph()
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _set_spacing(paragraph, 0, 0, line=font_size * 1.2)
            _bidi(paragraph)
            _run(paragraph, text, size=font_size, bold=True, font_name=SIGNATURE_FONT_NAME)
    return table


def _fit_guard(payload):
    fixed = list(payload.get("fixed_rows") or [])
    emergency = list(payload.get("emergency_rows") or []) if payload.get("emergency_enabled") else []
    layout = _table_layout(payload)
    meter = TextMeter()
    used = layout["fit_estimate"]
    for rows in (fixed, emergency):
        for row in rows:
            note = str(row.get("notes") or "")
            name = str(row.get("name") or "")
            if note and len(meter.wrap_lines(note, 115, layout["data_font"], font_name=FONT_NAME)) > 1:
                used += layout["data_row"] * 0.25
            if name and len(meter.wrap_lines(name, 190, layout["data_font"], font_name=FONT_NAME)) > 1:
                used += layout["data_row"] * 0.25
    usable = (PAGE_HEIGHT_MM - 2 * MARGIN_MM) * 72 / 25.4
    if used > usable:
        raise PageFitError("تعذر احتواء أمر صرف الوجبات الجافة في صفحة واحدة؛ قلل عدد الصفوف أو طول الملاحظات.")


def build_docx(payload):
    """يرجع BytesIO لملف A4 طولي من صفحة واحدة."""
    _fit_guard(payload)
    layout = _table_layout(payload)
    document = Document()
    section = document.sections[0]
    section.page_width = Mm(PAGE_WIDTH_MM)
    section.page_height = Mm(PAGE_HEIGHT_MM)
    section.top_margin = Mm(MARGIN_MM)
    section.bottom_margin = Mm(MARGIN_MM)
    section.left_margin = Mm(MARGIN_MM)
    section.right_margin = Mm(MARGIN_MM)
    _set_page_frame(section)
    normal = document.styles["Normal"]
    normal.font.name = FONT_NAME
    normal.font.size = Pt(BODY_FONT_PT)
    normal.font.bold = False

    selected_date = date.fromisoformat(str(payload.get("date") or ""))
    date_text = f"{payload.get('weekday') or ''} الموافق {selected_date.day}/{selected_date.month}/{selected_date.year} م"
    body_prefix = "أمر صرف وجبات (جافة) للخدمات"
    body_suffix = "عن يوم"
    paragraph_tail = " وكونهم مبيت 24 ساعة خدمة ـــولتعذر وصول التعيينات الطازجة لهم بصورة جيدة."

    head = document.add_table(rows=1, cols=2)
    head.autofit = False
    _table_direction(head)
    for cell, width in zip(head.rows[0].cells, (CONTENT_WIDTH_MM * 0.38, CONTENT_WIDTH_MM * 0.62)):
        _cell_borders(cell, none=True)
        _cell_width(cell, width)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
    right, left = head.cell(0, 0), head.cell(0, 1)
    right.text = ""
    for idx, text in enumerate(("مديرية أمن السويس", "إدارة قوات الأمن", "قسم العمليات")):
        p = right.paragraphs[0] if idx == 0 else right.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _set_spacing(p, 0, 0, line=13)
        _bidi(p)
        _run(p, text, size=LETTERHEAD_FONT_PT, bold=False)
    left.text = ""
    p = left.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _set_spacing(p, 0, 0, line=13)
    _bidi(p)
    _run(p, f"أمر عمليات رقم (      ) عن شهر (      )    لسنة {selected_date.year}",
         size=LETTERHEAD_FONT_PT, bold=False)

    gap = document.add_paragraph()
    _set_spacing(gap, 0, 0, line=layout["header_gap"])
    _bidi(gap)

    _paragraph(document, "أمر عمليات ثابت", size=TITLE_FONT_PT, bold=True,
               underline=True, after=layout["title_after"], line=layout["title_line"])
    fixed_wording = f"{body_prefix} الثابتة {body_suffix} {date_text}{paragraph_tail}"
    _paragraph(document, fixed_wording, size=layout["paragraph_font"], bold=True,
               align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=layout["paragraph_after"],
               line_twips=int(layout["paragraph_font"] * 20 * 1.35))
    _make_table(document, payload.get("fixed_rows") or [],
                "أجمالي الوجبـــــات الجافـــة المنصرفة", emergency=False,
                layout=layout)

    if payload.get("emergency_enabled"):
        _separator(document, spacing=layout["separator_space"])
        _paragraph(document, "أمر عمليات طارئ", size=TITLE_FONT_PT, bold=True,
                   underline=True, after=layout["title_after"], line=layout["title_line"])
        emergency_wording = f"{body_prefix} الطارئة {body_suffix} {date_text}{paragraph_tail}"
        _paragraph(document, emergency_wording, size=layout["paragraph_font"], bold=True,
                   align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=layout["paragraph_after"],
                   line_twips=int(layout["paragraph_font"] * 20 * 1.35))
        emergency = list(payload.get("emergency_rows") or [])
        emergency += [{"name": "", "officers": 0, "personnel": 0,
                       "conscripts": 0, "notes": ""}
                      for _ in range(max(0, 4 - len(emergency)))]
        _make_table(document, emergency,
                    "اجمالي الوجبـــــات الجافـــة المنصرفة", emergency=True,
                    layout=layout)
    footer = section.footer
    section.footer_distance = Mm(5)
    _signature_table(footer, payload, font_size=layout["signature_font"])
    normalize_ooxml_order(document.element)
    normalize_ooxml_order(footer._element)
    output = BytesIO()
    document.save(output)
    output.seek(0)
    return output
