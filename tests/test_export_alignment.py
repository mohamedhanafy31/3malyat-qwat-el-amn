"""تأكيد محاذاة كل ملفات Word القابلة للتنزيل."""
from io import BytesIO

import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

from backend import store
from docx_alignment import alignment_problems


DAY = "2026-10-20"


@pytest.mark.parametrize("export_name,url", [
    ("people officers", "/api/people/officers/export.docx"),
    ("people personnel", "/api/people/personnel/export.docx"),
    ("board detailed daily", f"/api/board/{DAY}/export.docx"),
    ("duty", f"/api/duty/{DAY}/export.docx"),
    ("afraad", f"/api/afraad/{DAY}/export.docx"),
    ("campaign", f"/api/campaign/{DAY}/export.docx"),
    ("leaves monthly", "/api/leaves/monthly/export.docx?on=2026-10-20"),
    ("leaves weekly", "/api/leaves/weekly/export.docx?on=2026-10-20"),
    ("regularity", f"/api/ops/{DAY}/regularity.docx"),
    ("special regularity", f"/api/ops/{DAY}/special-regularity.docx?section=مناسبة"),
    ("formation morning", f"/api/ops/{DAY}/formation-morning.docx"),
    ("formation night", f"/api/ops/{DAY}/formation-night.docx"),
    ("special formation", f"/api/ops/{DAY}/special-formation.docx?section=مناسبة"),
])
def test_downloaded_word_tables_are_center_center(client, export_name, url):
    _seed_alignment_data(client)
    response = client.get(url)
    assert response.status_code == 200, f"{export_name}: {response.get_data(as_text=True)[:300]}"
    assert alignment_problems(response.data) == [], export_name
    if export_name in {"board detailed daily", "duty", "campaign", "regularity",
                       "formation morning", "formation night"}:
        document = Document(BytesIO(response.data))
        merge_tags = {qn("w:gridSpan"), qn("w:hMerge"), qn("w:vMerge")}
        assert any(node.tag in merge_tags for table in document.tables
                   for node in table._tbl.iter()), f"{export_name}: fixture must produce merged cells"


def _seed_alignment_data(client):
    """بيانات طويلة ومتعددة السطور تغطي الخلايا والدمج في ملفات التشغيل."""
    def enrich(data):
        data["officers"][0]["name"] = "أحمد محمد عبد الرحمن حسن الطويل جدًا لاختبار التفاف الاسم داخل خلية الكشف"
        data["officers"][0]["post"] = "خدمة أولى\nخدمة ثانية"
        data["personnel"] = [{"id": "IND-ALIGN", "name": "هاني محمد إبراهيم سالم", "role": "أمين شرطة",
                              "status": "active", "post": "ملاحظة أولى\nملاحظة ثانية"}]
        data["leaves"][0]["note"] = "ملاحظة الراحة\nاستكمال بيانات"
        data["leaves"].append({"id": "LV-ALIGN", "person_id": "OFF-001", "type": "شهرية",
                               "start": DAY, "end": DAY, "return_date": "2026-10-21",
                               "note": "ملاحظة أولى\nملاحظة ثانية", "source": "اختبار"})

    store.with_data(enrich)
    for payload in (
        {"name": "خدمة تشغيلية طويلة الاسم لاختبار التفاف النص في الجداول", "kind": "خارجية",
         "section": "الخدمات الطارئة", "officer_ids": ["OFF-001", "OFF-002"],
         "personnel_ids": ["IND-ALIGN"], "conscript_count": 3, "weapon": "آلي", "time": "8ص",
         "note": "ملاحظة أولى\nملاحظة ثانية"},
        {"name": "مناسبة اختبار", "kind": "خارجية", "section": "مناسبة",
         "officer_ids": ["OFF-001", "OFF-002"], "conscript_count": 2, "time": "9ص",
         "note": "خدمة المناسبة\nتجهيز مبكر"},
    ):
        response = client.post(f"/api/assignments/{DAY}", json=payload)
        assert response.status_code == 201, response.get_json()


@pytest.mark.parametrize("url", [
    "/api/vehicles/export.docx?archived=0",
    "/api/drivers/export.docx",
    "/api/courses/export.docx?view=course",
    "/api/courses/export.docx?view=officer",
    "/api/leaves/export.docx?tab=all&type=أسبوعية",
    "/api/rest-suspensions/export.docx",
    "/api/missions/export.docx?day=2026-04-10",
    "/api/service-catalog/export.docx",
    "/api/target-commanders/export.docx?day=2026-04-10",
    "/api/officer-log/OFF-001/export.docx?date_from=2026-04-10&date_to=2026-04-10",
    "/api/register/2026/4/export.docx?q=أحمد",
    "/api/register/officer/OFF-001/export.docx",
    "/api/audit/export.docx?from=2026-01-01&to=2026-12-31&q=مدير",
    "/api/changes/export.docx?entity=duty_move&from_day=2026-04-10&to_day=2026-04-10",
])
def test_register_exports_are_center_center(client, url):
    response = client.get(url)
    assert response.status_code == 200, f"{url}: {response.get_data(as_text=True)[:300]}"
    assert alignment_problems(response.data) == [], url


def test_alignment_checker_reports_left_aligned_cell():
    document = Document()
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "خلية للاختبار"
    table.cell(0, 0).paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.LEFT
    output = BytesIO()
    document.save(output)
    problems = alignment_problems(output.getvalue())
    assert any("مش في المنتصف أفقيًا" in problem for problem in problems)
