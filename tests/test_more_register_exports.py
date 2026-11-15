from io import BytesIO
from urllib.parse import unquote
from urllib.parse import urlencode
import json

from docx import Document
from backend.store import load_data, save_data

from docx_alignment import alignment_problems


DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _document(response, filename):
    assert response.status_code == 200
    assert response.mimetype == DOCX
    assert filename in unquote(response.headers["Content-Disposition"])
    assert alignment_problems(response.data) == []
    return Document(BytesIO(response.data))


def _headers(document):
    return [cell.text for cell in document.tables[0].rows[0].cells]


def _fixture_rows(**values):
    data = load_data(())
    data.update(values)
    save_data(data)


def test_leave_register_export_filters_fixture_and_requires_auth(client, anon_client):
    doc = _document(client.get("/api/leaves/export.docx?tab=all&type=أسبوعية"), "سجل الراحات")
    assert _headers(doc) == ["م", "الاسم", "النوع", "من", "إلى", "العودة", "الأيام", "الحالة", "ملاحظات"]
    assert "أحمد محمد" in " ".join(c.text for r in doc.tables[0].rows for c in r.cells)
    assert anon_client.get("/api/leaves/export.docx").status_code == 401


def test_suspension_register_export_empty_and_requires_auth(client, anon_client):
    empty = _document(client.get("/api/rest-suspensions/export.docx"), "سجل أوامر وقف الراحات")
    assert "لا توجد بيانات" in " ".join(c.text for r in empty.tables[0].rows for c in r.cells)
    _fixture_rows(rest_suspensions=[{"id": "SUS-1", "types": ["أسبوعية", "شهرية"], "started_on": "2026-04-01", "reason": "تنظيم الإجازات"}])
    doc = _document(client.get("/api/rest-suspensions/export.docx"), "سجل أوامر وقف الراحات")
    assert _headers(doc) == ["م", "الحالة", "الأنواع", "من", "فُتح", "السبب", "الراحات المتأثرة"]
    assert "تنظيم الإجازات" in " ".join(c.text for r in doc.tables[0].rows for c in r.cells)
    assert anon_client.get("/api/rest-suspensions/export.docx").status_code == 401


def test_mission_register_export_uses_selected_date(client, anon_client):
    empty = _document(client.get("/api/missions/export.docx?day=2026-04-10"), "كشف المأموريات والتراحيل")
    assert "لا توجد بيانات" in " ".join(c.text for r in empty.tables[0].rows for c in r.cells)
    _fixture_rows(day_assignments={"2026-04-10": [{"id": "ASG-1", "name": "ترحيلات الجيزة", "kind": "خارجية", "section": "خدمات اليوم", "shift": "صباحي", "mission_transport": True, "officer_ids": [], "personnel_ids": [], "conscripts": [], "conscript_count": 2, "time": "08:00", "party": "إدارة المرور", "weapon": "بندقية", "note": "تجهيز مبكر"}]})
    doc = _document(client.get("/api/missions/export.docx?day=2026-04-10"), "كشف المأموريات والتراحيل")
    assert _headers(doc) == ["م", "التصنيف", "القسم", "الخدمة", "الفترة", "القائمون بها", "المجندون", "الانتظام", "الجهة", "التسليح", "ملاحظات"]
    assert "10 أبريل 2026" in "\n".join(p.text for p in doc.paragraphs)
    assert "ترحيلات الجيزة" in " ".join(c.text for r in doc.tables[0].rows for c in r.cells)
    assert anon_client.get("/api/missions/export.docx?day=2026-04-10").status_code == 401


def test_service_catalog_register_export_empty_and_requires_auth(client, anon_client):
    empty = _document(client.get("/api/service-catalog/export.docx"), "دليل الخدمات")
    assert "لا توجد بيانات" in " ".join(c.text for r in empty.tables[0].rows for c in r.cells)
    _fixture_rows(service_catalog=[{"id": "SVC-1", "name": "ارتكاز البوابة", "period": "صباحية بس", "kind": "خارجية", "post_type": "ارتكاز", "has_command": True, "command_officers": 1, "command_individuals": 2, "count": 3, "weapon": "بندقية", "instructions": "تسجيل الحركة", "location_text": "البوابة الرئيسية", "location_images": [], "tags": ["بوابة"], "report_am": "08:00", "report_pm": "", "order": 0}])
    doc = _document(client.get("/api/service-catalog/export.docx"), "دليل الخدمات")
    assert _headers(doc) == ["م", "الخدمة", "نوع النقطة", "الفترة", "التصنيف", "المجندون", "الرئاسة", "التسليح", "الانتظام", "التعليمات", "الوسوم", "الموقع"]
    assert "ارتكاز البوابة" in " ".join(c.text for r in doc.tables[0].rows for c in r.cells)
    assert anon_client.get("/api/service-catalog/export.docx").status_code == 401


def test_target_commanders_register_export_uses_date_and_requires_auth(client, anon_client):
    view = client.get("/api/target-commanders/2026-04-10").get_json()
    target = view["targets"][0]["name"]
    officer = view["officers"][0]
    query = urlencode({"day": "2026-04-10", "assignments": json.dumps({target: officer["id"]}, ensure_ascii=False)})
    doc = _document(client.get("/api/target-commanders/export.docx?" + query), "قادة الأهداف")
    assert _headers(doc) == ["م", "الهدف", "القائد الحالي", "القائد الجديد", "حالة الصف"]
    assert "10 أبريل 2026" in "\n".join(p.text for p in doc.paragraphs)
    assert doc.tables[0].rows[1].cells[1].text
    assert doc.tables[0].rows[1].cells[3].text == f"{officer['role']}/ {officer['name']}"
    assert anon_client.get("/api/target-commanders/export.docx?day=2026-04-10").status_code == 401


def test_exports_match_existing_data_api_role_access(conscript_client):
    pairs = [
        ("/api/bootstrap/leaves", "/api/leaves/export.docx"),
        ("/api/rest-suspensions", "/api/rest-suspensions/export.docx"),
        ("/api/missions/day/2026-04-10", "/api/missions/export.docx?day=2026-04-10"),
        ("/api/service-catalog", "/api/service-catalog/export.docx"),
        ("/api/target-commanders/2026-04-10", "/api/target-commanders/export.docx?day=2026-04-10"),
    ]
    for data_url, export_url in pairs:
        assert conscript_client.get(export_url).status_code == conscript_client.get(data_url).status_code


def test_deleted_leave_export_caps_newest_rows_and_marks_footer(client, monkeypatch):
    import backend.routes.leaves as leave_routes

    monkeypatch.setattr(leave_routes, "history_rows", lambda _data: [
        {"person_name": f"اسم {index}", "before": {"type": "أسبوعية", "start": "2026-01-01", "end": "2026-01-01"},
         "display_type": "أسبوعية", "origin_label": "سجل", "action_label": "حذف", "performed_by": "مشغل",
         "occurred_at": "2026-01-02T08:00:00", "reason": "", "restored_at": "", "restored_by": ""}
        for index in range(3000, -1, -1)])
    doc = _document(client.get("/api/leaves/export.docx?tab=deleted"), "سجل الراحات المحذوفة والملغية")
    assert len(doc.tables[0].rows) == 3001
    assert "اسم 3000" in doc.tables[0].rows[1].cells[1].text
    assert "تم عرض أحدث 3000 سجل فقط" in doc.sections[0].footer.paragraphs[0].text
