"""Word (عكس LibreOffice) بيرفض ملف يومية التعيينات لو ترتيب خصائص الفقرة/الخلية/الخط مش بترتيب مخطط OOXML:
«We can't open … Unspecified error — Part: /word/document.xml». الاختبار ده بيمسك أي رجوع للمشكلة."""
from io import BytesIO
from zipfile import ZipFile

from lxml import etree

from backend import assignments_roster_export as export
from backend.assignments_roster_export import _OOXML_ORDER

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _violations(docx_bytes):
    root = etree.fromstring(ZipFile(BytesIO(docx_bytes)).read("word/document.xml"))
    found = []
    for name, sequence in _OOXML_ORDER.items():
        for element in root.iter("{%s}%s" % (W, name)):
            tags = [etree.QName(child).localname for child in element
                    if etree.QName(child).namespace == W]
            indexes = [sequence.index(tag) for tag in tags if tag in sequence]
            if indexes != sorted(indexes) or len(set(tags)) != len(tags):
                found.append((name, tags))
    return found


def test_generated_roster_has_schema_ordered_properties(client):
    response = client.get("/api/assignments-roster/2026-05-02/export.docx")
    assert response.status_code == 200
    assert _violations(response.data) == []


def test_normalizer_fixes_misordered_and_duplicate_properties():
    root = etree.fromstring(
        f'<w:body xmlns:w="{W}"><w:p><w:pPr><w:rPr><w:b/></w:rPr><w:jc w:val="center"/>'
        f'<w:spacing w:before="0"/><w:jc w:val="right"/></w:pPr></w:p>'
        f'<w:tc><w:tcPr><w:vAlign w:val="center"/><w:noWrap/><w:tcW w:w="1"/></w:tcPr></w:tc></w:body>')
    assert export.normalize_ooxml_order(root) == 2
    assert [etree.QName(c).localname for c in root.find(f".//{{{W}}}pPr")] == ["spacing", "jc", "rPr"]
    assert root.find(f".//{{{W}}}jc").get(f"{{{W}}}val") == "right"
    assert [etree.QName(c).localname for c in root.find(f".//{{{W}}}tcPr")] == ["tcW", "noWrap", "vAlign"]
