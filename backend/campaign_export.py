"""تصدير «يومية المركبات» بصيغة الأرشيف الأحدث."""
import re
from datetime import date
from io import BytesIO

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from .board_export import WEEKDAY_BY_INDEX, _set_rtl_doc, set_run_font, style_tables_bold_rtl
from .export_fit import apply_fit_to_docx_table, fit_table, usable_height_pt
from .labels import first_words

LAST_FIT = {}
GRID_WIDTHS = [693, 514, 1416, 1268, 148, 1217, 342, 420, 1139,
               342, 334, 887, 408, 1109, 8]
CHECKPOINT_SPANS = [1, 3, 4, 3, 4]
DELIVERY_SPANS = [1, 3, 4, 3, 4]
FONT = "Sultan bold"
FILL = "F2F2F2"
# قواعد الطباعة اللي ثبتت من أرشيف 82 يوم (أغسطس–أكتوبر 2026):
# - السائق اسمين بدون رتبة (1,076 من 1,418 اسم؛ الثلاثي 305 والرباعي 36، والرتبة 0).
DRIVER_NAME_WORDS = 2
# - رقم لوحة الخدمات/اللواري من غير سلسلة (880 صف) أكتر من «ب13/9416» (469 صف).
#   ظهور السلسلة بيجي في فترات متصلة (8-13/8 و13-24/9 و6-21/10): غيّر القيمة دي لو
#   اتحوّل الأرشيف كله للصيغة الأطول.
DELIVERY_PLATE_WITH_SERIES = False
# - لوريات المأموريات الثابتة مالهاش صف في الأرشيف إلا لو اتكلّفت فعلًا.


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


def _merge_row(row, spans, values, *, size=9, fill=None):
    cells = row.cells
    offset = 0
    for span, value in zip(spans, values):
        cell = cells[offset]
        for extra in cells[offset + 1:offset + span]:
            cell = cell.merge(extra)
        _cell(cell, value, size=size, fill=fill)
        offset += span


def _row_spec(values, spans, size=9):
    return [{"text": value or "", "colspan": span, "size_pt": size,
             "bold": True, "font": FONT} for value, span in zip(values, spans)]


def _driver_text(row):
    """اسم السائق زي الأرشيف: أول كلمتين من غير رتبة، مهما كان نوع السائق."""
    driver = row.get("driver") or {}
    name = first_words(driver.get("name"), DRIVER_NAME_WORDS, glue=True)
    return name or "ـــــ"


def _has_content(item):
    """هل اللوري/الصف فيه تكليف فعلي (سائق أو مركبة أو خدمة مضافة)؟"""
    driver = item.get("driver") or {}
    return bool(str(driver.get("name") or "").strip() or item.get("vehicle")
                or item.get("attached") or item.get("vehicles"))


def _service_label(item):
    """صياغة اسم الخدمة زي الأرشيف: «كـــ 109» و«A + B» بمسافات، والساعة بعد الاسم.
    الجهة بين علامتي تنصيص ماتتطبعش هنا (طباعتها نزّلت التطابق 61.2% → 60.6%)."""
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


def _plate_row(table, values):
    row = table.add_row()
    # سجل اللوحات سبع خلايا مستقلة، كما في صيغة latest.
    for cell in list(row._tr.findall(qn("w:tc")))[7:]:
        row._tr.remove(cell)
    for cell, value in zip(row.cells, list(values)[:7]):
        _cell(cell, value, size=9)
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
    title = f"يومية المركبات اليوم {WEEKDAY_BY_INDEX[d.weekday()]} {d.day}/{d.month}/{d.year}م"
    _merge_row(table.add_row(), [15], [title], size=14)
    _merge_row(table.add_row(), CHECKPOINT_SPANS,
               ["م", "مركبات الإرتكازات", "السائق", "رقم المركبة", "نوع المركبة"],
               size=10, fill=FILL)
    posts = campaign.get("posts") or []
    post_specs = []
    for post in posts:
        values = [post.get("number", ""), post.get("name", ""),
                  post.get("driver_text") or "ـــــ", _post_plate(post),
                  _post_type(post)]
        post_specs.append(_row_spec(values, CHECKPOINT_SPANS))
        _merge_row(table.add_row(), CHECKPOINT_SPANS, values)
    divider = "خطــــــــــوط سيــــــــــر توصيــــــــــل الخدمــــــــــات"
    _merge_row(table.add_row(), [15], [divider], size=10)
    _merge_row(table.add_row(), DELIVERY_SPANS,
               ["م", "الخدمة", "السائق", "رقم المركبة", "نوع المركبة"],
               size=10, fill=FILL)
    delivery = list(campaign.get("lorries") or [])
    for service in campaign.get("services") or []:
        vehicles = service.get("service_vehicles") or []
        if not vehicles:
            delivery.append(service)
            continue
        for item in vehicles:
            delivery.append({**service, "vehicle": item.get("vehicle"),
                             "driver": item.get("driver") or service.get("driver")})
    delivery += list(campaign.get("daily") or [])
    delivery += [item for item in campaign.get("appointments") or [] if _has_content(item)]
    delivery_specs = []
    for item in delivery:
        values = ["", _service_label(item), _driver_text(item),
                  _delivery_plate(item), _delivery_type(item)]
        delivery_specs.append(_row_spec(values, DELIVERY_SPANS))
        _merge_row(table.add_row(), DELIVERY_SPANS, values)
    plate_rows = (campaign.get("plates") or {}).get("rows") or []
    for values in plate_rows:
        _plate_row(table, values)
    fit_rows = [_row_spec([title], [15], 14),
                 _row_spec(["م", "مركبات الإرتكازات", "السائق", "رقم المركبة", "نوع المركبة"],
                           CHECKPOINT_SPANS, 10)]
    fit_rows += post_specs + [_row_spec([divider], [15], 10),
                               _row_spec(["م", "الخدمة", "السائق", "رقم المركبة", "نوع المركبة"],
                                         DELIVERY_SPANS, 10)]
    fit_rows += delivery_specs
    fit_rows += [[{"text": value or "", "size_pt": 9, "bold": True, "font": FONT}
                  for value in list(values)[:7]] for values in plate_rows]
    widths_pt = [width * 72 / 1440 for width in GRID_WIDTHS]
    fit = fit_table({"rows": fit_rows, "grid_widths_pt": widths_pt},
                    usable_height_pt(section))
    apply_fit_to_docx_table(table, fit)
    LAST_FIT.clear()
    LAST_FIT.update(scale=fit.scale, ratio=fit.ratio, total_pt=fit.total_pt,
                    usable_pt=fit.usable_pt)
    style_tables_bold_rtl(doc)
    output = BytesIO()
    doc.save(output)
    output.seek(0)
    return output
