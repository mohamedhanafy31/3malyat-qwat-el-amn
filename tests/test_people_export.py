"""كشف Word بيانات الضباط/الأفراد + نسخته في آخر يوم في الأرشيف، ونص
مدير/وكيل الإدارة في يومية الضباط بدل «صافي»."""
from io import BytesIO
from urllib.parse import unquote
from zipfile import ZipFile

from docx import Document
from docx.oxml.ns import qn
from lxml import etree

from backend.people_export import build_docx

DIRECTOR, DEPUTY = "مدير الإدارة", "وكيل الإدارة"


def _main_table(document):
    """جدول البيانات هو اللي هيدره بيبدأ بـ«م»، مش جدول الترويسة."""
    return next(table for table in document.tables
                if table.rows and table.rows[0].cells[0].text == "م")


def _data_rows(table):
    return [row for row in table.rows[1:] if row.cells[0].text.isdigit()]


def test_officers_export_is_a_table_saved_in_the_latest_day_folder(client, tmp_path, monkeypatch):
    root = tmp_path / "archive"
    monkeypatch.setenv("DAILY_FILES_ROOT", str(root))
    (root / "2026" / "10" / "9").mkdir(parents=True)
    (root / "2026" / "10" / "28").mkdir(parents=True)
    (root / "2026" / "9" / "30").mkdir(parents=True)
    response = client.get("/api/people/officers/export.docx")
    assert response.status_code == 200
    name = unquote(response.headers["Content-Disposition"].split("filename*=")[-1].removeprefix("UTF-8''"))
    assert name.startswith("بيانات الضباط ") and name.endswith(".docx")
    assert unquote(response.headers["X-Saved-To"]) == f"2026/10/28/{name}"
    assert (root / "2026" / "10" / "28" / name).read_bytes() == response.data
    table = _main_table(Document(BytesIO(response.data)))
    assert [cell.text for cell in table.rows[0].cells][:3] == ["م", "الرتبة", "الاسم"]
    assert _data_rows(table)[0].cells[0].text == "1"


def test_personnel_export_without_archive_days_just_downloads(client, tmp_path, monkeypatch):
    monkeypatch.setenv("DAILY_FILES_ROOT", str(tmp_path / "empty"))
    response = client.get("/api/people/personnel/export.docx")
    assert response.status_code == 200 and "X-Saved-To" not in response.headers
    header = [cell.text for cell in _main_table(Document(BytesIO(response.data))).rows[0].cells]
    assert header == ["م", "الدرجة", "الاسم", "الكود", "العمل", "العنوان", "الهاتف"]
    assert client.get("/api/people/x/export.docx").status_code == 404


def test_export_subset_uses_canonical_column_order(client, tmp_path, monkeypatch):
    monkeypatch.setenv("DAILY_FILES_ROOT", str(tmp_path / "empty"))
    response = client.get("/api/people/officers/export.docx?columns=phone,rank,name")
    assert response.status_code == 200
    header = [cell.text for cell in _main_table(Document(BytesIO(response.data))).rows[0].cells]
    assert header == ["م", "الرتبة", "الاسم", "الهاتف"]


def test_export_has_no_group_rows_and_serial_continues():
    data = {
        "officers": [
            {"id": "O1", "role": "عقيد", "name": "أحمد", "status": "active"},
            {"id": "O2", "role": "عقيد", "name": "محمود", "status": "active"},
            {"id": "O3", "role": "نقيب", "name": "علي", "status": "active"},
        ],
        "command": {DIRECTOR: None, DEPUTY: None},
    }
    table = _main_table(Document(BytesIO(build_docx(data, "officers", "2026-11-02"))))
    assert table.rows[1].cells[0].text == "1"
    assert all(row.cells[0].text.isdigit() for row in table.rows[1:])
    assert [row.cells[0].text for row in _data_rows(table)] == ["1", "2", "3"]


def test_header_repeats_footer_has_page_field_and_director_post_prefix():
    data = {
        "officers": [
            {"id": "O1", "role": "عقيد", "name": "أحمد", "post": "العمليات",
             "status": "active"},
        ],
        "command": {DIRECTOR: "O1", DEPUTY: None},
    }
    document = Document(BytesIO(build_docx(data, "officers", "2026-11-02")))
    table = _main_table(document)
    assert table.rows[0]._tr.get_or_add_trPr().find(qn("w:tblHeader")) is not None
    director = _data_rows(table)[0]
    assert "مدير الإدارة — العمليات" in " | ".join(cell.text for cell in director.cells)
    assert "PAGE" in document.sections[0].footer._element.xml


def test_document_is_black_and_white_and_contains_both_template_logos():
    data = {"officers": [{"id": "O1", "role": "رائد", "name": "أحمد",
                           "status": "active"}],
            "command": {DIRECTOR: None, DEPUTY: None}}
    content = build_docx(data, "officers", "2026-11-02")
    namespaces = {
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    with ZipFile(BytesIO(content)) as package:
        root = etree.fromstring(package.read("word/document.xml"))
        fills = [node.get(qn("w:fill")) for node in root.xpath(".//w:shd", namespaces=namespaces)]
        assert all(fill in {None, "auto", "none"} for fill in fills)
        colours = [value.upper() for value in root.xpath(".//@w:color", namespaces=namespaces)]
        assert all(value in {"000000", "AUTO"} for value in colours)

        drawings = root.xpath(".//w:drawing", namespaces=namespaces)
        embeds = root.xpath(".//w:drawing//a:blip/@r:embed", namespaces=namespaces)
        assert len(drawings) == len(embeds) == 2
        assert all(drawing.xpath("./wp:inline | ./wp:anchor", namespaces=namespaces)
                   for drawing in drawings)
        rels = etree.fromstring(package.read("word/_rels/document.xml.rels"))
        targets = {node.get("Id"): node.get("Target") for node in rels}
        assert all(f"word/{targets[embed]}" in package.namelist() for embed in embeds)


def test_margins_and_formal_plain_summary():
    data = {"officers": [{"id": "O1", "role": "عقيد", "name": "أحمد",
                           "status": "active"}],
            "command": {DIRECTOR: None, DEPUTY: None}}
    document = Document(BytesIO(build_docx(data, "officers", "2026-11-02")))
    section = document.sections[0]
    assert section.left_margin.cm <= 1
    assert section.right_margin.cm <= 1
    assert section.top_margin.cm <= 1
    assert section.bottom_margin.cm <= 1
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "إجمالي القوة: 1 ضابط (قادة 1 — أعوان 0)" in text


def test_column_subset_has_data_immediately_after_header_and_scaled_table():
    data = {"officers": [{"id": "O1", "role": "رائد", "name": "أحمد",
                           "phone": "0100", "status": "active"}],
            "command": {DIRECTOR: None, DEPUTY: None}}
    table = _main_table(Document(BytesIO(
        build_docx(data, "officers", "2026-11-02", ["phone", "rank", "name"]))))
    assert [cell.text for cell in table.rows[0].cells] == ["م", "الرتبة", "الاسم", "الهاتف"]
    assert table.rows[1].cells[0].text == "1"
    grid_width = sum(int(column.get(qn("w:w"))) for column in table._tbl.tblGrid)
    assert abs(grid_width - 10998) <= 2  # 19.4 سم بالـ twips


def test_export_rejects_unknown_column(client, tmp_path, monkeypatch):
    monkeypatch.setenv("DAILY_FILES_ROOT", str(tmp_path / "empty"))
    response = client.get("/api/people/personnel/export.docx?columns=name,secret")
    assert response.status_code == 400
    assert response.get_json()["error"] == "أعمدة غير معروفة: secret"


def test_export_columns_endpoint_excludes_serial(client):
    response = client.get("/api/people/officers/export-columns")
    assert response.status_code == 200
    assert response.get_json() == [
        {"key": "rank", "title": "الرتبة"},
        {"key": "name", "title": "الاسم"},
        {"key": "code", "title": "الأقدمية"},
        {"key": "post", "title": "العمل المسند"},
        {"key": "rest", "title": "نظام الراحة"},
        {"key": "phone", "title": "الهاتف"},
    ]


def test_director_and_deputy_without_service_show_their_post_not_net(client):
    client.patch("/api/command", json={DIRECTOR: "OFF-001"})
    client.patch("/api/command", json={DEPUTY: "OFF-002"})
    rows = {row["id"]: row for row in client.get("/api/duty/2026-04-01").get_json()["rows"]}
    assert rows["OFF-001"]["text"] == DIRECTOR
    assert rows["OFF-002"]["text"] == DEPUTY
