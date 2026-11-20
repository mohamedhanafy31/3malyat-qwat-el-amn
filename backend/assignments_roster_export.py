"""تصدير كشف «يومية التعيينات» إلى Word من قالب الأرشيف المنظّف."""
from copy import deepcopy
from io import BytesIO
import math
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import re

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from .export_fit import TextMeter

TEMPLATE = Path(__file__).with_name("docx_templates") / "assignments_roster.docx"
FONT_NAME = "Arial"
NOTE_FONT_NAME = "Times New Roman"
NOTE_FONT_BOLD = True
NOTE_NORMAL_PT = 12.0
NOTE_MIN_ONE_LINE_PT = 8.0
NOTE_MIN_TWO_LINE_PT = 7.5
NOTE_LINE_HEIGHT = 1.25
NOTE_CELL_MARGIN_PT = 0.0  # the archive template has no explicit w:tcMar
NAME_MIN_GUTTER_PT = 0.0
ARCHIVE_ROW_HEIGHT = 440  # الأرشيف 397، لكن الصف exact عندنا فنزوّده شوية عشان خط عربي طويل ما يتقصش
MIN_ROW_HEIGHT = 225  # 9pt × 1.25 × 20 twips
TABLE_SAFETY = 0.97
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
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


# ترتيب أبناء العناصر في OOXML (ECMA-376): Word بيرفض الملف («Unspecified error» في word/document.xml)
# لو الترتيب اتغيّر، بينما LibreOffice بيتسامح. أي خاصية بنضيفها بـ`append` لازم تتعدّل لترتيبها الصح.
_OOXML_ORDER = {
    "pPr": "pStyle keepNext keepLines pageBreakBefore framePr widowControl numPr suppressLineNumbers "
           "pBdr shd tabs suppressAutoHyphens kinsoku wordWrap overflowPunct topLinePunct autoSpaceDE "
           "autoSpaceDN bidi adjustRightInd snapToGrid spacing ind contextualSpacing mirrorIndents "
           "suppressOverlap jc textDirection textAlignment textboxTightWrap outlineLvl divId cnfStyle "
           "rPr sectPr pPrChange".split(),
    "rPr": "rStyle rFonts b bCs i iCs caps smallCaps strike dstrike outline shadow emboss imprint "
           "noProof snapToGrid vanish webHidden color spacing w kern position sz szCs highlight u "
           "effect bdr shd fitText vertAlign rtl cs em lang eastAsianLayout specVanish oMath".split(),
    "tcPr": "cnfStyle tcW gridSpan hMerge vMerge tcBorders shd noWrap tcMar textDirection tcFitText "
            "vAlign hideMark".split(),
    "tblPr": "tblStyle tblpPr tblOverlap bidiVisual tblStyleRowBandSize tblStyleColBandSize tblW jc "
             "tblCellSpacing tblInd tblBorders shd tblLayout tblCellMar tblLook".split(),
}


def normalize_ooxml_order(root):
    """يرتّب أبناء pPr/rPr/tcPr/tblPr حسب المخطط ويشيل التكرار (الأخير يكسب). -> عدد العناصر اللي اتعدّلت."""
    changed = 0
    for name, sequence in _OOXML_ORDER.items():
        position = {tag: index for index, tag in enumerate(sequence)}
        for element in root.iter(qn(f"w:{name}")):
            children = list(element)
            keyed = []
            for order, child in enumerate(children):
                local = child.tag.rsplit("}", 1)[-1] if isinstance(child.tag, str) else ""
                known = child.tag.startswith("{" + _W_NS + "}") and local in position
                keyed.append((position[local] if known else len(sequence), order, local, child))
            latest = {}
            for key in keyed:
                if key[0] < len(sequence):
                    latest[key[2]] = key[3]            # التكرار: آخر عنصر بنفس الاسم يكسب
            kept = [k for k in keyed if k[0] >= len(sequence) or latest[k[2]] is k[3]]
            ordered = sorted(kept, key=lambda k: (k[0], k[1]))
            if [k[3] for k in ordered] != children:
                changed += 1
                for child in children:
                    element.remove(child)
                for k in ordered:
                    element.append(k[3])
    return changed


_MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def drop_empty_drawings(root):
    """يشيل أي `<w:drawing/>` فاضي (صندوق توقيع اتفضّى بدل ما يتشال): Word بيرفض الملف كله
    («Unspecified error») لأن الرسم لازم يكون فيه wp:anchor أو wp:inline. -> عدد المحذوف."""
    removed = 0
    for drawing in list(root.iter(qn("w:drawing"))):
        if len(drawing):
            continue
        node = drawing
        # نطلع لأقرب mc:AlternateContent ثم لـ w:r اللي حاوياه ونشيله كله
        while node is not None and node.tag != "{%s}AlternateContent" % _MC_NS:
            node = node.getparent()
        target = node if node is not None else drawing
        run = target.getparent()
        if run is not None and run.tag == qn("w:r") and len(run) == 1:
            run.getparent().remove(run)
        elif run is not None:
            run.remove(target)
        removed += 1
    return removed


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


def _set_cell_font_size(tc, points, minimum=7.5):
    value = str(max(int(round(float(minimum) * 2)), int(round(float(points) * 2))))
    for run_pr in tc.iter(qn("w:rPr")):
        for tag in ("w:sz", "w:szCs"):
            node = run_pr.find(qn(tag))
            if node is None:
                node = OxmlElement(tag)
                run_pr.append(node)
            node.set(qn("w:val"), value)


def _set_cell_font(tc, name=NOTE_FONT_NAME, bold=NOTE_FONT_BOLD):
    """يجعل القياس والخط الفعلي للخلية نفس الوجه العريض."""
    for run_pr in tc.iter(qn("w:rPr")):
        fonts = run_pr.find(qn("w:rFonts"))
        if fonts is None:
            fonts = OxmlElement("w:rFonts")
            run_pr.insert(0, fonts)
        for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
            fonts.set(qn(f"w:{attribute}"), name)
        if bold:
            for tag in ("w:b", "w:bCs"):
                node = run_pr.find(qn(tag))
                if node is None:
                    node = OxmlElement(tag)
                    run_pr.append(node)


def _set_cell_line_height(tc, points):
    line = str(max(1, int(round(float(points) * NOTE_LINE_HEIGHT * 20))))
    for paragraph in tc.findall(qn("w:p")):
        ppr = paragraph.find(qn("w:pPr"))
        if ppr is None:
            ppr = OxmlElement("w:pPr")
            paragraph.insert(0, ppr)
        spacing = ppr.find(qn("w:spacing"))
        if spacing is None:
            spacing = OxmlElement("w:spacing")
            ppr.append(spacing)
        spacing.set(qn("w:line"), line)
        spacing.set(qn("w:lineRule"), "exact")


def _set_cell_wrap(tc, wrapped):
    pr = _tc_pr(tc)
    nowrap = pr.find(qn("w:noWrap"))
    if wrapped:
        if nowrap is not None:
            pr.remove(nowrap)
    elif nowrap is None:
        pr.append(OxmlElement("w:noWrap"))


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


def _cell_text(tc):
    return "".join(node.text or "" for node in tc.iter(qn("w:t")))


def _row_grid_cells(tr):
    """يرجع (بداية الخلية على الشبكة، الامتداد، الخلية)."""
    position = 0
    result = []
    for cell in _tcs(tr):
        span = cell.find("./" + qn("w:tcPr") + "/" + qn("w:gridSpan"))
        span = int(span.get(qn("w:val"), "1")) if span is not None else 1
        result.append((position, span, cell))
        position += span
    return result


def _best_two_line_split(text, width_pt, size, meter):
    words = str(text or "").split()
    if len(words) < 2:
        return None
    choices = []
    for index in range(1, len(words)):
        lines = [" ".join(words[:index]), " ".join(words[index:])]
        widths = [meter.text_width(line, size, NOTE_FONT_BOLD, NOTE_FONT_NAME)
                  for line in lines]
        if max(widths) <= width_pt:
            choices.append((max(widths), abs(widths[0] - widths[1]), lines))
    if not choices:
        return None
    return min(choices, key=lambda item: (item[0], item[1]))[2]


def _two_line_need(text, size, meter):
    words = str(text or "").split()
    if len(words) < 2:
        return None
    choices = []
    for index in range(1, len(words)):
        lines = [" ".join(words[:index]), " ".join(words[index:])]
        widths = [meter.text_width(line, size, NOTE_FONT_BOLD, NOTE_FONT_NAME)
                  for line in lines]
        choices.append((max(widths), abs(widths[0] - widths[1])))
    return min(choices)[0] + NOTE_CELL_MARGIN_PT if choices else None


NOTE_WIDTH_SAFETY = 1.18   # Word/LibreOffice بيرسموا الخط بعرض أكبر من قياس Times New Roman


class _SafeMeter:
    """TextMeter بعرض مضروب في هامش أمان: التقدير بالخط المتاح عندنا مش نفس خط جهاز التشغيل."""

    def __init__(self):
        self._meter = TextMeter()

    def text_width(self, *args, **kwargs):
        return self._meter.text_width(*args, **kwargs) * NOTE_WIDTH_SAFETY

    def __getattr__(self, name):
        return getattr(self._meter, name)


def _note_fit(text, width_twips, height_twips, meter):
    """يختار حجمًا/عدد أسطر من غير قص النص."""
    inner = max(1.0, width_twips / 20.0 - NOTE_CELL_MARGIN_PT)
    for size in (12.0, 11.0, 10.0, 9.0, 8.0):
        if meter.text_width(text, size, NOTE_FONT_BOLD, NOTE_FONT_NAME) <= inner:
            return {"size": size, "lines": [str(text)]}

    available_height = height_twips / 20.0 - NOTE_CELL_MARGIN_PT
    for size in (8.0, 7.5):
        if 2 * size * NOTE_LINE_HEIGHT > available_height:
            continue
        lines = _best_two_line_split(text, inner, size, meter)
        if lines is not None:
            return {"size": size, "lines": lines}
    return None


def _required_note_width(text, height_twips, meter):
    """أصغر عرض يمكنه استيعاب النص ضمن قيود السطر/الصف."""
    one_line = meter.text_width(text, NOTE_MIN_ONE_LINE_PT,
                                NOTE_FONT_BOLD, NOTE_FONT_NAME) + NOTE_CELL_MARGIN_PT
    needs = [one_line]
    available_height = height_twips / 20.0 - NOTE_CELL_MARGIN_PT
    if 2 * NOTE_MIN_ONE_LINE_PT * NOTE_LINE_HEIGHT <= available_height:
        need = _two_line_need(text, NOTE_MIN_ONE_LINE_PT, meter)
        if need is not None:
            needs.append(need)
    return min(needs)


def _set_table_grid_widths(table, widths, rows=None):
    for grid_col, width in zip(table._tbl.tblGrid.findall(qn("w:gridCol")), widths):
        grid_col.set(qn("w:w"), str(int(width)))
    for tr in rows if rows is not None else table._tbl.tr_lst:
        for position, span, cell in _row_grid_cells(tr):
            if span != 1 or position >= len(widths):
                continue
            if position not in (1, 2, 3, 5, 6, 7):
                continue
            tcw = _tc_pr(cell).find(qn("w:tcW"))
            if tcw is None:
                tcw = OxmlElement("w:tcW")
                _tc_pr(cell).insert(0, tcw)
            tcw.set(qn("w:w"), str(int(widths[position])))
            tcw.set(qn("w:type"), "dxa")


def _fit_note_cells(table, rows, height):
    """يلائم الملاحظات مع إعادة توزيع مقاسة داخل كل نصف من الجدول.

    يبدأ التوسيع من الاسم، ثم يأخذ من الرتبة عند الحاجة. إجمالي شبكة النصف
    يظل ثابتًا، والاسم والرتبة لا ينزلان عن العرض المقاس المطلوب لعرض كل
    قيمهما الحالية.
    """
    meter = _SafeMeter()
    grid = [int(node.get(qn("w:w"), "0"))
            for node in table._tbl.tblGrid.findall(qn("w:gridCol"))]
    entries_by_half = {0: [], 1: []}
    names_by_half = {0: [], 1: []}
    ranks_by_half = {0: [], 1: []}
    for row_index, tr in enumerate(rows):
        if row_index == 0:
            continue
        cells = {position: cell for position, span, cell in _row_grid_cells(tr)
                 if span == 1}
        for half, rank_index, name_index, note_index in ((0, 1, 2, 3), (1, 5, 6, 7)):
            note = cells.get(note_index)
            name = cells.get(name_index)
            rank = cells.get(rank_index)
            if name is not None:
                names_by_half[half].append(_cell_text(name).strip())
            if rank is not None:
                ranks_by_half[half].append(_cell_text(rank).strip())
            if note is None or name is None:
                continue
            text = _cell_text(note).strip()
            if not text:
                continue
            entries_by_half[half].append({"note": note, "name": name,
                                          "text": text, "height": height})

    for half, entries in entries_by_half.items():
        if not entries:
            continue
        rank_index, name_index, note_index = ((1, 2, 3) if half == 0
                                              else (5, 6, 7))
        pair_width = grid[name_index] + grid[note_index]
        name_min_pt = max((
            meter.text_width(name, NOTE_NORMAL_PT,
                             NOTE_FONT_BOLD, NOTE_FONT_NAME) + NAME_MIN_GUTTER_PT
            for name in names_by_half[half]
            if name
        ), default=0.0)
        rank_min_pt = max((
            meter.text_width(rank, NOTE_NORMAL_PT,
                             NOTE_FONT_BOLD, NOTE_FONT_NAME)
            for rank in ranks_by_half[half]
            if rank
        ), default=0.0)
        note_width_pt = grid[note_index] / 20.0
        for entry in entries:
            if _note_fit(entry["text"], grid[note_index], height, meter) is None:
                note_width_pt = max(
                    note_width_pt,
                    _required_note_width(entry["text"], height, meter),
                )
        target_note_width = max(grid[note_index], int(math.ceil(note_width_pt * 20)))
        name_min = int(math.ceil(name_min_pt * 20))
        rank_min = int(math.ceil(rank_min_pt * 20)) if rank_min_pt else grid[rank_index]
        total_half_width = grid[rank_index] + pair_width
        note_max = total_half_width - name_min - rank_min
        target_note_width = min(target_note_width, note_max)      # عند الحد الأقصى _note_fit بيصغّر الخط
        if target_note_width > pair_width - name_min:
            # الاسم وصل إلى عرضه المقاس؛ الزيادة الباقية تأتي من الرتبة.
            grid[rank_index] = total_half_width - name_min - target_note_width
            grid[name_index] = name_min
            grid[note_index] = target_note_width
        else:
            grid[note_index] = target_note_width
            grid[name_index] = pair_width - target_note_width

    _set_table_grid_widths(table, grid, rows)
    for half, entries in entries_by_half.items():
        position = 3 if half == 0 else 7
        for entry in entries:
            fit = _note_fit(entry["text"], grid[position], height, meter)
            if fit is None:
                raise ValueError(f"ملاحظة يومية التعيينات لا تتسع: {entry['text']}")
            _set_cell_text(entry["note"], "\n".join(fit["lines"]))
            _set_cell_font_size(entry["note"], fit["size"], minimum=7.5)
            _set_cell_font(entry["note"])
            _set_cell_line_height(entry["note"], fit["size"])
            _set_cell_wrap(entry["note"], len(fit["lines"]) > 1)


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
    parts = str(text or "").split("\n")
    for index, part in enumerate(parts):
        text_node = OxmlElement("w:t")
        text_node.text = part + (" " if index < len(parts) - 1 else "")
        text_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        run.append(text_node)
        if index < len(parts) - 1:
            run.append(OxmlElement("w:br"))
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


def _signature_name(signer, prefer_short=False):
    signer = signer or {}
    value = signer.get("short_name") if prefer_short else signer.get("name")
    value = str(value or signer.get("name") or "").replace("ـ", " ")
    return " ".join(value.split()[:2])


def _signature_box(box, title, signer, prefer_short=False):
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
                  f"({_signature_name(signer, prefer_short)})"]
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
            _signature_box(box, "بلوكامين قسم العمليات", ops)       # الفرد: على اليمين
            move_shape(box, "right")
        elif name == "Text Box 5":
            _signature_box(box, "رئيس قسم العمليات", chief, prefer_short=True)  # الضابط: على الشمال
            move_shape(box, "left")
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

    _fit_note_cells(table, rows, height)

    for tr in list(table._tbl.tr_lst):
        table._tbl.remove(tr)
    for tr in rows:
        table._tbl.append(tr)

    drop_empty_drawings(document.element)
    normalize_ooxml_order(document.element)
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
