from io import BytesIO

from docx import Document


def _doc(response):
    assert response.status_code == 200
    assert response.mimetype == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Document(BytesIO(response.data))


def test_vehicle_register_export_tracks_archive_filter(client, anon_client):
    doc = _doc(client.get("/api/vehicles/export.docx?archived=0"))
    assert "سجل المركبات" in "\n".join(p.text for p in doc.paragraphs)
    assert [c.text for c in doc.tables[0].rows[0].cells] == ["م", "اللوحة", "النوع", "الموديل", "الحالة", "ملاحظات"]
    assert anon_client.get("/api/vehicles/export.docx").status_code == 401


def test_drivers_register_export(client, anon_client):
    doc = _doc(client.get("/api/drivers/export.docx"))
    assert "سجل السواقين" in "\n".join(p.text for p in doc.paragraphs)
    assert [c.text for c in doc.tables[0].rows[0].cells] == ["م", "الاسم", "الدرجة", "التليفون", "العمل"]
    assert anon_client.get("/api/drivers/export.docx").status_code == 401


def test_courses_register_export_tracks_view(client, anon_client):
    doc = _doc(client.get("/api/courses/export.docx?view=course"))
    assert "حسب الفرقة" in "\n".join(p.text for p in doc.paragraphs)
    assert [c.text for c in doc.tables[0].rows[0].cells] == ["م", "اسم الفرقة", "المكان", "الضباط والالتحاقات"]
    officer = _doc(client.get("/api/courses/export.docx?view=officer"))
    assert "حسب الضابط" in "\n".join(p.text for p in officer.paragraphs)
    assert anon_client.get("/api/courses/export.docx").status_code == 401


def test_vehicle_export_tolerates_records_without_optional_fields(client):
    """مركبات قديمة كانت بتتحفظ من غير `origin`/`party`؛ التصدير مايقعش (500) عليها."""
    from backend import store
    from backend.models.vehicle import Vehicle

    def add(data):
        item = Vehicle(plate_number="9876", plate_series="ب12", type="لوري").as_dict()
        item["id"] = "VEH-LEGACY"
        for key in ("origin", "party", "notes", "model"):
            item.pop(key, None)
        data.setdefault("vehicles", []).append(item)

    store.with_data(add)
    doc = _doc(client.get("/api/vehicles/export.docx"))
    texts = "\n".join(cell.text for row in doc.tables[0].rows for cell in row.cells)
    assert "ب12/9876" in texts
