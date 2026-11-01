"""خانات التوقيع (مدير الإدارة / وكيل الإدارة / رئيس قسم العمليات) في ملفات Word.

القوالب المنسوخة من الأرشيف فيها التوقيعات text boxes بأشكال مختلفة (سطور فاضية،
مسافات للتوسيط، «عقيد /» مرة و«عقيد/» مرة). هنا كل خانة بتتكتب بنفس الشكل:
3 سطور في النص — المسمى، ثم «الرتبة/»، ثم «(الاسم)» — والأسماء من بيانات اليوم.
"""
from copy import deepcopy

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from .dated import command_on
from .people import effective, officers_on
from .repo import PeopleRepo
from .text import norm

# المفتاح ← (اللي بيميّز الخانة في نص القالب بعد شيل التطويل والمسافات، الرتبة/الاسم الاحتياطي)
BOXES = {
    "director": ("مديرإدارة", "عقيد", "أحمد سمير"),
    "deputy": ("وكيلإدارة", "عقيد", "محمد فؤاد"),
    "operations": ("رئيسقسمالعمليات", "رائد", "محمد بحر"),
}


def _short(person):
    return person.get("short_name") or " ".join(str(person.get("name", "")).split()[:2])


def _officer(data, day, ident):
    raw, category, _ = PeopleRepo(data).locate(str(ident or ""))
    if raw is None or category != "officers":
        return None
    return {**raw, **effective(raw, day)}


def signatories(data, day):
    """{director|deputy|operations: {rank, name}} حسب قيادة اليوم ووظايف الضباط."""
    command = command_on(data, day)
    result = {}
    for key, post in (("director", "مدير الإدارة"), ("deputy", "وكيل الإدارة")):
        person = _officer(data, day, command.get(post))
        result[key] = ({"rank": person.get("role") or BOXES[key][1], "name": _short(person)}
                       if person else {"rank": BOXES[key][1], "name": BOXES[key][2]})
    chief_post = norm("رئيس قسم العمليات")
    chief = next(({**person, **effective(person, day)} for person in officers_on(data, day)
                  if chief_post in norm(effective(person, day).get("post"))), None)
    result["operations"] = ({"rank": chief.get("role") or "رائد", "name": _short(chief)}
                            if chief else {"rank": "رائد", "name": "محمد بحر"})
    return result


def _plain(text):
    return "".join(str(text or "").replace("ـ", "").split())


def _paragraph(proto_ppr, proto_rpr, text):
    paragraph = OxmlElement("w:p")
    ppr = deepcopy(proto_ppr) if proto_ppr is not None else OxmlElement("w:pPr")
    for tag in ("w:ind", "w:jc", "w:spacing"):
        for node in ppr.findall(qn(tag)):
            ppr.remove(node)
    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:before"), "0")
    spacing.set(qn("w:after"), "0")
    jc = OxmlElement("w:jc")
    jc.set(qn("w:val"), "center")
    # ترتيب عناصر pPr في المخطط: ... spacing ثم ind ثم ... jc ... ثم rPr في الآخر.
    rpr_in_ppr = ppr.find(qn("w:rPr"))
    if rpr_in_ppr is not None:
        rpr_in_ppr.addprevious(spacing)
        rpr_in_ppr.addprevious(jc)
    else:
        ppr.append(spacing)
        ppr.append(jc)
    paragraph.append(ppr)
    run = OxmlElement("w:r")
    if proto_rpr is not None:
        run.append(deepcopy(proto_rpr))
    t = OxmlElement("w:t")
    t.text = text
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    run.append(t)
    paragraph.append(run)
    return paragraph


def fill_boxes(document, names):
    """يكتب كل خانة توقيع بنفس الشكل. بيرجع عدد الخانات اللي اتكتبت."""
    written = 0
    for box in document.part.element.iter(qn("w:txbxContent")):
        paragraphs = box.findall(qn("w:p"))
        texts = ["".join(t.text or "" for t in p.iter(qn("w:t"))) for p in paragraphs]
        joined = _plain("".join(texts))
        key = next((k for k, (marker, _r, _n) in BOXES.items() if marker in joined), None)
        if key is None or not paragraphs:
            continue
        # المسمى زي ما هو في القالب (بالتطويل بتاعه)؛ الرتبة والاسم من البيانات.
        title = next(" ".join(text.split()) for text in texts if text.strip())
        first_run = next((r for p in paragraphs for r in p.iter(qn("w:r")) if r.find(qn("w:t")) is not None), None)
        proto_rpr = first_run.find(qn("w:rPr")) if first_run is not None else None
        proto_ppr = paragraphs[0].find(qn("w:pPr"))
        item = names.get(key) or {}
        lines = [title, f"{item.get('rank') or BOXES[key][1]}/", f"({item.get('name') or BOXES[key][2]})"]
        new = [_paragraph(proto_ppr, proto_rpr, line) for line in lines]
        for paragraph in paragraphs:
            box.remove(paragraph)
        for paragraph in new:
            box.append(paragraph)
        written += 1
    return written
