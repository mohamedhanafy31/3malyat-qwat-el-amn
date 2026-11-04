"""«أمر خدمة يوم …»: مسودة يومية بنفس شكل ملف الأرشيف.

الملف نص حر بيعدّله المشغّل بإيده بعد كده؛ السيستم بيكتب فيه اللي يقدر
يستنتجه من اليومية التفصيلية (وشاشتها) ومدخلات يومية الانتظام، بنفس ترتيب
وصياغة ملفات الأرشيف (أغسطس–أكتوبر 2026):

1. المتابعة الاشرافية (+ العقيد التاني لو له نص إضافي).
2. «مشرف القول المكبر : ص --- … ـــ ل --- …» و«التدخل السريع» بنفس الشكل.
3. باقي الخدمات الأساسية: «بتروجيت صبح : م.اول/ ماركو ماجد».
4. البنود الثابتة بصياغة الأمر: قول الكورنيش، ارتكاز الإسعاف، المحكمة
   (العدد والمعاد من ملاحظات يومية الانتظام)، وأي ملاحظة إضافية زي ما هي.
5. التفتيشات: «تفتيش فيصل : عدد 10 مجند دونك 10ص "فيصل"» — موجودة على
   الشاشة بس ملف Word التفصيلي مابيطبعهاش.
6. الخدمات الطارئة بترتيب الموقع: «الاسم : القوة المعاد "المكان"»، والقوة
   مترجمة لصياغة الأمر («فرد + مج» → «مج قتالية برئاستها»…). حملة الأمن
   الوطني مابتتكتبش في الأمر أبدًا.
7. كتل الخدمات الخاصة: عنوان «المناسبة "المكان" الساعة …» وبنودها من غير
   تكرار المعاد/المكان المشترك.
8. «مركز اصلاح قوات الامن :» وخدمات السجن.
لازم يطلع صفحة واحدة (تصغير الخط والمسافات، وإلا ``PageFitError``).
"""
import re
from collections import Counter
from copy import deepcopy
from datetime import date
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from .afraad import _time_key, basic_rows
from .board_export import WEEKDAY_BY_INDEX, _archive_time, _basic_assignees, _people_list
from .clocktime import compact_time
from .constants import (SECTION_BASIC, SECTION_INSPECTIONS, SECTION_OCCASIONAL,
                        SECTION_PRISON, canonical_section_name)
from .export_fit import PageFitError, TextMeter
from .regularity import _officer_rows, is_big_column
from .service_sections import is_structural, split_custom_sections
from .signatures import fill_boxes, signatories
from .text import norm

TEMPLATE = Path(__file__).with_name("docx_templates") / "service_order.docx"
SUPERVISION = "المتابعة الاشرافية الميدانية على جميع خدمات ادارة قوات الأمن ."
EMPTY = "........"
AMBULANCE = "مايك فض برئاسته للارتكاز أمام صيدلية الاسعاف"
PRISON_TITLE = "مركز اصلاح قوات الامن :"
# نوع الوحدة في القوام → صياغة الأمر. الوحدات بتتكتب «… برئاستها» أو «… برئاسة ضابط».
_UNITS = {"مج": "مج قتالية", "مجموعة": "مج قتالية", "وحدة": "وحدة فض", "وحدة فض": "وحدة فض",
          "وحدة حفظ نظام": "وحدة حفظ نظام", "ميك": "مايك فض", "مايك": "مايك فض",
          "رياضي": "وحدة حفظ نظام رياضي"}
# (حجم الخط pt، ارتفاع السطر كمضاعف للخط — تباعد «exact» عشان الحساب يطابق
# Word/LibreOffice مهما كان ارتفاع الخط العربي الطبيعي) من الأوسع للأضيق.
_STEPS = [(12, 2.0), (12, 1.8), (12, 1.6), (11, 1.6), (11, 1.45), (10, 1.45),
          (10, 1.3), (9, 1.3), (9, 1.2), (8.5, 1.15)]
# العنوان والشعار فوق، والتوقيعات تحت (من القالب)، بالـpt.
_CHROME_PT = 160
LAST_FIT = {}


def _rank_name(rank, name):
    rank = str(rank or "").strip()
    name = re.sub(r"\s*\(.*?\)\s*", " ", str(name or "")).strip()
    if not name:
        return ""
    if rank == "عقيد":
        rank = "العقيد"
    return f"{rank} / {name}" if rank else name


def _shift_pair(rows, needle):
    """{am, pm} → "رتبة / اسم" لصفوف ضباط يومية الانتظام اللي نصها فيه needle."""
    found = {}
    for row in rows:
        service = norm(row.get("service"))
        if norm(needle) not in service:
            continue
        shift = "am" if norm("صباحية") in service else "pm" if norm("ليلية") in service else None
        if shift and shift not in found:
            found[shift] = _rank_name(row.get("rank"), row.get("name"))
    return found


def _label(row):
    return str((row or {}).get("label") or (row or {}).get("name") or "").strip()


def _is_national_security_campaign(row):
    value = norm(_label(row) + " " + str(row.get("name") or ""))
    return "حمل" in value and "وطن" in value


def _strength(row):
    """قوام الخدمة بصياغة الأمر: «مج قتالية برئاستها»، «وحدة فض برئاسة نقيب/…»،
    «برئاسة رائد/… وبصحبته أ.ش/… وعدد 3 مجند طلبة»، «عدد 5 مجند حفظ نظام»."""
    officers = _people_list(row.get("officers"))
    personnel = _people_list(row.get("personnel"))
    units, counted = [], []
    for conscript in row.get("conscripts") or []:
        cls = " ".join(str(conscript.get("class") or "").split())
        count = conscript.get("count")
        unit = _UNITS.get(cls)
        if cls in {"مج", "مجموعة"} and count and int(count) > 1:
            # «6 مجند»/«3 مجند» للماتش: عدد مجندين مش مجموعة قتالية واحدة
            unit = None
            cls = ""
        if unit:
            units.append(unit)
        else:
            counted.append(" ".join(filter(None, [f"عدد {count} مجند" if count else "مجند", cls])))
    if not row.get("conscripts") and row.get("conscript_count"):
        counted.append(f"عدد {row['conscript_count']} مجند")
    head = ("برئاسة " + " و ".join(officers)) if officers else ""
    if units:
        if not head:
            head = "برئاستها"
        text = " ".join(filter(None, [units[0], head]))
        rest = units[1:] + counted
        return " + ".join([text, *rest])
    if officers:
        companions = personnel + counted
        return head + (" وبصحبته " + " و".join(companions) if companions else "")
    if personnel:
        return " + ".join(personnel + counted)
    if counted:
        return " + ".join(counted)
    if row.get("personnel_command_required"):
        return "فرد"
    return (row.get("source_manning") or "").strip()


def _when_where(row, skip_time="", skip_party=""):
    """«8ص "عتاقة"» من غير تكرار اللي في الاسم أو المشترك في الكتلة."""
    name = norm(_label(row)).replace(" ", "")
    time = _archive_time(row.get("time"))
    if time and (time == skip_time or norm(time).replace(" ", "") in name):
        time = ""
    party = str(row.get("party") or "").strip().strip('"').strip()
    quoted = {norm(value).replace(" ", "") for value in re.findall(r'"([^"]*)"', _label(row))}
    if party and (party == skip_party or norm(party).replace(" ", "") in quoted):
        party = ""
    return " ".join(filter(None, [time, f'"{party}"' if party else ""]))


def _service_line(row, skip_time="", skip_party=""):
    name, strength = _label(row), _strength(row)
    tail = " ".join(filter(None, [strength, _when_where(row, skip_time, skip_party)]))
    return f"{name} : {tail}" if tail else name


def _inspection_line(row):
    count = row.get("conscript_count")
    force = " ".join(filter(None, [f"عدد {count} مجند" if count else "",
                                   str(row.get("weapon") or "").strip() or ("حفظ نظام" if count else "")]))
    tail = " ".join(filter(None, [force, _when_where(row)]))
    return f"{_label(row)} : {tail}" if tail else _label(row)


def _block_lines(name, rows):
    """كتلة خاصة: عنوان بالمكان والمعاد المشتركين، وبنود من غير تكرارهم."""
    # معاد المناسبة = أبدرها (بداية الماتش)، والمكان = الأكتر تكرارًا
    timed = sorted((row for row in rows if row.get("time")), key=lambda row: _time_key(row.get("time")))
    time = _archive_time(timed[0].get("time")) if timed else ""
    parties = Counter(str(row.get("party") or "").strip().strip('"').strip()
                      for row in rows if row.get("party"))
    party = parties.most_common(1)[0][0] if parties else ""
    title = " ".join(filter(None, [str(name).strip(), f'"{party}"' if party else "",
                                   f"الساعة {time}" if time else ""]))
    return [title] + [_service_line(row, time, party) for row in rows]


def _prison_lines(rows):
    lines = [PRISON_TITLE]
    for row in rows:
        label = _label(row)
        shift = str(row.get("shift") or "").strip()
        if shift in {"صباحية", "ليلية"} and "فترة" not in label:
            label = f"{label} فترة {shift}"
        officers = _people_list(row.get("officers"))
        if officers:
            lines.append(f"{' و '.join(officers)} : {label}")
        else:
            lines.append(_service_line({**row, "label": label}))
    return lines


def _note_number(note, default):
    match = re.search(r"\(?\s*(\d+)\s*\)?\s*مجند", note or "")
    return match.group(1) if match else default


def _fixed_lines(notes, ambulance_time):
    """البنود الثابتة بصياغة الأمر؛ الأعداد والمعاد من ملاحظات يومية الانتظام."""
    court = next((n for n in notes if "محكم" in norm(n)), None)
    corniche = next((n for n in notes if "كورنيش" in norm(n)), None)
    medical = next((n for n in notes if "المجمع الطبي" in norm(n)), None)
    corniche_time = "7 م"
    if corniche:
        match = re.search(r"من\s*(\d+(?:[.:]\d+)?)\s*(ص|م)", corniche)
        if match:
            corniche_time = f"{match.group(1)} {match.group(2)}"
    lines = [f"قول كورنيش : عدد ( {_note_number(corniche, '1')} ) مجند مسلح خرطوش "
             f"{corniche_time} : الانصراف .",
             " ".join(filter(None, ["ارتكاز الإسعاف :", AMBULANCE, ambulance_time])) + " .",
             f"المحكمة : ({_note_number(court, '10')}) مجند حفظ نظام 8ص ."]
    # أي ملاحظة إضافية للمشغّل تتكتب زي ما هي (الثابتة اتكتبت فوق بصياغة الأمر).
    known = {id(n) for n in (court, corniche, medical) if n}
    lines.extend(str(n).strip() for n in notes if id(n) not in known and str(n).strip())
    return lines


def build(board, regularity_inputs, data, day):
    """payload: {title, day, lines, signatories}."""
    officer_rows = _officer_rows(data, day, regularity_inputs)
    lines = []
    for row in officer_rows:
        who = _rank_name(row.get("rank"), row.get("name"))
        if row.get("kind") == "supervisory":
            extra = str(row.get("service") or "").split(" + ", 1)
            lines.append(f"{who} : " + SUPERVISION + (f" + {extra[1]}" if len(extra) > 1 else ""))
        elif row.get("kind") == "command-extra":
            lines.append(f"{who} : {row.get('service')}")

    big = _shift_pair(officer_rows, "مشرف القول المكبر")
    rapid = _shift_pair(officer_rows, "تدخل")
    lines.append(f"مشرف القول المكبر : ص --- {big.get('am') or EMPTY} "
                 f"ــــــــــــ ل --- {big.get('pm') or EMPTY} .")
    lines.append(f"التدخل السريع : ص --- {rapid.get('am') or EMPTY} "
                 f"ــــــــــــ ل --- {rapid.get('pm') or EMPTY} .")

    sections = {}
    for section in board.get("sections") or []:
        sections.setdefault(canonical_section_name(section.get("name")), section)
    for row in (sections.get(SECTION_BASIC) or {}).get("rows") or []:
        name = _label(row)
        if is_big_column(name) or "تدخل" in norm(name) or "اسعاف" in norm(name):
            continue
        people = _basic_assignees(row)
        if people:
            lines.append(f"{name} : {' + '.join(people)}")

    ambulance = next((row for row in basic_rows(data, day)
                      if "اسعاف" in norm(row.get("name"))), None)
    ambulance_time = compact_time((ambulance or {}).get("schedule") or "")
    lines.extend(_fixed_lines(list(regularity_inputs.get("notes") or []), ambulance_time))

    for row in (sections.get(SECTION_INSPECTIONS) or {}).get("rows") or []:
        lines.append(_inspection_line(row))

    emergency = list((sections.get(SECTION_OCCASIONAL) or {}).get("rows") or [])
    custom = [section for name, section in sections.items()
              if section.get("type") == "services" and not is_structural(name)
              and name not in {SECTION_INSPECTIONS, SECTION_PRISON}]
    ordinary, special_blocks = split_custom_sections(custom, _time_key)
    for row in emergency + ordinary:
        if not _is_national_security_campaign(row):
            lines.append(_service_line(row))
    for block in special_blocks:
        lines.extend(_block_lines(block["name"], block["rows"]))
    prison = (sections.get(SECTION_PRISON) or {}).get("rows") or []
    if prison:
        lines.extend(_prison_lines(prison))

    d = date.fromisoformat(day)
    title = f"امر خدمة يوم {WEEKDAY_BY_INDEX[d.weekday()]} الموافق {d.day}/{d.month}/{d.year}م"
    return {"title": title, "day": day, "lines": [line for line in lines if line],
            "signatories": signatories(data, day)}


def _usable_pt(section):
    return (section.page_height.pt - section.top_margin.pt - section.bottom_margin.pt
            - _CHROME_PT)


def _fit(lines, section):
    meter = TextMeter()
    # عرض النص = الصفحة ناقص الهوامش ومسافة الترقيم، و×0.85 لأن خط القالب
    # (Sultan bold وبدايله) أعرض من خط القياس — أحسن نصغّر زيادة من صفحة تانية.
    width = (section.page_width.pt - section.left_margin.pt - section.right_margin.pt - 50) * .85
    usable = _usable_pt(section)
    for size, spacing in _STEPS:
        total = 0
        for text in lines:
            count = len(meter.wrap_lines(text, width, size, bold=True))
            total += count * _line_pt(size, spacing)
        if total <= usable * .97:
            return size, spacing, total
    raise PageFitError("تعذر احتواء أمر الخدمة في صفحة واحدة؛ قلل عدد البنود أو طول النصوص.")


def _line_pt(size, spacing):
    return round(size * spacing * 2) / 2


def _set_spacing(ppr, size, spacing):
    node = ppr.find(qn("w:spacing"))
    if node is None:
        node = OxmlElement("w:spacing")
        ppr.append(node)
    node.set(qn("w:before"), "0")
    node.set(qn("w:after"), "0")
    node.set(qn("w:line"), str(int(_line_pt(size, spacing) * 20)))
    node.set(qn("w:lineRule"), "exact")
    # w:spacing لازم ييجي قبل w:ind/w:jc/w:rPr في ترتيب pPr
    anchor = next((child for child in ppr if child.tag in {qn("w:ind"), qn("w:jc"), qn("w:rPr")}), None)
    if anchor is not None:
        anchor.addprevious(node)


def _set_size(rpr, size):
    for tag in ("w:sz", "w:szCs"):
        node = rpr.find(qn(tag))
        if node is None:
            node = OxmlElement(tag)
            rpr.append(node)
        node.set(qn("w:val"), str(int(round(size * 2))))


def _item(proto_ppr, proto_rpr, text, size, spacing):
    paragraph = OxmlElement("w:p")
    ppr = deepcopy(proto_ppr)
    _set_spacing(ppr, size, spacing)
    paragraph.append(ppr)
    run = OxmlElement("w:r")
    rpr = deepcopy(proto_rpr)
    _set_size(rpr, size)
    run.append(rpr)
    node = OxmlElement("w:t")
    node.text = text
    node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    run.append(node)
    paragraph.append(run)
    return paragraph


def build_docx(payload):
    document = Document(TEMPLATE)
    section = document.sections[0]
    lines = payload.get("lines") or []
    size, spacing, total = _fit(lines, section)
    title = document.paragraphs[1]
    if title.runs:
        title.runs[0].text = payload.get("title") or ""
        for run in title.runs[1:]:
            run.text = ""
    proto = document.paragraphs[3]._p
    proto_ppr = proto.find(qn("w:pPr"))
    first_run = next(r for r in proto.findall(qn("w:r")) if r.find(qn("w:t")) is not None)
    proto_rpr = first_run.find(qn("w:rPr"))
    anchor = proto
    for text in lines:
        item = _item(proto_ppr, proto_rpr, text, size, spacing)
        anchor.addnext(item)
        anchor = item
    proto.getparent().remove(proto)
    fill_boxes(document, payload.get("signatories") or {})
    LAST_FIT.clear()
    LAST_FIT.update(size_pt=size, spacing=spacing, total_pt=total, page_count=1)
    buffer = BytesIO()
    document.save(buffer)
    buffer.seek(0)
    return buffer
