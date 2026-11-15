from io import BytesIO
from urllib.parse import unquote

from docx import Document

from docx_alignment import alignment_problems

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _doc(client, url):
    response = client.get(url)
    assert response.status_code == 200
    assert response.mimetype == DOCX
    disposition = unquote(response.headers["Content-Disposition"])
    assert "filename*=" in response.headers["Content-Disposition"]
    assert any("\u0600" <= char <= "\u06ff" for char in disposition)
    content = Document(BytesIO(response.data))
    assert alignment_problems(response.data) == []
    return content


def _text(doc):
    return "\n".join(p.text for p in doc.paragraphs) + "\n" + "\n".join(
        cell.text for table in doc.tables for row in table.rows for cell in row.cells)


def test_officer_log_export_has_arabic_register_and_rows(client, anon_client):
    client.post("/api/assignments/2026-04-10", json={"name": "نقطة تفتيش", "kind": "خارجية",
        "shift": "صباحية", "officer_ids": ["OFF-001"]})
    doc = _doc(client, "/api/officer-log/OFF-001/export.docx?date_from=2026-04-10&date_to=2026-04-10")
    assert [c.text for c in doc.tables[0].rows[0].cells] == ["م", "التاريخ", "اليوم", "الخدمات", "الحالة", "ملاحظة"]
    assert "نقطة تفتيش" in _text(doc)
    assert anon_client.get("/api/officer-log/OFF-001/export.docx").status_code == 401
    empty = _doc(client, "/api/officer-log/OFF-001/export.docx?date_from=1990-01-01&date_to=1990-01-02")
    assert "لا توجد بيانات" in _text(empty)


def test_month_register_export_preserves_search_and_officer_ledger(client, anon_client):
    doc = _doc(client, "/api/register/2026/4/export.docx?q=أحمد")
    assert doc.tables[0].rows[0].cells[0].text == "م"
    assert doc.tables[0].rows[0].cells[1].text == "الضابط"
    assert "أحمد محمد" in _text(doc) and "محمود علي" not in _text(doc)
    personal = _doc(client, "/api/register/officer/OFF-001/export.docx")
    assert [c.text for c in personal.tables[0].rows[0].cells] == ["م", "التاريخ", "الرمز", "الحالة", "الخدمات", "ملاحظة"]
    assert anon_client.get("/api/register/2026/4/export.docx").status_code == 401


def test_audit_export_keeps_view_logs_access_and_filters(client, officer_client, individual_client, anon_client):
    from backend.auth.audit_log import emit
    emit("login_ok")
    doc = _doc(client, "/api/audit/export.docx?from=2026-01-01&to=2026-12-31&q=مدير")
    assert [c.text for c in doc.tables[0].rows[0].cells] == ["م", "الوقت", "المستخدم", "الحدث", "التفاصيل"]
    assert "مدير" in _text(doc)
    assert individual_client.get("/api/audit/export.docx").status_code == 403
    assert officer_client.get("/api/audit/export.docx").status_code == 200
    assert anon_client.get("/api/audit/export.docx").status_code == 401
    _doc(client, "/api/audit/export.docx?user=missing-user")


def test_changes_export_keeps_open_access_and_filters(client, individual_client, anon_client):
    row = client.post("/api/assignments/2026-04-10", json={"name": "خدمة التصدير", "kind": "خارجية",
        "officer_ids": ["OFF-001"]}).get_json()
    client.post("/api/board/2026-04-10/confirm", json={})
    client.patch(f"/api/assignments/2026-04-10/{row['id']}", json={"officer_ids": []})
    client.post("/api/board/2026-04-10/confirm", json={})
    doc = _doc(client, "/api/changes/export.docx?entity=duty_move&from_day=2026-04-10&to_day=2026-04-10")
    assert [c.text for c in doc.tables[0].rows[0].cells] == ["م", "وقت التأكيد", "اليومية", "النوع", "العملية", "التغيير", "المُعدِّل"]
    assert "خدمة التصدير" in _text(doc)
    assert individual_client.get("/api/changes/export.docx?entity=unknown").status_code == 200
    assert anon_client.get("/api/changes/export.docx").status_code == 401
