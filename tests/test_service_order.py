from io import BytesIO

import pytest
from docx import Document

from backend import daily_files, service_order
from backend.export_fit import PageFitError
from backend.regularity import build as build_regularity
from test_regularity import DAY, assignment, data_for


def _texts(buffer):
    return [p.text for p in Document(BytesIO(buffer.getvalue())).paragraphs if p.text.strip()]


def _board(rows=(), special=()):
    sections = [{"name": "الخدمات الطارئة", "type": "services", "rows": list(rows)}]
    sections += [{"name": name, "type": "services", "rows": list(block)} for name, block in special]
    return {"date": DAY, "sections": sections}


def _row(name, time="", party="", **extra):
    return {"id": name, "name": name, "label": name, "time": time, "party": party,
            "officers": [], "personnel": [], "conscripts": [], **extra}


# ---------- مشرف القول المكبر في يومية الانتظام ----------

@pytest.mark.parametrize(("name", "shift", "text"), [
    ("القول المكبر", "ليلية", "مشرف القول المكبر فترة ليلية من 8م حتي 8ص"),
    ("قول مكبر", "صباحية", "مشرف القول المكبر فترة صباحية من 8ص حتي 8م"),
])
def test_our_big_column_officer_gets_from_to_hours(name, shift, text):
    data = data_for([assignment(name, section="الخدمات أساسية", id="AS-B", shift=shift,
                                officer_ids=["OFF-4"], personnel_ids=[])])
    rows = build_regularity(data, DAY)["officer_rows"]
    assert any(row["id"] == "OFF-4" and row["service"] == text for row in rows)


def test_typed_big_column_supervisor_our_officer_vs_outside():
    data = data_for([])
    ours = build_regularity(data, DAY, {"big_column_supervisors": {
        "pm": {"rank": "مقدم", "name": "ضابط خدمة", "phone": ""}}})["officer_rows"]
    assert any(row["service"] == "مشرف القول المكبر فترة ليلية من 8م حتي 8ص" for row in ours)
    outside = build_regularity(data, DAY, {"big_column_supervisors": {
        "pm": {"rank": "عقيد", "name": "ضابط من المديرية", "phone": ""}}})["officer_rows"]
    assert any(row["service"] == 'مشرف القول المكبر فترة ليلية "8 م الي 8 ص"' for row in outside)


# ---------- محتوى أمر الخدمة ----------

def test_service_order_lines_follow_archive_shape():
    data = data_for([assignment("القول المكبر", section="الخدمات أساسية", id="AS-B", shift="ليلية",
                                officer_ids=["OFF-4"], personnel_ids=[])])
    board = _board(
        [_row("حملة امن وطنى 12ظ", "12ظ", "الأمن الوطني", personnel_command_required=True,
              conscripts=[{"count": 2, "class": "مج"}]),
         _row("ترحيلة الجيزة", "06:00", "السويس", personnel_command_required=True,
              conscripts=[{"count": 1, "class": "مج"}]),
         _row('طلبة امداد 7ص "المديرية"', "07:00", "المديرية", conscripts=[{"count": 3, "class": "طلبة"}]),
         _row("مأمورية امداد", "08:00", officers=[{"role": "رائد", "name": "محمد ميهوب"}],
              conscripts=[{"count": 3, "class": "طلبة"}]),
         _row("مامورية علاقات", "05:00", "المديرية", conscripts=[{"count": 6, "class": "مج"}])],
        [("مباراة المصري", [
            _row("ميك المرور", "14:00", "استاد السويس", officers=[{"role": "م.اول", "name": "ماركو ماجد"}],
                 conscripts=[{"count": 1, "class": "ميك"}]),
            _row("مدرجات الدرجة الاولي", "14:00", "استاد السويس",
                 officers=[{"role": "نقيب", "name": "طارق فاروق"}], conscripts=[{"count": 1, "class": "رياضي"}]),
            _row("ارتكاز الخضر", "19:00", "استاد السويس", conscripts=[{"count": 1, "class": "وحدة"}])])])
    board["sections"].append({"name": "تفتيشات", "type": "services", "rows": [
        _row("تفتيش فيصل", "10ص", "فيصل", conscript_count=10, weapon="دونك")]})
    board["sections"].append({"name": "خدمات سجن قوات الأمن", "type": "services", "rows": [
        _row("تأمين السجن العسكري", shift="صباحية", officers=[{"role": "رائد", "name": "محمد بحر"}])]})
    notes = ["عدد 5 مجند حفظ نظام لتأمين محكمه والباب الرئيسي الساعه 8ص بالمديرية",
             "عدد (2) مجند قول كورنيش مسلح خرطوش من 6م : الانصراف", "ملاحظة إضافية للمشغل"]
    payload = service_order.build(board, {"notes": notes}, data, DAY)
    lines = payload["lines"]
    assert payload["title"] == "امر خدمة يوم الثلاثاء الموافق 20/10/2026م"
    assert lines[0] == f"العقيد / مدير سمير : {service_order.SUPERVISION}"
    assert lines[1].startswith("مشرف القول المكبر : ص --- ........")
    assert "ل --- مقدم / ضابط خدمة" in lines[1]
    assert lines[2].startswith("التدخل السريع : ص --- ")
    assert "قول كورنيش : عدد ( 2 ) مجند مسلح خرطوش 6 م : الانصراف ." in lines
    assert "المحكمة : (5) مجند حفظ نظام 8ص ." in lines
    assert "ملاحظة إضافية للمشغل" in lines
    assert not any("المجمع الطبي" in line for line in lines)
    assert 'تفتيش فيصل : عدد 10 مجند دونك 10ص "فيصل"' in lines
    # حملة الأمن الوطني مابتتكتبش في الأمر
    assert not any("وطن" in line for line in lines)
    assert 'ترحيلة الجيزة : مج قتالية برئاستها 6ص "السويس"' in lines
    assert 'طلبة امداد 7ص "المديرية" : عدد 3 مجند طلبة' in lines   # المكان مش متكرر
    assert "مأمورية امداد : برئاسة رائد/ محمد ميهوب وبصحبته عدد 3 مجند طلبة 8ص" in lines
    assert 'مامورية علاقات : عدد 6 مجند 5ص "المديرية"' in lines
    title = lines.index('مباراة المصري "استاد السويس" الساعة 2م')
    assert lines[title + 1:title + 4] == [
        "ميك المرور : مايك فض برئاسة م.اول/ ماركو ماجد",
        "مدرجات الدرجة الاولي : وحدة حفظ نظام رياضي برئاسة نقيب/ طارق فاروق",
        "ارتكاز الخضر : وحدة فض برئاستها 7م"]
    prison = lines.index(service_order.PRISON_TITLE)
    assert lines[prison + 1] == "رائد/ محمد بحر : تأمين السجن العسكري فترة صباحية"
    # ضابط القول المكبر مايتكررش كبند لوحده
    assert sum("ضابط خدمة" in line for line in lines) == 1


def test_service_order_docx_is_one_page_and_shrinks():
    short = service_order.build_docx({"title": "امر خدمة", "lines": ["بند"] * 5, "signatories": {}})
    assert service_order.LAST_FIT["size_pt"] == 12
    texts = _texts(short)
    assert texts[0] == "امر خدمة" and texts.count("بند") == 5
    service_order.build_docx({"title": "t", "lines": ["ترحيلة نيابة عسكرية 8ص : فرد + مج"] * 40,
                              "signatories": {}})
    assert service_order.LAST_FIT["size_pt"] < 12
    with pytest.raises(PageFitError):
        service_order.build_docx({"title": "t", "lines": ["بند طويل جدا " * 20] * 80, "signatories": {}})


# ---------- إنشاء الملف مع ملفات اليوم من غير ما يمسح تعديلات المشغّل ----------

@pytest.fixture
def archive(monkeypatch, tmp_path):
    root = tmp_path / "archive"
    monkeypatch.setenv("DAILY_FILES_ROOT", str(root))
    from backend import day_exports
    version = {"n": 1}
    monkeypatch.setattr(day_exports, "build_service_order_bytes",
                        lambda day: f"order-{version['n']}".encode())
    return root, version


def test_service_order_created_updated_until_edited(archive):
    _root, version = archive
    day = "2026-11-03"
    daily_files.write_day_files(day, ["service_order"])
    path = daily_files.day_folder(day) / "أمر خدمة يوم 3-11-2026.docx"
    assert path.read_bytes() == b"order-1"
    version["n"] = 2
    daily_files.write_day_files(day, ["service_order"])
    assert path.read_bytes() == b"order-2"           # لسه بتاع السيستم → يتحدّث
    path.write_bytes(b"edited by operator")
    version["n"] = 3
    result = daily_files.write_day_files(day, ["service_order"])
    assert path.read_bytes() == b"edited by operator"  # اتعدّل بالإيد → مايتلمسش
    assert result.files["service_order"]["kept"] == "edited"


def test_operator_file_with_same_name_is_never_replaced(archive):
    day = "2026-11-04"
    folder = daily_files.day_folder(day)
    folder.mkdir(parents=True)
    (folder / "أمر خدمة يوم 4-11-2026.docx").write_bytes(b"mine")
    daily_files.write_day_files(day, ["service_order"])
    assert (folder / "أمر خدمة يوم 4-11-2026.docx").read_bytes() == b"mine"


def test_yesterdays_order_is_not_cloned_into_today(archive):
    root, _version = archive
    source = root / "2026" / "11" / "3"
    source.mkdir(parents=True)
    (source / "أمر خدمة يوم 3-11-2026.docx").write_bytes(b"old")
    (source / "ارقام الافراد.docx").write_bytes(b"keep")
    folder, cloned, _ = daily_files.ensure_day_folder("2026-11-04")
    assert cloned == source
    assert (folder / "ارقام الافراد.docx").exists()
    assert not (folder / "أمر خدمة يوم 3-11-2026.docx").exists()


def test_refresh_one_accepts_service_order(client, archive):
    response = client.post("/api/day-files/2026-11-05/service_order", json={},
                           headers={"X-Requested-With": "fetch"})
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["result"]["path"].endswith("أمر خدمة يوم 5-11-2026.docx")
