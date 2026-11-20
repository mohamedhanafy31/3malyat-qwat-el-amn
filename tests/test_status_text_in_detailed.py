"""مصفوفة نص الحالة من الحفظ حتى عرض اليومية التفصيلية والتصدير."""
from datetime import date, timedelta
import io
import json

import pytest
from docx import Document

from backend.board_export import _presentation_sections
from backend.day_exports import build_board_bytes


OFFICER = "OFF-002"
SLOT_SECTION = "ضابط عظيم الإدارة"


# كل زوج يغطّي حالة من حالات الطلب مع اختلاف وجود النص. placement و day_mode
# موزّعان عمدًا بدل اختبار مسار واحد فقط: الحالة الخاصة يجب ألا تعتمد على وجود
# خدمة عادية أو هدف/كتلة ثابتة، ولا على كون اليومية مؤكدّة أو مقفولة بعد الحفظ.
MATRIX = [
    {"kind": "custom-new", "status": "حالة جديدة تماما", "note": "نص حالة جديدة",
     "placement": "none", "leave": False, "day_mode": "open"},
    {"kind": "custom-new", "status": "حالة جديدة بلا ملاحظة", "note": "",
     "placement": "basic", "leave": True, "day_mode": "confirmed-before"},
    {"kind": "custom-existing", "status": "حالة محفوظة من القائمة", "note": "",
     "placement": "target", "leave": False, "day_mode": "open"},
    {"kind": "custom-existing", "status": "حالة محفوظة من القائمة", "note": "نص القائمة",
     "placement": "slot", "leave": True, "day_mode": "locked"},
    {"kind": "طارئة", "status": "طارئة", "note": "",
     "placement": "none", "leave": False, "day_mode": "open"},
    {"kind": "طارئة", "status": "طارئة", "note": "طارئة — نقطة + متابعة",
     "placement": "basic", "leave": True, "day_mode": "confirmed-before"},
    {"kind": "مرضي", "status": "مرضي", "note": "",
     "placement": "target", "leave": False, "day_mode": "open"},
    {"kind": "مرضي", "status": "مرضي", "note": "مرضي — راحة",
     "placement": "slot", "leave": True, "day_mode": "locked"},
    {"kind": "غياب", "status": "غياب", "note": "",
     "placement": "none", "leave": False, "day_mode": "open"},
    {"kind": "غياب", "status": "غياب", "note": "غياب + إخطار",
     "placement": "basic", "leave": True, "day_mode": "confirmed-before"},
    {"kind": "مأمورية", "status": "مأمورية", "note": "",
     "placement": "target", "leave": False, "day_mode": "open"},
    {"kind": "مأمورية", "status": "مأمورية", "note": "مأمورية",
     "placement": "slot", "leave": True, "day_mode": "locked"},
    {"kind": "انتداب", "status": "انتداب", "note": "",
     "placement": "none", "leave": False, "day_mode": "open"},
    {"kind": "انتداب", "status": "انتداب", "note": "انتداب + جهة",
     "placement": "basic", "leave": True, "day_mode": "confirmed-before"},
    {"kind": "custom-period", "status": "تكليف ميداني ثابت", "note": "نص ثابت للفترة",
     "placement": "target", "leave": False, "day_mode": "open"},
    {"kind": "custom-period", "status": "تكليف ميداني بلا نص", "note": "",
     "placement": "slot", "leave": True, "day_mode": "locked"},
]


def _all_docx_text(document):
    out = []

    def walk(tables):
        for table in tables:
            for row in table.rows:
                for cell in row.cells:
                    out.extend(paragraph.text for paragraph in cell.paragraphs)
                    walk(cell.tables)

    walk(document.tables)
    return "\n".join(out)


def _outsider(board):
    section = next(section for section in board["sections"] if section["name"] == "الخوارج")
    return next(row for row in section["rows"] if row["id"] == OFFICER)


def _payload(case, day):
    body = {
        # نفس الحقول الأساسية التي يبنيها static/js/duty.js عند submit.
        "taqseera": False, "status": case["status"], "note": case["note"],
        "extra": "", "admin_work": False,
    }
    if case["kind"] == "طارئة":
        body["status_end"] = day
    if case["kind"] in ("مأمورية", "انتداب"):
        body.update(status_end=day, status_title="تأمين مؤتمر",
                    status_details="بمدينة العاشر")
    if case["kind"] == "custom-period":
        body.update(status_period=True, status_end=day)
    if case["status"] == "غياب":
        body["status_start_time"] = ""
    return body


def _add_placement(client, day, placement):
    if placement == "basic":
        response = client.post(f"/api/assignments/{day}", json={
            "name": "خدمة اختبار", "kind": "خارجية", "section": "الخدمات الأساسية",
            "officer_ids": [OFFICER],
        })
        assert response.status_code == 201, response.get_json()
    elif placement == "target":
        response = client.put(f"/api/board/{day}/target/سوميد",
                              json={"officer_ids": [OFFICER]})
        assert response.status_code == 200, response.get_json()
    elif placement == "slot":
        response = client.put(f"/api/board/{day}/slot/{SLOT_SECTION}/صباحية",
                              json={"officer_ids": [OFFICER]})
        assert response.status_code == 200, response.get_json()


def _add_leave(data_file, day):
    data = json.loads(data_file.read_text(encoding="utf-8"))
    data.setdefault("leaves", []).append({
        "id": f"LV-{day[-2:]}", "person_id": OFFICER, "type": "شهرية",
        "start": day, "end": day, "return_date": (date.fromisoformat(day) + timedelta(days=1)).isoformat(),
        "note": "", "source": "اختبار المصفوفة",
    })
    data_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize("case", MATRIX, ids=lambda case: (
    f"{case['kind']}-{case['placement']}-{'note' if case['note'] else 'no-note'}-"
    f"{'leave' if case['leave'] else 'normal'}-{case['day_mode']}"))
def test_status_text_survives_the_detailed_daily_matrix(client, data_file, case):
    index = MATRIX.index(case)
    day = (date(2026, 6, 1) + timedelta(days=index)).isoformat()
    if case["kind"] == "custom-existing" or (
            case["kind"] == "custom-period" and not case["note"]):
        data = json.loads(data_file.read_text(encoding="utf-8"))
        data["custom_officer_statuses"] = [case["status"]]
        data_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    _add_placement(client, day, case["placement"])
    if case["leave"]:
        _add_leave(data_file, day)

    # تأكيد اليومية لا ينسخ حالة الضابط، لكنه يثبت أن snapshot لا يسقطها بعده.
    if case["day_mode"] == "confirmed-before":
        confirmed = client.post(f"/api/board/{day}/confirm", json={})
        assert confirmed.status_code == 201, confirmed.get_json()
    saved = client.put(f"/api/duty/{day}/{OFFICER}", json=_payload(case, day))
    assert saved.status_code == 200, saved.get_json()
    if case["day_mode"] == "locked":
        assert client.post(f"/api/day-status/{day}/close", json={}).status_code == 201

    saved_row = next(row for row in saved.get_json()["rows"] if row["id"] == OFFICER)
    assert saved_row["status"] == case["status"], saved.get_json()["rows"]
    board = client.get(f"/api/board/{day}").get_json()
    outsider = _outsider(board)
    assert outsider["reason"] == case["status"]
    if case["note"]:
        assert case["note"] in outsider["note"]
    presented = _presentation_sections(board["sections"])
    rendered = _outsider({"sections": presented})
    assert rendered["detail"]
    assert case["note"] in rendered["detail"] if case["note"] else True
    if case["kind"] in ("مأمورية", "انتداب") and case["note"]:
        assert rendered["detail"].endswith(case["note"])

    export = client.get(f"/api/board/{day}/export.docx")
    assert export.status_code == 200
    exported_text = _all_docx_text(Document(io.BytesIO(export.data)))
    assert case["status"] in exported_text
    if case["note"]:
        assert case["note"] in exported_text

    generated = _all_docx_text(Document(io.BytesIO(build_board_bytes(day))))
    assert case["status"] in generated
    if case["note"]:
        assert case["note"] in generated


def test_status_text_with_newline_plus_and_max_note_length_is_not_truncated(client):
    day = "2026-07-01"
    note = ("سطر + جهة\n" * 49) + "نهاية"
    response = client.put(f"/api/duty/{day}/{OFFICER}", json={
        "taqseera": False, "status": "حالة طويلة", "note": note,
        "extra": "", "admin_work": False,
    })
    assert response.status_code == 200, response.get_json()
    row = next(row for row in client.get(f"/api/duty/{day}").get_json()["rows"]
               if row["id"] == OFFICER)
    assert row["note"] == note.strip()
    outsider = _outsider(client.get(f"/api/board/{day}").get_json())
    assert outsider["note"] == note
    text = _all_docx_text(Document(io.BytesIO(client.get(
        f"/api/board/{day}/export.docx").data)))
    assert "سطر + جهة" in text and text.count("سطر") >= 40


def test_custom_period_cancel_is_available_and_removes_the_text_from_all_views(client):
    day = "2026-08-01"
    status = "تغطية مؤقتة"
    note = "النص الثابت للإلغاء"
    response = client.put(f"/api/duty/{day}/{OFFICER}", json={
        "taqseera": False, "status": status, "note": note,
        "extra": "", "admin_work": False, "status_period": True,
        "status_end": "2026-08-03",
    })
    assert response.status_code == 200, response.get_json()
    before = client.get(f"/api/board/{day}").get_json()
    assert note in _outsider(before)["note"]
    duty = client.get(f"/api/duty/{day}").get_json()
    assert next(row for row in duty["rows"] if row["id"] == OFFICER)["persistent_status"]["custom"]
    cancelled = client.post(f"/api/duty/{day}/{OFFICER}/cancel-status", json={})
    assert cancelled.status_code == 200, cancelled.get_json()
    after_board = client.get(f"/api/board/{day}").get_json()
    assert note not in json.dumps(after_board, ensure_ascii=False)
    assert next(row for row in client.get(f"/api/duty/{day}").get_json()["rows"]
                if row["id"] == OFFICER)["persistent_status"] is None
    assert note not in _all_docx_text(Document(io.BytesIO(
        client.get(f"/api/board/{day}/export.docx").data)))
    assert note not in _all_docx_text(Document(io.BytesIO(build_board_bytes(day))))
