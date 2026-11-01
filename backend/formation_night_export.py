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

TEMPLATE = Path(__file__).with_name("docx_templates") / "formation_night.docx"
TEMPLATE_ROWS = 42           # عدد صفوف جدول القالب اللي بيملا الصفحة
MIN_SCALE = .7               # أقل تصغير للخط/الارتفاع لو الصفوف زادت عن القالب
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


def _cells(proto, kind, side, item):
    index = 0 if side == "r" else 1
    if kind in ("title", "head"):
        cells = [deepcopy(tc) for tc in proto[kind][index]]
        _set_text(cells[0], item["text"])
        return cells
    cells = [deepcopy(tc) for tc in proto["slot"][index]]
    values = item["values"] if kind == "slot" else ["", "", ""]
    for tc, value in zip(cells, values):
        _set_text(tc, value)
    return cells


def _units(blocks):
    units = []
    for block in blocks:
        weapons = list(block.get("weapons") or [])
        slots = [{"type": "slot", "values": [f"{i}-", weapons[i - 1] if i <= len(weapons) else "", ""]}
                 for i in range(1, int(block.get("count") or 0) + 1)]
        units.append([{"type": "title", "text": block["title"]}] + slots)
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
