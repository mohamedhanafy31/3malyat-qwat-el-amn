from io import BytesIO

from docx import Document
from docx.oxml.ns import qn

from backend.register_export import build_register_docx, register_file_name
from docx_alignment import alignment_problems


def test_register_engine_rtl_serial_repeat_alignment_and_widths():
    content = build_register_docx("سجل", [("اللوحة", 1), ("الهاتف", 2)],
                                  [["ABC 123", "0100"]], ltr_columns=(0,))
    doc = Document(BytesIO(content))
    table = doc.tables[0]
    assert [c.text for c in table.rows[0].cells] == ["م", "اللوحة", "الهاتف"]
    assert table.rows[1].cells[0].text == "1"
    assert table.rows[0]._tr.get_or_add_trPr().find(qn("w:tblHeader")) is not None
    assert table._tbl.tblPr.find(qn("w:bidiVisual")) is not None
    assert abs(sum(int(c.get(qn("w:w"))) for c in table._tbl.tblGrid) - 10998) < 2
    run = next(run for run in table.rows[1].cells[1].paragraphs[0].runs if run.text)
    assert run._r.get_or_add_rPr().find(qn("w:rtl")).get(qn("w:val")) == "0"
    assert alignment_problems(content) == []
    assert "سجل المركبات 15-11-2026.docx" == register_file_name("سجل المركبات", "2026-11-15")


def test_register_empty_and_landscape():
    doc = Document(BytesIO(build_register_docx("سجل", [(str(i), 1) for i in range(8)], [])))
    assert doc.sections[0].page_width > doc.sections[0].page_height
    assert doc.tables[0].rows[1].cells[1].text == "لا توجد بيانات"
