"""ملف Word لخط تشكيل مناسبة خاصة على شكل «خط تشكيل مباراة» في الأرشيف.

القالب ``docx_templates/formation_special.docx`` نسخة من أرشيف 2026-09-15
(A4 طولي بإطار صفحة مزدوج). جسم القالب بيتمسح ونبني جدول لكل خدمة لوحدها
(م | الخدمة والقائم بها | التسليح) بخانة مرقّمة لكل مجند — من غير خدمات
ملزوقة تحت بعض في نفس الجدول. الملف ممكن يبقى أكتر من صفحة عادي.

الجدول مايتقسمش على صفحتين: ارتفاعات الصفوف ثابتة (`exact`) فبنحسب بنفسنا
الجدول اللي مش هيكفي في الصفحة ونبدأه في صفحة جديدة، و`keepNext` احتياطي لـWord
لأن OnlyOffice مش بيلتزم بيه جوه الجداول. الجدول الأكبر من صفحة كاملة بس هو اللي
بيكمل في اللي بعدها، بصف عنوانه متكرر.
"""
from io import BytesIO
from math import ceil
from pathlib import Path
from xml.sax.saxutils import escape

from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn

TEMPLATE = Path(__file__).with_name("docx_templates") / "formation_special.docx"
GRID = (1310, 5339, 3133)    # نفس الجدول ذو الخدمة الواحدة في الأرشيف (يمين ← شمال)
HEAD_HEIGHT = 1000
SLOT_HEIGHT = 420
SPACER_HEIGHT = 200
BREAK_HEIGHT = 20
# 16838 طول A4 − 1276 هامش تحت − 990 بداية الجسم (الترويسة بتزقه لتحت هامش الـ284؛
# متقاس في OnlyOffice) − 102 احتياطي لفرق الترويسة في Word.
PAGE_ROOM = 14470
# تقدير محافظ لعدد الحروف في السطر وارتفاع السطر، عشان الارتفاع الثابت مايقصّش نص طويل.
_HEAD_CHARS, _HEAD_LINE = 34, 300
_WEAPON_CHARS, _WEAPON_LINE = 18, 340
_THICK = '<w:{side} w:val="thinThickSmallGap" w:sz="24" w:space="0" w:color="auto"/>'
_THIN = '<w:{side} w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
_HEAD_FONT = '<w:rFonts w:ascii="Bahnschrift SemiBold" w:hAnsi="Bahnschrift SemiBold" w:cs="AdvertisingExtraBold" w:hint="cs"/>'
_BODY_FONT = '<w:rFonts w:cstheme="minorHAnsi"/>'


def _run(text, size, font):
    return (f'<w:r><w:rPr>{font}<w:b/><w:bCs/><w:sz w:val="{size}"/><w:szCs w:val="{size}"/><w:rtl/></w:rPr>'
            f'<w:t xml:space="preserve">{escape(text)}</w:t></w:r>')


def _para(text, size, font, keep=False):
    keep_xml = "<w:keepNext/>" if keep else ""
    return (f'<w:p><w:pPr>{keep_xml}<w:spacing w:before="0" w:after="0"/><w:jc w:val="center"/>'
            f'<w:rPr><w:b/><w:bCs/><w:sz w:val="{size}"/><w:szCs w:val="{size}"/><w:rtl/></w:rPr></w:pPr>'
            f'{_run(text, size, font) if text else ""}</w:p>')


def _cell(width, lines, *, size=28, font=_BODY_FONT, thick=False, keep=False):
    borders = ""
    if thick:
        borders = "<w:tcBorders>" + "".join(_THICK.format(side=s) for s in ("top", "left", "bottom", "right")) + "</w:tcBorders>"
    paras = "".join(_para(line, size, font, keep) for line in (lines or [""]))
    return (f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{borders}'
            f'<w:vAlign w:val="center"/></w:tcPr>{paras}</w:tc>')


def _row(cells, height, header=False):
    repeat = "<w:tblHeader/>" if header else ""
    return (f'<w:tr><w:trPr><w:cantSplit/><w:trHeight w:val="{height}" w:hRule="exact"/>{repeat}</w:trPr>'
            f'{cells}</w:tr>')


def _lines(text, per_line):
    return max(1, ceil(len(str(text or "")) / per_line))


def _head_lines(post):
    return [post["name"], post["head"]] if post["head"] else [post["name"]]


def _head_height(post):
    lines = sum(_lines(line, _HEAD_CHARS) for line in _head_lines(post))
    return max(HEAD_HEIGHT, lines * _HEAD_LINE + 100)


def _slot_weapon(post, number):
    weapons = post["weapons"]
    return weapons[number - 1] if number <= len(weapons) else ""


def _slot_height(post, number):
    return max(SLOT_HEIGHT, _lines(_slot_weapon(post, number), _WEAPON_CHARS) * _WEAPON_LINE + 80)


def _slot_numbers(post):
    return range(1, max(1, post["count"]) + 1)


def table_height(post):
    return _head_height(post) + sum(_slot_height(post, number) for number in _slot_numbers(post))


def is_oversized(post):
    return table_height(post) + BREAK_HEIGHT > PAGE_ROOM


def page_starts(posts):
    """أرقام الجداول اللي بتبدأ صفحة جديدة (غير أول جدول) بالترتيب نفسه من غير
    ما نقدّم خدمة أكبر عشان تملا فراغ."""
    starts, used = set(), 0
    for index, post in enumerate(posts):
        height = table_height(post)
        if index and (is_oversized(post) or used + SPACER_HEIGHT + height > PAGE_ROOM):
            starts.add(index)
            used = BREAK_HEIGHT + height
        elif index:
            used += SPACER_HEIGHT + height
        else:
            used = height
        if is_oversized(post):
            used = PAGE_ROOM        # اللي بعده يبدأ صفحة جديدة
    return starts


def _table(post):
    whole = not is_oversized(post)
    numbers = list(_slot_numbers(post))
    # كل صفوف الجدول لازقة في بعض؛ الجدول الأكبر من صفحة عنوانه بس لازق في أول خاناته.
    rows = [_row(_cell(GRID[0], ["م"], font=_HEAD_FONT, thick=True, keep=True)
                 + _cell(GRID[1], _head_lines(post), size=24, font=_HEAD_FONT, thick=True, keep=True)
                 + _cell(GRID[2], ["التسليح"], font=_HEAD_FONT, thick=True, keep=True),
                 _head_height(post), header=not whole)]
    for number in numbers:
        keep = whole and number != numbers[-1]
        rows.append(_row(_cell(GRID[0], [f"{number}."], size=24, keep=keep) + _cell(GRID[1], [""], keep=keep)
                         + _cell(GRID[2], [_slot_weapon(post, number)], keep=keep), _slot_height(post, number)))
    borders = ("<w:tblBorders>" + "".join(_THICK.format(side=s) for s in ("top", "left", "bottom", "right"))
               + "".join(_THIN.format(side=s) for s in ("insideH", "insideV")) + "</w:tblBorders>")
    grid_xml = "".join(f'<w:gridCol w:w="{w}"/>' for w in GRID)
    return parse_xml(
        f'<w:tbl {nsdecls("w")}><w:tblPr><w:tblStyle w:val="TableGrid"/><w:bidiVisual/>'
        f'<w:tblW w:w="{sum(GRID)}" w:type="dxa"/><w:jc w:val="center"/>{borders}<w:tblLayout w:type="fixed"/>'
        f'<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="1" w:lastColumn="0" w:noHBand="0" w:noVBand="1"/>'
        f'</w:tblPr><w:tblGrid>{grid_xml}</w:tblGrid>{"".join(rows)}</w:tbl>')


def _gap(height, page_break=False):
    """فقرة فاصلة بارتفاع ثابت بين جدولين، أو أول الصفحة الجديدة قبل الجدول."""
    break_xml = "<w:pageBreakBefore/>" if page_break else ""
    return parse_xml(f'<w:p {nsdecls("w")}><w:pPr>{break_xml}'
                     f'<w:spacing w:before="0" w:after="0" w:line="{height}" w:lineRule="exact"/>'
                     f'<w:rPr><w:sz w:val="2"/><w:szCs w:val="2"/></w:rPr></w:pPr></w:p>')


def build_docx(payload):
    document = Document(str(TEMPLATE))
    body = document.element.body
    section_properties = body.find(qn("w:sectPr"))
    for child in list(body):
        if child is not section_properties:
            body.remove(child)
    starts = page_starts(payload["posts"])
    for index, post in enumerate(payload["posts"]):
        if index:
            section_properties.addprevious(
                _gap(BREAK_HEIGHT, True) if index in starts else _gap(SPACER_HEIGHT))
        section_properties.addprevious(_table(post))
    # Word لازم له فقرة بعد آخر جدول؛ ارتفاعها أقل من الاحتياطي فمابتفتحش صفحة زيادة.
    section_properties.addprevious(_gap(BREAK_HEIGHT))
    buffer = BytesIO()
    document.save(buffer)
    buffer.seek(0)
    return buffer
