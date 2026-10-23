from io import BytesIO

from docx import Document

from backend import roster_import, store


def _conscript_docx(*names):
    document = Document()
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[1].text = "الاسم"
    for name in names:
        row = table.add_row()
        row.cells[1].text = name
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def _personnel_doc(rows):
    head = ["م", "الدرجة", "الاسم", "العمل المسند", "العنوان", "رقم الهاتف", "رقم الشرطة"]
    html_rows = [head] + rows
    body = "".join("<tr>" + "".join(f"<td>{value}</td>" for value in row) + "</tr>"
                   for row in html_rows)
    return ("<html><body><table>" + body + "</table></body></html>").encode("utf-8")


def test_parse_supported_word_structures():
    assert [row["name"] for row in roster_import.parse_conscripts(
        _conscript_docx("أحمد محمد", "محمود علي"))] == ["أحمد محمد", "محمود علي"]
    rows = roster_import.parse_personnel(_personnel_doc([
        ["١", "امين شرطة اول", "أحمد محمد", "سائق", "السويس", "٠١٠١٢٣٤٥٦٧٨", "٧٠٠١"],
    ]))
    assert rows[0] == {"row": 1, "role": "أمين شرطة أول", "name": "أحمد محمد",
                       "post": "سائق", "address": "السويس",
                       "phone": "01012345678", "code": "7001"}


def test_conscript_apply_preserves_match_and_detaches_removed_history():
    data = {"conscripts": [
        {"id": "CON-001", "name": "أحمد محمد", "phone": "", "is_driver": True},
        {"id": "CON-002", "name": "قديم", "phone": "", "is_driver": True},
    ], "day_campaign": {"2026-01-01": {"lorries": {"LOR-1": {
        "driver": {"kind": "conscript", "id": "CON-002"}}}}}, "id_seq": {"CON": 2}}
    result = roster_import.apply(data, "conscripts",
                                 _conscript_docx("احمد محمد", "جديد"), "drivers.docx")
    assert data["conscripts"][0]["id"] == "CON-001"
    assert data["conscripts"][1]["id"] == "CON-003"
    assert data["day_campaign"]["2026-01-01"]["lorries"]["LOR-1"]["driver"] == {
        "kind": "text", "id": "", "name": "قديم"}
    assert result["detached_history_refs"] == 1


def test_personnel_apply_replaces_active_and_keeps_archive():
    data = {"personnel": [
        {"id": "IND-001", "name": "أحمد محمد", "role": "أمين شرطة", "code": "old",
         "phone": "", "post": "", "address": "", "join_date": "2020-01-01", "status": "active"},
        {"id": "IND-002", "name": "قديم", "role": "معاون", "code": "2",
         "phone": "", "post": "", "address": "", "join_date": "2020-01-01", "status": "active"},
        {"id": "IND-003", "name": "أرشيف", "role": "معاون", "code": "3",
         "phone": "", "post": "", "address": "", "join_date": "2019-01-01",
         "status": "archived", "leave_date": "2020-01-01"},
    ], "id_seq": {"IND": 3}}
    blob = _personnel_doc([
        ["1", "امين شرطة اول", "احمد محمد", "سائق", "السويس", "01012345678", "7001"],
        ["2", "جندي اول", "فرد جديد", "خدمات", "", "", ""],
    ])
    result = roster_import.apply(data, "personnel", blob, "كشف_2026-10-21.doc")
    active = [row for row in data["personnel"] if row["status"] == "active"]
    archived = [row for row in data["personnel"] if row["status"] == "archived"]
    assert [row["id"] for row in active] == ["IND-001", "IND-004"]
    assert active[1]["code"].startswith("غير مسجل-")
    assert {row["id"] for row in archived} == {"IND-002", "IND-003"}
    assert next(row for row in archived if row["id"] == "IND-002")["leave_date"] == "2026-10-21"
    assert result["total"] == 2 and result["removed"] == 1


def test_personnel_matching_keeps_identity_when_full_name_or_phone_changes():
    data = {"personnel": [
        {"id": "IND-001", "name": "طاهر مجدي رمضان", "role": "أمين شرطة ممتاز",
         "code": "ف-1", "phone": "01140574422", "other_phones": ["01281166758"],
         "post": "التدريب", "address": "", "join_date": "2020-01-01", "status": "active"},
        {"id": "IND-002", "name": "محمد عباس عبدالسميع", "role": "أمين شرطة ثالث",
         "code": "ف-2", "phone": "01000540851", "post": "سائق", "address": "",
         "join_date": "2020-01-01", "status": "active"},
    ], "id_seq": {"IND": 2}}
    blob = _personnel_doc([
        ["1", "امين شرطة ممتاز", "طاهر مجدي رمضان قطب", "التدريب", "", "01281166758", "70596"],
        ["2", "امين شرطة ثالث", "محمد عباس عبدالسميع السيد", "سائق", "", "", "201721"],
    ])
    result = roster_import.apply(data, "personnel", blob, "كشف_2026-10-21.doc")
    assert [row["id"] for row in data["personnel"]] == ["IND-001", "IND-002"]
    assert result["matched"] == 2 and result["added"] == 0 and result["removed"] == 0


def test_roster_import_preview_and_apply_route(client, data_file):
    blob = _conscript_docx("أحمد محمد", "محمود علي")
    response = client.post("/api/roster-import/conscripts/preview", data={
        "file": (BytesIO(blob), "drivers.docx")}, content_type="multipart/form-data")
    assert response.status_code == 200
    preview = response.get_json()
    applied = client.post("/api/roster-import/conscripts/apply", data={
        "file": (BytesIO(blob), "drivers.docx"), "source_hash": preview["source_hash"],
        "revision": preview["revision"], "effective_date": preview["effective_date"],
    }, content_type="multipart/form-data")
    assert applied.status_code == 200
    assert [row["name"] for row in store.assemble()["conscripts"]] == ["أحمد محمد", "محمود علي"]


def test_apply_rejects_file_changed_after_preview(client):
    first = _conscript_docx("أحمد")
    second = _conscript_docx("محمود")
    preview = client.post("/api/roster-import/conscripts/preview", data={
        "file": (BytesIO(first), "drivers.docx")}, content_type="multipart/form-data").get_json()
    response = client.post("/api/roster-import/conscripts/apply", data={
        "file": (BytesIO(second), "drivers.docx"), "source_hash": preview["source_hash"],
        "revision": preview["revision"]}, content_type="multipart/form-data")
    assert response.status_code == 409
    assert response.get_json()["code"] == "source_changed"
