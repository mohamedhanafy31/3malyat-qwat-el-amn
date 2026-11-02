"""ملف Word لخط تشكيل مناسبة خاصة على شكل «خط تشكيل مباراة» في الأرشيف.

القالب ``docx_templates/formation_special.docx`` نسخة من أرشيف 2026-09-15
(A4 طولي بإطار صفحة مزدوج). جسم القالب بيتمسح ونبني جدول لكل خدمة لوحدها
(م | الخدمة والقائم بها | التسليح) بخانة مرقّمة لكل مجند — من غير خدمات
ملزوقة تحت بعض في نفس الجدول. الملف ممكن يبقى أكتر من صفحة عادي.
"""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn

TEMPLATE = Path(__file__).with_name("docx_templates") / "formation_special.docx"
GRID = (1310, 5339, 3133)    # نفس الجدول ذو الخدمة الواحدة في الأرشيف (يمين ← شمال)
HEAD_HEIGHT = 1000
SLOT_HEIGHT = 420
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


def _row(cells, height):
    return f'<w:tr><w:trPr><w:cantSplit/><w:trHeight w:val="{height}"/></w:trPr>{cells}</w:tr>'


def _table(post):
    head_lines = [post["name"], post["head"]] if post["head"] else [post["name"]]
    # عنوان الخدمة بيفضل لازق في أول خاناتها (keepNext) عشان مايتقطعش آخر الصفحة.
    rows = [_row(_cell(GRID[0], ["م"], font=_HEAD_FONT, thick=True, keep=True)
                 + _cell(GRID[1], head_lines, size=24, font=_HEAD_FONT, thick=True, keep=True)
                 + _cell(GRID[2], ["التسليح"], font=_HEAD_FONT, thick=True, keep=True), HEAD_HEIGHT)]
    weapons = post["weapons"]
    for number in range(1, max(1, post["count"]) + 1):
        weapon = weapons[number - 1] if number <= len(weapons) else ""
        rows.append(_row(_cell(GRID[0], [f"{number}."], size=24) + _cell(GRID[1], [""])
                         + _cell(GRID[2], [weapon]), SLOT_HEIGHT))
    borders = ("<w:tblBorders>" + "".join(_THICK.format(side=s) for s in ("top", "left", "bottom", "right"))
               + "".join(_THIN.format(side=s) for s in ("insideH", "insideV")) + "</w:tblBorders>")
    grid_xml = "".join(f'<w:gridCol w:w="{w}"/>' for w in GRID)
    return parse_xml(
        f'<w:tbl {nsdecls("w")}><w:tblPr><w:tblStyle w:val="TableGrid"/><w:bidiVisual/>'
        f'<w:tblW w:w="{sum(GRID)}" w:type="dxa"/><w:jc w:val="center"/>{borders}<w:tblLayout w:type="fixed"/>'
        f'<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="1" w:lastColumn="0" w:noHBand="0" w:noVBand="1"/>'
        f'</w:tblPr><w:tblGrid>{grid_xml}</w:tblGrid>{"".join(rows)}</w:tbl>')


def _spacer():
    return parse_xml(f'<w:p {nsdecls("w")}><w:pPr><w:spacing w:before="0" w:after="0"/>'
                     f'<w:rPr><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr></w:pPr></w:p>')


def build_docx(payload):
    document = Document(str(TEMPLATE))
    body = document.element.body
    section_properties = body.find(qn("w:sectPr"))
    for child in list(body):
        if child is not section_properties:
            body.remove(child)
    for post in payload["posts"]:
        section_properties.addprevious(_table(post))
        section_properties.addprevious(_spacer())
    buffer = BytesIO()
    document.save(buffer)
    buffer.seek(0)
    return buffer
