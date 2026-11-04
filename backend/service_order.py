"""«أمر خدمة يوم …»: مسودة يومية بنفس شكل ملف الأرشيف.

الملف نص حر بيعدّله المشغّل بإيده بعد كده؛ السيستم بيكتب فيه اللي يقدر
يستنتجه من اليومية التفصيلية ومدخلات يومية الانتظام: المتابعة الاشرافية،
مشرفي القول المكبر والتدخل السريع، باقي ضباط الخدمات الأساسية، الملاحظات
الثابتة، الإسعاف، الخدمات الطارئة بترتيب الموقع، ثم كتل الخدمات الخاصة.
لازم يطلع صفحة واحدة (تصغير الخط والمسافات، وإلا ``PageFitError``).
"""
import re
from copy import deepcopy
from datetime import date
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from .afraad import _time_key
from .board_export import (WEEKDAY_BY_INDEX, _compact_manning, _emergency_name,
                           _people_list, _presentation_sections, _section_by_name)
from .constants import SECTION_OCCASIONAL, canonical_section_name
from .export_fit import PageFitError, TextMeter
from .afraad import basic_rows
from .clocktime import compact_time
from .regularity import _officer_rows, is_big_column
from .service_sections import block_title, is_structural, split_custom_sections
from .signatures import fill_boxes, signatories
from .text import norm

TEMPLATE = Path(__file__).with_name("docx_templates") / "service_order.docx"
SUPERVISION = "المتابعة الاشرافية الميدانية على جميع خدمات ادارة قوات الأمن ."
EMPTY = "........"
AMBULANCE = "مايك فض برئاسته للارتكاز أمام صيدلية الاسعاف"
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
    """{صباحية, ليلية} → "رتبة / اسم" لصفوف ضباط يومية الانتظام اللي نصها فيه needle."""
    found = {}
    for row in rows:
        service = norm(row.get("service"))
        if norm(needle) not in service:
            continue
        shift = "am" if norm("صباحية") in service else "pm" if norm("ليلية") in service else None
        if shift and shift not in found:
            found[shift] = _rank_name(row.get("rank"), row.get("name"))
    return found


def _strength(row):
    """قوام الخدمة بصيغة أمر الخدمة: «برئاسة … + عدد N مجند …»."""
    source = (row.get("source_manning") or "").strip()
    compact = _compact_manning(row)
    if source and compact == source:
        return source
    bits = []
    officers = _people_list(row.get("officers"))
    if officers:
        bits.append("برئاسة " + " و ".join(officers))
    elif row.get("officer_command_required"):
        bits.append("برئاسة ضابط")
    personnel = len(row.get("personnel") or [])
    if personnel or row.get("personnel_command_required"):
        bits.append(f"عدد {personnel} فرد" if personnel > 1 else "فرد")
    for conscript in row.get("conscripts") or []:
        cls = str(conscript.get("class") or "").strip()
        cls = "" if cls in {"مج", "مجند"} else cls
        count = conscript.get("count")
        bits.append(" ".join(filter(None, [f"عدد {count} مجند" if count else "مجند", cls])))
    if row.get("conscript_count") and not row.get("conscripts"):
        bits.append(f"عدد {row['conscript_count']} مجند")
    return " + ".join(bits)


def _line(name, detail):
    name, detail = str(name or "").strip(), str(detail or "").strip()
    return f"{name} : {detail}" if detail else name


def build(board, regularity_inputs, data, day):
    """payload: {title, day, lines, signatories}."""
    officer_rows = _officer_rows(data, day, regularity_inputs)
    lines = []
    for row in officer_rows:
        who = _rank_name(row.get("rank"), row.get("name"))
        if row.get("kind") == "supervisory":
            extra = str(row.get("service") or "").split(" + ", 1)
            text = SUPERVISION + (f" + {extra[1]}" if len(extra) > 1 else "")
            lines.append(_line(who, text))
        elif row.get("kind") == "command-extra":
            lines.append(_line(who, row.get("service")))

    big = _shift_pair(officer_rows, "مشرف القول المكبر")
    rapid = _shift_pair(officer_rows, "تدخل")
    lines.append(f"مشرف القول المكبر : ص --- {big.get('am') or EMPTY} "
                 f"ــــــــــــ ل --- {big.get('pm') or EMPTY} .")
    lines.append(f"التدخل السريع : ص --- {rapid.get('am') or EMPTY} "
                 f"ــــــــــــ ل --- {rapid.get('pm') or EMPTY} .")
    for row in officer_rows:
        service = norm(row.get("service"))
        if row.get("kind") == "basic" and not is_big_column(service) and norm("تدخل") not in service:
            # «ارتكاز الحي الحكومي فترة صباحية : نقيب / عبدالرحمن طارق»
            text = re.sub(r'\s*"[^"]*"\s*', " ", str(row.get("service") or "")).strip()
            lines.append(_line(text, _rank_name(row.get("rank"), row.get("name"))))

    lines.extend(str(note).strip() for note in regularity_inputs.get("notes") or [] if str(note).strip())

    sections = [{**section, "name": canonical_section_name(section.get("name"))}
                for section in _presentation_sections(board.get("sections") or [])]
    ambulance = next((row for row in basic_rows(data, day)
                      if "اسعاف" in norm(row.get("name"))), None)
    if ambulance:
        time = compact_time(ambulance.get("schedule") or "")
        lines.append(_line("ارتكاز الإسعاف", " ".join(filter(None, [AMBULANCE, time]))))

    emergency = list(_section_by_name(sections, SECTION_OCCASIONAL, "services").get("rows") or [])
    custom = [section for section in sections
              if section.get("type") == "services" and not is_structural(section.get("name"))]
    ordinary, special_blocks = split_custom_sections(custom, _time_key)
    for row in emergency + ordinary:
        lines.append(_line(_emergency_name(row), _strength(row)))
    for block in special_blocks:
        lines.append(block_title(block["name"]))
        for row in block["rows"]:
            lines.append(_line(_emergency_name(row), _strength(row)))

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
