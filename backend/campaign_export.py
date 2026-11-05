"""تصدير «يومية الحملة» بصيغة الأرشيف الأحدث."""
import re
from datetime import date
from io import BytesIO

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, Twips

from . import fleet
from .board_export import WEEKDAY_BY_INDEX, _set_rtl_doc, set_run_font, style_tables_bold_rtl
from .labels import personnel_rank_abbr

GRID_WIDTHS = [693, 514, 1416, 1268, 148, 1217, 342, 420, 1139,
               342, 334, 887, 408, 1109, 8]
# التنسيق الغالب في أرشيف سبتمبر وأكتوبر 2026 (54 ملف): جدول واحد بيكمّل على
# صفحة تانية عادي — مفيش تصغير لصفحة واحدة.
CHECKPOINT_SPANS = [1, 2, 5, 3, 4]               # 583 صف
DELIVERY_SPANS = [1, 3, 6, 3, 2]                 # عمود الخدمة ضيّق (= عرض عمود الارتكاز) عشان السائق ما يلفّش وتبقى صفحة واحدة
DRIVER_ONLY_SPANS = [1, 5, 9]                    # «سائق بورتوفيق»: سائق من غير مركبة (55 صف)
PLATE_SPANS = [2, 1, 2, 2, 2, 3, 3]              # سجل اللوحات (154 صف، آخر عمود 8 twips بيتضم للأخير)
FONT = "Sultan bold"
FILL = "F2F2F2"
TITLE_PT, POST_PT, HEADING_PT, DELIVERY_PT, PLATE_PT = 14, 9, 9, 11, 11
# رقم لوحة خطوط السير بالسلسلة «ب15/5217» (طلب المالك؛ الأرشيف كان متقسّم بين الصيغتين).
DELIVERY_PLATE_WITH_SERIES = True
# لوريات المأموريات الثابتة مالهاش صف في الأرشيف إلا لو اتكلّفت فعلًا.


def _set_borders(table):
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for name, value, size in (("top", "thinThickSmallGap", 24),
                              ("left", "thinThickSmallGap", 24),
                              ("bottom", "thinThickSmallGap", 24),
                              ("right", "thinThickSmallGap", 24),
                              ("insideH", "double", 4), ("insideV", "double", 4)):
        node = borders.find(qn("w:" + name))
        if node is None:
            node = OxmlElement("w:" + name)
            borders.append(node)
        node.set(qn("w:val"), value)
        node.set(qn("w:sz"), str(size))
        node.set(qn("w:space"), "0")
        node.set(qn("w:color"), "000000")


def _set_grid(table):
    grid = table._tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in GRID_WIDTHS:
        col = OxmlElement("w:gridCol")
        col.set(qn("w:w"), str(width))
        grid.append(col)
    table.autofit = False
    table._tbl.tblPr.append(OxmlElement("w:bidiVisual"))
    # هوامش الخانات صفر زي الأرشيف — من غيرها اللوحة «ب13/9416» بتلف على سطرين.
    margins = OxmlElement("w:tblCellMar")
    for side in ("left", "right"):
        node = OxmlElement(f"w:{side}")
        node.set(qn("w:w"), "0")
        node.set(qn("w:type"), "dxa")
        margins.append(node)
    table._tbl.tblPr.append(margins)


def _shade(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    old = tc_pr.find(qn("w:shd"))
    if old is not None:
        tc_pr.remove(old)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def _cell(cell, text="", *, size=9, bold=True, fill=None):
    cell.text = ""
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    paragraph = cell.paragraphs[0]
    # cell.text = "" بيسيب run فاضي بخط Arial 10 بيكبّر ارتفاع السطر عن مقاس الأرشيف.
    for empty in paragraph._p.findall(qn("w:r")):
        paragraph._p.remove(empty)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    ppr = paragraph._p.get_or_add_pPr()
    if ppr.find(qn("w:bidi")) is None:
        ppr.append(OxmlElement("w:bidi"))
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    run = paragraph.add_run(str(text or ""))
    set_run_font(run, FONT, size, bold)
    run._r.get_or_add_rPr().append(OxmlElement("w:rtl"))
    if fill:
        _shade(cell, fill)


def _merge_row(row, spans, values, *, size=9, fill=None, number_fill=FILL):
    """خانة «م» (أول خانة) متظللة في كل صف زي الأرشيف."""
    cells = row.cells
    offset = 0
    for index, (span, value) in enumerate(zip(spans, values)):
        cell = cells[offset]
        for extra in cells[offset + 1:offset + span]:
            cell = cell.merge(extra)
        _cell(cell, value, size=size, fill=fill or (number_fill if index == 0 and len(spans) > 1 else None))
        offset += span


def _driver_text(row):
    """السائق بالرتبة والاسم كامل: الأفراد «ا.ش/» أو «م.ش/» والمجند «مجند/».
    السائق المكتوب نص حر بيطلع زي ما اتكتب."""
    driver = row.get("driver") or {}
    name = " ".join(re.sub(r"ـ", "", str(driver.get("name") or driver.get("display") or "")).split())
    if not name:
        return "ـــــ"
    if driver.get("kind") == "personnel":
        return f"{personnel_rank_abbr(driver.get('role'))}/ {name}"
    if driver.get("kind") == "conscript":
        return f"مجند/ {name}"
    return name


def _has_content(item):
    """هل اللوري/الصف فيه تكليف فعلي (سائق أو مركبة أو خدمة مضافة)؟"""
    driver = item.get("driver") or {}
    return bool(str(driver.get("name") or "").strip() or item.get("vehicle")
                or item.get("attached") or item.get("vehicles"))


def _service_label(item):
    """صياغة اسم الخدمة زي الأرشيف: «كـــ 109» و«A + B» بمسافات، والساعة بعد الاسم.
    الجهة بين علامتي تنصيص ماتتطبعش هنا (طباعتها نزّلت التطابق 61.2% → 60.6%)."""
    if item.get("kind") == "group":
        return " ".join(str(item.get("name") or "").split())   # عنوان المجموعة زي ما كتبه المستخدم
    name = str(item.get("name") or "")
    name = re.sub(r"كـ+\s*109", "كـــ 109", name)
    name = re.sub(r"\s*\+\s*", " + ", name)
    # «مستشفى 1» / «نيابة عامة 1»: الرقم عداد تمييز داخلي والأرشيف مابيطبعوش
    name = re.sub(r"\s+1$", "", " ".join(name.split()))
    time = " ".join(str(item.get("time") or "").split())
    if time and time not in name:
        name = f"{name} {time}"
    return name


def _post_plate(post):
    if post.get("plate_text"):
        return post["plate_text"]
    plate = (post.get("vehicle") or {}).get("plate") or ""
    if "/" in plate:
        series, number = plate.split("/", 1)
        return number + series
    return plate


def _post_type(post):
    if post.get("type_text"):
        return post["type_text"]
    vehicle = post.get("vehicle") or {}
    return " ".join(filter(None, (vehicle.get("type"), vehicle.get("model"))))


def _delivery_plate(row):
    plate = (row.get("vehicle") or {}).get("plate") or ""
    if DELIVERY_PLATE_WITH_SERIES:
        return plate
    return plate.split("/", 1)[-1] if plate else ""


def _delivery_type(row):
    vehicle = row.get("vehicle") or {}
    value = vehicle.get("type") or ""
    if vehicle.get("origin") == "external" and vehicle.get("party"):
        value += f" (خارجية: {vehicle['party']})"
    return value


def _sync_cell_widths(table):
    """عرض كل خانة = مجموع أعمدة الشبكة اللي بتغطيها. الدمج في python-docx بيسيب
    tcW قديم، وLibreOffice بيرسم بيه فالخانة كانت بتضيق وتلف اللوحة على سطرين."""
    for tr in table._tbl.tr_lst:
        column = 0
        for tc in tr.tc_lst:
            span = tc.grid_span
            tc.width = Twips(sum(GRID_WIDTHS[column:column + span]))
            column += span


THICK = 18   # 2.25pt (بالثُمن نقطة): الحد الفاصل بين فئات المركبات وبين لواري الفئة الواحدة


def _row_border(row, side):
    """حد سميك أسود على كل خلايا الصف من الناحية side ('top' أو 'bottom')."""
    for tc in row._tr.tc_lst:
        tc_pr = tc.get_or_add_tcPr()
        borders = tc_pr.find(qn("w:tcBorders"))
        if borders is None:
            borders = OxmlElement("w:tcBorders")
            # ترتيب عناصر tcPr في المخطط: tcBorders قبل shd/noWrap/tcMar/vAlign.
            after = [tc_pr.find(qn("w:" + n)) for n in
                     ("shd", "noWrap", "tcMar", "textDirection", "tcFitText", "vAlign", "hideMark")]
            after = [n for n in after if n is not None]
            if after:
                after[0].addprevious(borders)
            else:
                tc_pr.append(borders)
        node = borders.find(qn("w:" + side))
        if node is None:
            node = OxmlElement("w:" + side)
            order = ("top", "left", "start", "bottom", "right", "end")
            later = [borders.find(qn("w:" + n)) for n in order[order.index(side) + 1:]]
            later = [n for n in later if n is not None]
            if later:
                later[0].addprevious(node)
            else:
                borders.append(node)
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), str(THICK))
        node.set(qn("w:space"), "0")
        node.set(qn("w:color"), "000000")


def _plate_row(table, values):
    row = table.add_row()
    _merge_row(row, PLATE_SPANS, list(values)[:len(PLATE_SPANS)], size=PLATE_PT, number_fill=None)
    return row


def build_docx(campaign):
    doc = Document()
    _set_rtl_doc(doc)
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21.0), Cm(29.7)
    section.top_margin = section.left_margin = section.right_margin = Cm(1.27)
    section.bottom_margin = Cm(0.752)
    table = doc.add_table(rows=0, cols=15)
    _set_grid(table)
    _set_borders(table)
    d = date.fromisoformat(campaign["date"])
    title = f"يومية الحملة اليوم {WEEKDAY_BY_INDEX[d.weekday()]} {d.day}/{d.month}/{d.year}م"
    _merge_row(table.add_row(), [15], [title], size=TITLE_PT)
    _merge_row(table.add_row(), CHECKPOINT_SPANS,
               ["م", "مركبات الإرتكازات", "السائق", "رقم المركبة", "نوع المركبة"], size=HEADING_PT)
    for post in campaign.get("posts") or []:
        values = [post.get("number", ""), post.get("name", ""),
                  post.get("driver_text") or "ـــــ", _post_plate(post), _post_type(post)]
        _merge_row(table.add_row(), CHECKPOINT_SPANS, values, size=POST_PT)
    divider = "خطــــــــــوط سيــــــــــر توصيــــــــــل الخدمــــــــــات"
    _merge_row(table.add_row(), [15], [divider], size=HEADING_PT, fill=FILL)
    _merge_row(table.add_row(), DELIVERY_SPANS,
               ["م", "الخدمة", "السائق", "رقم المركبة", "نوع المركبة"], size=HEADING_PT)
    delivery = [{**item, "_lorry": True} for item in campaign.get("lorries") or []]
    for service in campaign.get("services") or []:
        vehicles = service.get("service_vehicles") or []
        if not vehicles:
            delivery.append(service)
            continue
        for item in vehicles:
            delivery.append({**service, "vehicle": item.get("vehicle"),
                             "driver": item.get("driver") or service.get("driver")})
    delivery += [{**item, "_daily": True} for item in campaign.get("daily") or []]
    delivery += [{**item, "_lorry": True} for item in campaign.get("appointments") or [] if _has_content(item)]
    # ترتيب فئات المركبات: لوري (كل لوري ورا بعض) ← أتوبيس ← ميكروباص ← بيك اب/دوبل كبينة ← الباقي.
    ordered = fleet.order_by_category(
        delivery, lambda item: (item.get("vehicle") or {}).get("type"),
        lambda item: (item.get("vehicle") or {}).get("id") or item.get("id"),
        lorry_if_missing=lambda item: bool(item.get("_lorry")))
    previous_break = False
    for number, (item, _category, _key, brk) in enumerate(ordered, 1):
        plate, kind = _delivery_plate(item), _delivery_type(item)
        # «سائق بورتوفيق» وأمثاله: سائق يومي من غير مركبة، اسمه على عرض الصف (زي الأرشيف).
        if item.get("_daily") and not plate and not kind and (item.get("driver") or {}).get("name"):
            values, spans = [f"{number}.", _service_label(item), _driver_text(item)], DRIVER_ONLY_SPANS
        else:
            values, spans = [f"{number}.", _service_label(item), _driver_text(item), plate, kind], DELIVERY_SPANS
        row = table.add_row()
        _merge_row(row, spans, values, size=DELIVERY_PT)
        if previous_break:
            _row_border(row, "top")
        if brk:
            _row_border(row, "bottom")
        previous_break = brk
    for values in (campaign.get("plates") or {}).get("rows") or []:
        _plate_row(table, values)
    _sync_cell_widths(table)
    style_tables_bold_rtl(doc)
    output = BytesIO()
    doc.save(output)
    output.seek(0)
    return output
