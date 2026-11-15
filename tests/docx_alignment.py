"""فاحص مشترك لمحاذاة الجداول في ملفات Word المصدَّرة: كل خلية فيها نص لازم
تكون في المنتصف أفقيًا ورأسيًا («center of center»)."""
from io import BytesIO

from docx import Document
from docx.oxml.ns import qn


def _paragraph_alignment(paragraph):
    properties = paragraph._p.pPr
    node = properties.find(qn("w:jc")) if properties is not None else None
    return node.get(qn("w:val")) if node is not None else None


def _vertical_alignment(cell):
    properties = cell._tc.tcPr
    node = properties.find(qn("w:vAlign")) if properties is not None else None
    return node.get(qn("w:val")) if node is not None else None


def _walk(table, path, problems):
    for row_index, row in enumerate(table.rows):
        seen = set()
        for cell in row.cells:
            if id(cell._tc) in seen:        # الخلية المدموجة بتتكرر في row.cells
                continue
            seen.add(id(cell._tc))
            for nested_index, nested in enumerate(cell.tables):
                _walk(nested, f"{path}.r{row_index}.nested{nested_index}", problems)
            text = cell.text.strip()
            if not text:
                continue
            where = f"{path}.r{row_index} «{text[:24]}»"
            if _vertical_alignment(cell) != "center":
                problems.append(f"{where}: مش في منتصف الخلية رأسيًا ({_vertical_alignment(cell)})")
            bad = {_paragraph_alignment(p) for p in cell.paragraphs if p.text.strip()} - {"center"}
            if bad:
                problems.append(f"{where}: مش في المنتصف أفقيًا ({sorted(map(str, bad))})")


def alignment_problems(content):
    """-> قايمة مشاكل المحاذاة في كل جداول الملف (فاضية = كله center/center)."""
    document = Document(BytesIO(content) if isinstance(content, (bytes, bytearray)) else content)
    problems = []
    for index, table in enumerate(document.tables):
        _walk(table, f"table{index}", problems)
    return problems
