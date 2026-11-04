"""خط تشكيل ليل على قالب ملف الأرشيف نفسه (طلب المالك: نفس التنسيق بالظبط).

القالب ``docx_templates/formation_night.docx`` نسخة من «خط تشكيل ليل.docx» يوم 2026-10-22.
بنعيد بناء صفوف الجدول بس: كل خدمة أساسية ليلية عنوان وتحتها خانة لكل مجند بعدد
يومية الأعداد. كل الباقي (الخطوط، الحدود، الأشكال تحت الجدول) من القالب زي ما هو.
"""
from copy import deepcopy
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from .formation import has_no_serial

TEMPLATE = Path(__file__).with_name("docx_templates") / "formation_night.docx"
TEMPLATE_ROWS = 42           # عدد صفوف جدول القالب اللي بيملا الصفحة
MIN_SCALE = .7               # أقل تصغير للخط/الارتفاع لو الصفوف زادت عن القالب
THICK = 18                   # 2.25pt (بالثُمن نقطة) الحد الفاصل بين مجموعات اللوري
# أعمدة القالب بعد توسيع الاسم على حساب رقم السلاح (نفس عرض كل نص):
# يمين = اسم، تسليح، فاصل 9، رقم | شمال = اسم، تسليح، رقم.
GRID = (3906, 850, 9, 640, 3665, 850, 640)
LAST_FIT = {}


def _span(tc):
    node = tc.tcPr.find(qn("w:gridSpan")) if tc.tcPr is not None else None
    return int(node.get(qn("w:val"))) if node is not None else 1


def _positions(tr):
    col, out = 0, []
    for tc in tr.tc_lst:
        out.append((col, _span(tc), tc))
        col += _span(tc)
    return out


def _apply_grid(tbl):
    for col, width in zip(tbl.tblGrid.findall(qn("w:gridCol")), GRID):
        col.set(qn("w:w"), str(width))
    for tr in tbl.tr_lst:
        for col, span, tc in _positions(tr):
            tc.tcPr.find(qn("w:tcW")).set(qn("w:w"), str(sum(GRID[col:col + span])))


def _merge_serial(cells):
    """خانة التسليح بتاخد مكان «رقم السلاح» لما السلاح مالوش رقم."""
    weapon, serial = cells[1], cells[2]
    width = int(weapon.tcPr.find(qn("w:tcW")).get(qn("w:w"))) + int(serial.tcPr.find(qn("w:tcW")).get(qn("w:w")))
    weapon.tcPr.find(qn("w:tcW")).set(qn("w:w"), str(width))
    span = weapon.tcPr.find(qn("w:gridSpan"))
    if span is None:
        span = OxmlElement("w:gridSpan")
        weapon.tcPr.find(qn("w:tcW")).addnext(span)
    span.set(qn("w:val"), str(_span(weapon) + _span(serial) if span.get(qn("w:val")) else 1 + _span(serial)))
    # الحد الخارجي (إطار الجدول/فاصل النصين) بتاع خانة الرقم ينتقل للخانة المدموجة.
    borders = weapon.tcPr.find(qn("w:tcBorders"))
    source = serial.tcPr.find(qn("w:tcBorders"))
    edge = source.find(qn("w:right")) if source is not None else None
    if borders is not None:
        for old in borders.findall(qn("w:right")):
            borders.remove(old)
        if edge is not None:
            borders.append(deepcopy(edge))
    return cells[:2]


def _prototypes(tbl):
    """نماذج الخلايا من جدول القالب: (اليمين، الشمال) لكل نوع صف."""
    rows = tbl.tr_lst
    first = _positions(rows[0])
    slot = _positions(rows[1])
    proto = {
        "trPr": deepcopy(rows[1].trPr),
        "head": ([tc for col, _s, tc in first if col < 4], [tc for col, _s, tc in first if col >= 4]),
        "slot": ([tc for col, _s, tc in slot if col < 4], [tc for col, _s, tc in slot if col >= 4]),
    }
    for tr in rows:
        for col, span, tc in _positions(tr):
            text = "".join(t.text or "" for t in tc.iter(qn("w:t"))).strip()
            if not text:
                continue
            if col == 0 and span == 4:
                proto.setdefault("title_r", [tc])
            if col == 4 and span == 3:
                proto.setdefault("title_l", [tc])
    proto["title"] = (proto.pop("title_r"), proto.pop("title_l"))
    return proto


def _set_text(tc, text):
    """يحط النص في أول run ويشيل الباقي، مع الحفاظ على تنسيق الخلية."""
    tcpr = tc.tcPr
    vmerge = tcpr.find(qn("w:vMerge")) if tcpr is not None else None
    if vmerge is not None:
        tcpr.remove(vmerge)
    paragraphs = tc.findall(qn("w:p"))
    for extra in paragraphs[1:]:
        tc.remove(extra)
    paragraph = paragraphs[0]
    runs = paragraph.findall(qn("w:r"))
    if runs:
        run = runs[0]
        for extra in runs[1:]:
            paragraph.remove(extra)
    else:
        run = OxmlElement("w:r")
        ppr = paragraph.find(qn("w:pPr"))
        rpr = ppr.find(qn("w:rPr")) if ppr is not None else None
        if rpr is not None:
            run.append(deepcopy(rpr))
        paragraph.append(run)
    for node in list(run):
        if node.tag != qn("w:rPr"):
            run.remove(node)
    if text:
        t = OxmlElement("w:t")
        t.text = str(text)
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        run.append(t)


def _thick_bottom(tc):
    """حد سفلي سميك للخلية (يستبدل حد القالب السفلي بس)."""
    tcpr = tc.get_or_add_tcPr()
    borders = tcpr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tcpr.append(borders)
    node = borders.find(qn("w:bottom"))
    if node is None:
        node = OxmlElement("w:bottom")
        borders.append(node)
    node.set(qn("w:val"), "single")
    node.set(qn("w:sz"), str(THICK))
    node.set(qn("w:space"), "0")
    node.set(qn("w:color"), "000000")
    order = ["top", "start", "left", "bottom", "end", "right", "insideH", "insideV", "tl2br", "tr2bl"]
    kids = sorted(list(borders), key=lambda n: order.index(n.tag.split("}")[1]) if n.tag.split("}")[1] in order else 99)
    for kid in kids:
        borders.remove(kid)
        borders.append(kid)


def _cells(proto, kind, side, item):
    index = 0 if side == "r" else 1
    if kind in ("title", "head"):
        cells = [deepcopy(tc) for tc in proto[kind][index]]
        _set_text(cells[0], item["text"])
    else:
        cells = [deepcopy(tc) for tc in proto["slot"][index]]
        values = item["values"] if kind == "slot" else ["", "", ""]
        if item and item.get("merge"):
            cells = _merge_serial(cells)
        for tc, value in zip(cells, values):
            _set_text(tc, value)
    if item and item.get("thick"):
        for tc in cells:
            _thick_bottom(tc)
    return cells


def _units(blocks):
    units = []
    for block in blocks:
        weapons = list(block.get("weapons") or [])
        slots = []
        for i in range(1, int(block.get("count") or 0) + 1):
            weapon = weapons[i - 1] if i <= len(weapons) else ""
            slots.append({"type": "slot", "values": [f"{i}-", weapon, ""], "merge": has_no_serial(weapon)})
        unit = [{"type": "title", "text": block["title"]}] + slots
        if block.get("group_end"):
            # آخر صف في مجموعة اللوري: حد سفلي سميك يفصلها عن اللي بعدها.
            unit[-1] = {**unit[-1], "thick": True}
        units.append(unit)
    return units


def _split(units):
    """النص اليمين الأول وبعده الشمال، من غير ما خدمة تتقسم، وبأقل ارتفاع ممكن."""
    total = sum(len(unit) for unit in units)
    capacity = max(1, (total + 1) // 2)
    while True:
        halves, used = [[]], 0
        for unit in units:
            if halves[-1] and used + len(unit) > capacity:
                halves.append([])
                used = 0
            halves[-1].extend(unit)
            used += len(unit)
        if len(halves) <= 2:
            halves += [[] for _ in range(2 - len(halves))]
            for half in halves:
                # أول خدمة في كل نص عنوانها فيه «التسليح / رقم السلاح» زي القالب.
                if half and half[0]["type"] == "title":
                    half[0] = {**half[0], "type": "head"}
            return halves
        capacity += 1


def _scale_sizes(tbl, scale):
    for tag in ("w:sz", "w:szCs"):
        for node in tbl.iter(qn(tag)):
            node.set(qn("w:val"), str(max(10, int(round(int(node.get(qn("w:val"))) * scale)))))


def build_docx(dto):
    document = Document(TEMPLATE)
    tbl = document.tables[0]._tbl
    _apply_grid(tbl)
    proto = _prototypes(tbl)
    right, left = _split(_units(dto.get("blocks") or []))
    for tr in list(tbl.tr_lst):
        tbl.remove(tr)
    count = max(len(right), len(left), 1)
    scale = 1.0 if count <= TEMPLATE_ROWS else max(MIN_SCALE, TEMPLATE_ROWS / count)
    for index in range(count):
        tr = OxmlElement("w:tr")
        trpr = deepcopy(proto["trPr"])
        if scale < 1:
            height = trpr.find(qn("w:trHeight"))
            height.set(qn("w:val"), str(int(int(height.get(qn("w:val"))) * scale)))
        tr.append(trpr)
        for side, half in (("r", right), ("l", left)):
            item = half[index] if index < len(half) else None
            kind = item["type"] if item else "blank"
            for tc in _cells(proto, kind, side, item):
                tr.append(tc)
        tbl.append(tr)
    if scale < 1:
        _scale_sizes(tbl, scale)
    LAST_FIT.clear()
    LAST_FIT.update({"page_count": 1, "rows": count, "scale": scale, "template_rows": TEMPLATE_ROWS})
    output = BytesIO()
    document.save(output)
    output.seek(0)
    return output
