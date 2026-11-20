"""تصدير كشف «يومية التعيينات» إلى Word من قالب الأرشيف المنظّف."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import re

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

TEMPLATE = Path(__file__).with_name("docx_templates") / "assignments_roster.docx"
FONT_NAME = "Arial"
ARCHIVE_ROW_HEIGHT = 440  # الأرشيف 397، لكن الصف exact عندنا فنزوّده شوية عشان خط عربي طويل ما يتقصش
MIN_ROW_HEIGHT = 225  # 9pt × 1.25 × 20 twips
TABLE_SAFETY = 0.97
TITLE_SIGNATURE_BUDGET = 2200
V_SHAPE = "{urn:schemas-microsoft-com:vml}shape"
WPS_BODY_PR = "{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}bodyPr"
EMU_PER_TWIP = 635
SIGNATURE_BOX_WIDTH = 4000  # 200pt; fits the longest three-line signature
TARGET_LABEL_ROWS = 2
TARGET_LABEL_FONT_PT = 14


def _column_width_twips(node):
    """عرض نص الصفحة (بين الهوامش) بالـtwips من sectPr المستند اللي فيه العقدة."""
    root = node.getroottree().getroot()
    sect = root.find(".//" + qn("w:sectPr"))
    size, margin = sect.find(qn("w:pgSz")), sect.find(qn("w:pgMar"))
    return (int(size.get(qn("w:w"))) - int(margin.get(qn("w:left"))) - int(margin.get(qn("w:right"))))


def _tcs(tr):
    return list(tr.findall(qn("w:tc")))


def _tc_pr(tc):
    pr = tc.find(qn("w:tcPr"))
    if pr is None:
        pr = OxmlElement("w:tcPr")
        tc.insert(0, pr)
    return pr


def _set_grid_span(tc, span, width=None):
    pr = _tc_pr(tc)
    node = pr.find(qn("w:gridSpan"))
    if node is None:
        node = OxmlElement("w:gridSpan")
        pr.append(node)
    node.set(qn("w:val"), str(span))
    if width is not None:
        tcw = pr.find(qn("w:tcW"))
        if tcw is None:
            tcw = OxmlElement("w:tcW")
            pr.insert(0, tcw)
        tcw.set(qn("w:w"), str(width))
        tcw.set(qn("w:type"), "dxa")


def _set_vmerge(tc, value):
    pr = _tc_pr(tc)
    node = pr.find(qn("w:vMerge"))
    if node is None:
        node = OxmlElement("w:vMerge")
        pr.append(node)
    if value == "continue":
        node.attrib.pop(qn("w:val"), None)
    else:
        node.set(qn("w:val"), value)


def _center_cell(tc):
    """يفرض تمركز الخلية أفقيًا ورأسيًا في كل تمثيلات الجدول."""
    pr = _tc_pr(tc)
    valign = pr.find(qn("w:vAlign"))
    if valign is None:
        valign = OxmlElement("w:vAlign")
        pr.append(valign)
    valign.set(qn("w:val"), "center")
    nowrap = pr.find(qn("w:noWrap"))
    if nowrap is None:
        nowrap = OxmlElement("w:noWrap")
        pr.append(nowrap)
    for paragraph in tc.findall(qn("w:p")):
        ppr = paragraph.find(qn("w:pPr"))
        if ppr is None:
            ppr = OxmlElement("w:pPr")
            paragraph.insert(0, ppr)
        jc = ppr.find(qn("w:jc"))
        if jc is None:
            jc = OxmlElement("w:jc")
            ppr.append(jc)
        jc.set(qn("w:val"), "center")
        spacing = ppr.find(qn("w:spacing"))
        if spacing is None:
            spacing = OxmlElement("w:spacing")
            ppr.append(spacing)
        spacing.set(qn("w:before"), "0")
        spacing.set(qn("w:after"), "0")
        spacing.set(qn("w:line"), "240")
        spacing.set(qn("w:lineRule"), "auto")


def _set_row_height(tr, height):
    tr_pr = tr.find(qn("w:trPr"))
    if tr_pr is None:
        tr_pr = OxmlElement("w:trPr")
        tr.insert(0, tr_pr)
    height_node = tr_pr.find(qn("w:trHeight"))
    if height_node is None:
        height_node = OxmlElement("w:trHeight")
        tr_pr.append(height_node)
    height_node.set(qn("w:val"), str(int(height)))
    height_node.set(qn("w:hRule"), "exact")


def _set_cell_font_size(tc, points):
    value = str(max(18, int(round(float(points) * 2))))
    for run_pr in tc.iter(qn("w:rPr")):
        for tag in ("w:sz", "w:szCs"):
            node = run_pr.find(qn(tag))
            if node is None:
                node = OxmlElement(tag)
                run_pr.append(node)
            node.set(qn("w:val"), value)


def _vmerge_span(rows, row_index, cell_index):
    cell = _tcs(rows[row_index])[cell_index]
    merge = cell.find("./" + qn("w:tcPr") + "/" + qn("w:vMerge"))
    if merge is None or merge.get(qn("w:val")) != "restart":
        return 1
    span = 1
    for following in rows[row_index + 1:]:
        cells = _tcs(following)
        if len(cells) <= cell_index:
            break
        following_merge = cells[cell_index].find(
            "./" + qn("w:tcPr") + "/" + qn("w:vMerge"))
        if following_merge is None:
            break
        if following_merge.get(qn("w:val")) == "restart":
            break
        span += 1
    return span


def _fit_table_fonts(rows, height):
    """يمنع الخط من أن يكون أطول من ارتفاع الصف الصارم.

    الخلية المدمجة تحصل على مجموع ارتفاع صفوفها؛ أما الخلايا العادية فتحصل
    على صف واحد. لا ننزل تحت 9pt، ولذلك يضمن row_height_for حدًا أدنى مناسبًا.
    """
    for row_index, row in enumerate(rows):
        for cell_index, cell in enumerate(_tcs(row)):
            span = _vmerge_span(rows, row_index, cell_index)
            max_points = (span * height) / 25.0
            sizes = [int(node.get(qn("w:val"))) / 2
                     for node in cell.iter(qn("w:sz"))
                     if node.get(qn("w:val"), "").isdigit()]
            if sizes and max(sizes) > max_points:
                _set_cell_font_size(cell, max(9, max_points))


def _available_table_height(document):
    section = document.sections[0]
    page_body = (section.page_height.twips - section.top_margin.twips
                 - section.bottom_margin.twips)
    return max(MIN_ROW_HEIGHT, int((page_body - TITLE_SIGNATURE_BUDGET)
                                   * TABLE_SAFETY))


def row_height_for(document, row_count):
    """أكبر ارتفاع صف يحفظ ميزانية الصفحة مع حد أدنى 9pt تقريبًا."""
    row_count = max(1, int(row_count))
    return max(MIN_ROW_HEIGHT,
               min(ARCHIVE_ROW_HEIGHT,
                   _available_table_height(document) // row_count))


def _full_width_row(source_row, width):
    """ينشئ صفًا واحدًا بخانة واحدة ممتدة على شبكة الأعمدة الثمانية."""
    tr = deepcopy(source_row)
    cells = _tcs(tr)
    if not cells:
        raise ValueError("صف الأرشيف لا يحتوي خلايا")
    keep = cells[4] if len(cells) >= 5 else cells[0]
    for cell in cells:
        if cell is not keep:
            tr.remove(cell)
    _set_grid_span(keep, 8, width)
    pr = _tc_pr(keep)
    vmerge = pr.find(qn("w:vMerge"))
    if vmerge is not None:
        pr.remove(vmerge)
    _set_cell_text(keep, "")
    return tr


def _prototype_rpr(parent):
    """يرجع rPr من النص الفعلي، ثم من إعداد الفقرة عند الخلايا الفارغة."""
    run = parent.find(".//" + qn("w:r") + "/" + qn("w:rPr"))
    if run is not None:
        return deepcopy(run)
    return deepcopy(parent.find(".//" + qn("w:pPr") + "/" + qn("w:rPr")))


def _append_text_run(paragraph, text, prototype):
    run = OxmlElement("w:r")
    if prototype is not None:
        run.append(deepcopy(prototype))
    text_node = OxmlElement("w:t")
    text_node.text = str(text or "")
    text_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    run.append(text_node)
    paragraph.append(run)


def _set_cell_text(tc, text, _unused=None):
    """يستبدل النص فقط ويترك pPr/rPr/الحدود كما أخذت من صف الأرشيف."""
    paragraphs = tc.findall(qn("w:p"))
    if not paragraphs:
        paragraphs = [OxmlElement("w:p")]
        tc.append(paragraphs[0])
    paragraph = paragraphs[0]
    prototype = _prototype_rpr(tc)
    for extra in paragraphs[1:]:
        tc.remove(extra)
    for child in list(paragraph):
        if child.tag != qn("w:pPr"):
            paragraph.remove(child)
    if text:
        _append_text_run(paragraph, text, prototype)


def _remove_numbering(tc):
    paragraph = tc.find(qn("w:p"))
    ppr = paragraph.find(qn("w:pPr")) if paragraph is not None else None
    numpr = ppr.find(qn("w:numPr")) if ppr is not None else None
    if numpr is not None:
        ppr.remove(numpr)


def _fill_half(tr, start, item):
    values = [
        item.get("number", "") if item else "",
        item.get("role", "") if item else "",
        item.get("name", "") if item else "",
        item.get("status", "") if item else "",
    ]
    cells = _tcs(tr)
    if len(cells) < start + 4:
        return
    for offset, value in enumerate(values):
        # أول خانة في النصف الأيمن تعتمد على numbering الموجود في قالب Word.
        if start == 0 and offset == 0:
            if item:
                continue
            _remove_numbering(cells[start + offset])
        _set_cell_text(cells[start + offset], value)


def _signature_box(box, title, signer):
    paragraphs = box.findall(qn("w:p"))
    if not paragraphs:
        return
    proto_ppr = paragraphs[0].find(qn("w:pPr"))
    proto_rpr = next((run.find(qn("w:rPr")) for run in paragraphs[0].findall(qn("w:r"))
                      if run.find(qn("w:t")) is not None), None)
    if not title and not signer:
        values = ["", "", ""]
    elif not signer:
        values = [title, "", ""]
    else:
        values = [title, f"{(signer or {}).get('rank') or ''}/",
                  f"({(signer or {}).get('name') or ''})"]
    for paragraph in paragraphs:
        box.remove(paragraph)
    for value in values:
        p = OxmlElement("w:p")
        if proto_ppr is not None:
            p.append(deepcopy(proto_ppr))
        run = OxmlElement("w:r")
        if proto_rpr is not None:
            run.append(deepcopy(proto_rpr))
        text_node = OxmlElement("w:t")
        text_node.text = value
        text_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        run.append(text_node)
        p.append(run)
        _tighten_raw_paragraph(p)
        box.append(p)


def _tighten_raw_paragraph(paragraph):
    ppr = paragraph.find(qn("w:pPr"))
    if ppr is None:
        ppr = OxmlElement("w:pPr")
        paragraph.insert(0, ppr)
    jc = ppr.find(qn("w:jc"))
    if jc is None:
        jc = OxmlElement("w:jc")
        ppr.append(jc)
    jc.set(qn("w:val"), "center")
    spacing = ppr.find(qn("w:spacing"))
    if spacing is None:
        spacing = OxmlElement("w:spacing")
        ppr.append(spacing)
    spacing.set(qn("w:before"), "0")
    spacing.set(qn("w:after"), "0")
    spacing.set(qn("w:line"), "240")
    spacing.set(qn("w:lineRule"), "auto")


def _fill_signatures(document, payload):
    root = document.part.element
    # القالب القديم يحمل ثلاثة صناديق؛ الصندوق الثالث هو بقايا «وكيل» ولا
    # يجوز أن يظل مخفيًا أو يظهر في محرر آخر. نحذفه من تمثيلي DrawingML وVML.
    for anchor in list(root.iter(qn("wp:anchor"))):
        doc_pr = anchor.find(qn("wp:docPr"))
        if doc_pr is not None and doc_pr.get("name") == "Text Box 3":
            anchor.getparent().remove(anchor)
    for shape in list(root.iter(V_SHAPE)):
        if shape.get("id") == "Text Box 3":
            shape.getparent().remove(shape)

    def shape_name(box):
        node = box
        while node is not None:
            if node.tag == qn("wp:anchor"):
                doc_pr = node.find(qn("wp:docPr"))
                return doc_pr.get("name") if doc_pr is not None else ""
            if node.tag == V_SHAPE:
                return node.get("id") or ""
            node = node.getparent()
        return ""

    def move_shape(box, edge):
        node = box
        while node is not None and node.tag not in (qn("wp:anchor"), V_SHAPE):
            node = node.getparent()
        if node is None:
            return
        if node.tag == qn("wp:anchor"):
            position_h = node.find(qn("wp:positionH"))
            if position_h is None:
                position_h = OxmlElement("wp:positionH")
                node.insert(1, position_h)
            # كالأرشيف: إزاحة من حافة العمود الشمال (الأرشيف نفسه: صندوق رئيس العمليات إزاحته 5.0M
            # على اليمين ومدير الإدارة 0.13M على الشمال). `align` بتتفسّر غلط في LibreOffice/OnlyOffice.
            position_h.set("relativeFrom", "column")
            for child in list(position_h):
                position_h.remove(child)
            offset_h = OxmlElement("wp:posOffset")
            offset_h.text = "0" if edge == "left" else str(
                max(0, (_column_width_twips(node) - SIGNATURE_BOX_WIDTH) * EMU_PER_TWIP))
            position_h.append(offset_h)
            position_v = node.find(qn("wp:positionV"))
            if position_v is None:
                position_v = OxmlElement("wp:positionV")
                node.insert(2, position_v)
            position_v.set("relativeFrom", "paragraph")
            for child in list(position_v):
                position_v.remove(child)
            offset = OxmlElement("wp:posOffset")
            offset.text = "0"
            position_v.append(offset)
            extent = node.find(qn("wp:extent"))
            if extent is not None:
                extent.set("cx", str(SIGNATURE_BOX_WIDTH * EMU_PER_TWIP))
            for shape_ext in node.iter(qn("a:ext")):
                shape_ext.set("cx", str(SIGNATURE_BOX_WIDTH * EMU_PER_TWIP))
        else:
            style = node.get("style") or ""
            style = re.sub(r"mso-position-horizontal:[^;]+;?", "", style)
            style = re.sub(r"mso-position-horizontal-relative:[^;]+;?", "", style)
            style = re.sub(r"margin-left:[^;]+;?", "", style)
            style = re.sub(r"margin-top:[^;]+;?", "", style)
            style = re.sub(r"width:[^;]+;?", "", style)
            if style and not style.endswith(";"):
                style += ";"
            style += (f"mso-position-horizontal:{edge};"
                      "mso-position-horizontal-relative:margin;"
                      "mso-position-vertical-relative:text;"
                      f"width:{SIGNATURE_BOX_WIDTH / 20:.2f}pt;"
                      "margin-left:0;margin-top:0;")
            node.set("style", style)

    ops = payload.get("ops_signer") or {}
    chief = payload.get("chief") or {}
    # Text Box 4 هو اليسار، وText Box 5 هو اليمين في القالب المنظّف.
    for box in list(root.iter(qn("w:txbxContent"))):
        name = shape_name(box)
        if name == "Text Box 4":
            _signature_box(box, "قسم العمليات", ops)
            move_shape(box, "left")
        elif name == "Text Box 5":
            _signature_box(box, "رئيس قسم العمليات", chief)
            move_shape(box, "right")
    for body_pr in root.iter(WPS_BODY_PR):
        body_pr.set("wrap", "square")


def _title(document, text):
    paragraph = document.paragraphs[0] if document.paragraphs else document.add_paragraph()
    runs = list(paragraph._p.r_lst)
    if len(runs) < 13 or " عن يوم " not in str(text):
        if not runs:
            paragraph.add_run(text)
            return
        text_node = runs[0].find(qn("w:t"))
        if text_node is None:
            text_node = OxmlElement("w:t")
            runs[0].append(text_node)
        text_node.text = str(text)
        text_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        for run in runs[1:]:
            for node in list(run.findall(qn("w:t"))):
                run.remove(node)
        return
    rest = str(text).split(" عن يوم ", 1)[1]
    day_name, date_text = rest.split(" الموافق ", 1)
    date_text = date_text.removesuffix("م")
    date_parts = date_text.split("/")
    if len(date_parts) != 3:
        text_node = runs[0].find(qn("w:t"))
        text_node.text = str(text)
        text_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        for run in runs[1:]:
            for node in list(run.findall(qn("w:t"))):
                run.remove(node)
        return
    day, month, year = date_parts
    values = ["كشف", " ", "بأسماء", " السادة الضباط عن يوم ",
              "ال", day_name[2:] if day_name.startswith("ال") else day_name,
              " ", "الموافق ", day, "/", month, "/", f" {year}م"]
    for run, value in zip(runs, values):
        for node in list(run.findall(qn("w:t"))):
            run.remove(node)
        text_node = OxmlElement("w:t")
        text_node.text = value
        text_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        run.append(text_node)

    _tighten_paragraph(paragraph)


def _tighten_paragraph(paragraph):
    ppr = paragraph._p.get_or_add_pPr()
    spacing = ppr.find(qn("w:spacing"))
    if spacing is None:
        spacing = OxmlElement("w:spacing")
        ppr.append(spacing)
    spacing.set(qn("w:before"), "0")
    spacing.set(qn("w:after"), "0")
    spacing.set(qn("w:line"), "240")
    spacing.set(qn("w:lineRule"), "auto")
    jc = ppr.find(qn("w:jc"))
    if jc is None:
        jc = OxmlElement("w:jc")
        ppr.append(jc)
    jc.set(qn("w:val"), "center")


def build_docx(payload):
    """يرجع BytesIO؛ الصفحة والـAPI يرسلان نفس البايتات."""
    document = Document(TEMPLATE)
    _title(document, payload.get("title") or payload.get("date") or "")
    _fill_signatures(document, payload)
    table = document.tables[0]
    source_rows = list(table._tbl.tr_lst)
    if len(source_rows) < 24:
        raise ValueError("قالب يومية التعيينات لا يحتوي صفوف الأرشيف الـ24 المطلوبة")

    right = list(payload.get("right") or [])
    target_items = list(payload.get("target_items") or [])
    left = list(payload.get("left") or []) + list(payload.get("overflow") or [])
    doctors = list(payload.get("doctors") or [])
    categories = payload.get("footer_categories")
    if not isinstance(categories, list):
        categories = [
            {"label": "ضابط امن مركزي", "count": payload.get("central", 4)},
            {"label": "ضابط امن مواني", "count": payload.get("ports", 1)},
        ]
    categories = [item for item in categories if isinstance(item, dict)]
    total = payload.get(
        "total", len(right) + len(target_items) + len(left) + len(doctors)
        + sum(int(item.get("count", 0)) for item in categories))

    # الأهداف والضباط الذين يواصلون بعد النصف الأيمن يسكنون النصف الأيسر
    # بترتيب واحد، مع أرقام تبدأ بعد آخر رقم في النصف الأيمن.
    left_items = []
    next_number = 24
    for item in target_items + left:
        item = dict(item)
        item["number"] = next_number
        next_number += 1
        left_items.append(item)

    # في الشكل الأرشيفي: كتلة المحتوى اليسرى حتى الصف 13، ثم ثلاثة صفوف ذيل
    # وصف فارغ، ثم أربع خانات للعيادة، وصف فارغ، وأخيرًا الإجمالي الكامل.
    footer_slots = max(3, len(categories))
    clinic_slots = 4 if len(doctors) <= 3 else 1 + len(doctors)
    content_slots = 13
    content_needed = TARGET_LABEL_ROWS + len(left_items)  # العنوان + صفوف عادية
    content_extra = max(0, content_needed - content_slots)
    footer_start = 14 + content_extra
    clinic_start = footer_start + footer_slots + 1
    total_index = clinic_start + clinic_slots + 1

    def source_row(index):
        return source_rows[index] if index < len(source_rows) else source_rows[23]

    def row_for(index):
        if index == 0:
            return deepcopy(source_rows[0])
        if index == 1:
            return deepcopy(source_rows[1])
        if TARGET_LABEL_ROWS >= 2 and 2 <= index < 1 + TARGET_LABEL_ROWS:
            return deepcopy(source_rows[2])
        if 1 + TARGET_LABEL_ROWS <= index < footer_start:
            return deepcopy(source_rows[6])
        if footer_start <= index < footer_start + footer_slots:
            return deepcopy(source_rows[15] if index == footer_start else source_rows[16])
        if index == footer_start + footer_slots:
            return deepcopy(source_rows[18])
        if clinic_start <= index < clinic_start + clinic_slots:
            if index < clinic_start + (clinic_slots - len(doctors)):
                return deepcopy(source_rows[20] if index == clinic_start else source_rows[21])
            doctor_index = index - clinic_start - (clinic_slots - len(doctors))
            return deepcopy(source_rows[23] if doctor_index == len(doctors) - 1
                            else source_rows[22])
        if index == clinic_start + clinic_slots:
            return deepcopy(source_rows[18])
        if index == total_index:
            grid_width = 0
            for cell in source_rows[0].findall(qn("w:tc")):
                tc_pr = cell.find(qn("w:tcPr"))
                tc_w = tc_pr.find(qn("w:tcW")) if tc_pr is not None else None
                if tc_w is not None:
                    grid_width += int(tc_w.get(qn("w:w"), "0"))
            return _full_width_row(source_rows[15], grid_width)
        return deepcopy(source_row(index))

    # عنوان الأهداف يمتد صفين على الأقل؛ صفوف الأهداف نفسها عادية تحته.
    left_cursor = 0
    rows = []
    for index in range(total_index + 1):
        tr = row_for(index)
        if index == 0:
            rows.append(tr)
            continue

        right_item = right[index - 1] if index - 1 < len(right) else None
        cells = _tcs(tr)
        if index != total_index:
            _fill_half(tr, 0, right_item)

        if index == 1:
            _set_cell_text(cells[4], "الأهداف")
            _set_cell_font_size(cells[4], TARGET_LABEL_FONT_PT)
        elif 1 + TARGET_LABEL_ROWS <= index < footer_start:
            item = left_items[left_cursor] if left_cursor < len(left_items) else None
            left_cursor += 1
            _fill_half(tr, 4, item)
        elif footer_start <= index < footer_start + footer_slots:
            footer_index = index - footer_start
            item = categories[footer_index] if footer_index < len(categories) else None
            _set_cell_text(cells[4],
                           f"( {item['count']} ) {item['label']}" if item else "")
        elif clinic_start <= index < clinic_start + clinic_slots:
            label_span = clinic_slots - len(doctors)
            if not doctors:
                _set_cell_text(cells[4], "")
            elif index < clinic_start + label_span:
                _set_cell_text(cells[4], "العيادة الطبية" if index == clinic_start else "")
            else:
                doctor_index = index - clinic_start - label_span
                doctor = doctors[doctor_index] if doctor_index < len(doctors) else None
                if doctor and doctor_index == 0:
                    doctor = {**doctor, "number": next_number}
                _fill_half(tr, 4, doctor)
        elif index == total_index:
            _set_cell_text(cells[0], f"الإجمالي: {total}")

        for cell in _tcs(tr):
            _center_cell(cell)
        rows.append(tr)

    # The table is deliberately allowed to grow only by cloning ordinary rows
    # when the left content/footer/clinic needs it; in the usual archive-sized
    # case this remains exactly 24 rows.
    height = row_height_for(document, len(rows))
    _fit_table_fonts(rows, height)
    for tr in rows:
        _set_row_height(tr, height)
        for cell in _tcs(tr):
            _center_cell(cell)

    for tr in list(table._tbl.tr_lst):
        table._tbl.remove(tr)
    for tr in rows:
        table._tbl.append(tr)

    output = BytesIO()
    document.save(output)
    output.seek(0)

    # `python-docx` يعيد تسلسل أجزاء ثابتة في الحزمة عند كل حفظ، حتى لو لم
    # نلمسها. القالب مأخوذ حرفيًا من ملف الأرشيف؛ لذلك نعيد كل الأجزاء غير
    # document.xml من القالب نفسه، فلا يبقى اختلاف غير اختلاف بيانات اليوم.
    generated = BytesIO(output.getvalue())
    restored = BytesIO()
    with ZipFile(TEMPLATE) as template_zip:
        with ZipFile(generated) as generated_zip:
            with ZipFile(restored, "w", compression=ZIP_DEFLATED) as result_zip:
                for info in generated_zip.infolist():
                    content = (generated_zip.read(info.filename)
                               if info.filename == "word/document.xml"
                               else template_zip.read(info.filename))
                    result_zip.writestr(info, content)
    restored.seek(0)
    return restored
