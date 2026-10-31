"""استيراد يومية الحملة (importer/campaign.py + migrations/022): استخراج، حل، تعارض، idempotency."""
import hashlib
import sys
from importlib import import_module

import pytest
from docx import Document

from backend import store
from importer import campaign

DAY = "2026-07-10"


# ───────────── ملف يومية حملة تخليقي ─────────────

def _write_sheet(root, posts=(), delivery=(), plates=(), day=DAY):
    """جدول واحد بنفس تركيب ملف الأرشيف: عنوان، رأس ارتكازات، الارتكازات، فاصل، رأس توصيل، صفوف، لوحات."""
    year, month, dd = day.split("-")
    folder = root / str(int(month)) / str(int(dd))
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"يومية الحملة عن يوم {int(dd)}-{int(month)}-{year}.docx"
    document = Document()
    table = document.add_table(rows=0, cols=5)

    def merged(text):
        row = table.add_row()
        cell = row.cells[0].merge(row.cells[4])
        cell.text = text

    def plain(values):
        row = table.add_row()
        for cell, value in zip(row.cells, values):
            cell.text = value

    merged("يومية المركبات اليوم الجمعة 10/7/2026م")
    plain(["م", "مركبات الإرتكازات", "السائق", "رقم المركبة", "نوع المركبة"])
    for row in posts:
        plain(row)
    merged("خطــــــــــوط سيــــــــــر توصيــــــــــل  الخدمــــــــــات")
    plain(["م", "الخدمة", "السائق", "رقم المركبة", "نوع المركبة"])
    for row in delivery:
        plain(row)
    for row in plates:
        plain(list(row) + [""] * (5 - len(row)))
    document.save(path)
    return path


POSTS = [["1.", "المديرية", 'مجند " قوات الامن" صبح , ليل', "3279ب13", "مايك ايفكو"]]
DELIVERY = [
    ["", "القنصلية  + تفتيش فيصل ", "سامح فهمي عبدالحميد", "ب15/5217", "لوري"],
    ["", "مأمورية امداد 8ص", "مصطفى عبدالعزيز مصطفى", "4997", "بيك اب"],
    ["", "التدخل السريع", "ناصر مجهول الهوية", "ب12/9999", "بيك اب"],
    ["", "خدمة مش موجودة", "اسم ثنائي", "", ""],
    ["", "كـــ    109  ", "", "", "لوري"],
]
PLATES = [["ب15/5217", "ب12/4997"]]


# ───────────── بيانات النظام عن طريق الـAPI ─────────────

@pytest.fixture
def world(client, tmp_path):
    ids = {}
    for series, number, kind, key in (("ب13", "3279", "ميك", "post"), ("ب15", "5217", "لوري", "lorry"),
                                      ("ب12", "4997", "بيك اب", "pickup")):
        ids[key] = client.post("/api/vehicles", json={
            "plate_series": series, "plate_number": number, "type": kind}).get_json()["id"]
    ids["driver"] = client.post("/api/person", json={
        "type": "personnel", "name": "سامح فهمي عبدالحميد", "code": "771", "phone": "0101",
        "join_date": "2020-01-01", "role": "أمين شرطة", "post": "سائق"}).get_json()["id"]
    ids["conscript"] = client.post("/api/conscripts", json={"name": "مصطفى عبدالعزيز مصطفى"}).get_json()["id"]
    for name in ("تفتيش فيصل", "مأمورية امداد"):
        row = client.post(f"/api/assignments/{DAY}", json={
            "name": name, "kind": "خارجية", "section": "الخدمات الطارئة"}).get_json()
        ids[name] = row["id"]
    assert client.post(f"/api/campaign/{DAY}/posts", json={"name": "المديرية", "number": "1."}).status_code == 200
    assert client.post(f"/api/campaign/{DAY}/daily-rows", json={"name": "التدخل السريع"}).status_code == 200
    ids["root"] = tmp_path / "archive"
    _write_sheet(ids["root"], POSTS, DELIVERY, PLATES)
    return ids


def _load():
    return store.load_data(store.ALL_DAYS)


def _run(data, root, **kwargs):
    return campaign.run_import(data, root, start="2026-07-01", **kwargs)


def _plan(report):
    assert len(report["plans"]) == 1
    return report["plans"][0]


# ───────────── الاستخراج ─────────────

def test_extract_reads_posts_delivery_and_plate_register(tmp_path):
    path = _write_sheet(tmp_path, POSTS, DELIVERY, PLATES)
    sheet = campaign.extract_file(path)
    assert sheet["error"] is None
    assert sheet["posts"] == [{"number": "1.", "name": "المديرية", "driver": 'مجند " قوات الامن" صبح , ليل',
                               "plate": "3279ب13", "type": "مايك ايفكو"}]
    assert [row["name"] for row in sheet["delivery"]] == [
        "القنصلية + تفتيش فيصل", "مأمورية امداد 8ص", "التدخل السريع", "خدمة مش موجودة", "ك 109"]
    assert sheet["delivery"][0] == {"name": "القنصلية + تفتيش فيصل", "driver": "سامح فهمي عبدالحميد",
                                    "plate": "ب15/5217", "type": "لوري"}
    # «ك 109» اسم لوري مش لوحة، وصف اللوحات الحقيقي بس هو اللي يروح للسجل
    assert sheet["plates"] == [["ب15/5217", "ب12/4997"]]


def test_discover_prefers_folder_of_the_day_and_filters_range(tmp_path):
    right = _write_sheet(tmp_path, day="2026-08-05")
    wrong = tmp_path / "9" / "1" / "يومية الحملة عن يوم 5-8-2026.docx"      # نسخة مزاحة في فولدر غلط
    wrong.parent.mkdir(parents=True)
    wrong.write_bytes(right.read_bytes())
    _write_sheet(tmp_path, day="2026-07-01")
    found = campaign.discover_files(tmp_path, "2026-08-01")
    assert found == {"2026-08-05": right}


# ───────────── اللوحات ─────────────

@pytest.mark.parametrize(("text", "series", "number"), [
    ("ب14/9556", "ب14", "9556"), ("ب14 / 9556 ", "ب14", "9556"), ("9556", "", "9556"),
    ("14/9556", "#14", "9556"), ("3279ب13", "ب13", "3279"), ("4222 ب15", "ب15", "4222"),
    ("٩٥٥٦", "", "9556"), ("ب١٤/٩٥٥٦", "ب14", "9556"),
])
def test_parse_plate_normalises_every_archive_spelling(text, series, number):
    plate = campaign.parse_plate(text)
    assert (plate["series"], plate["number"]) == (series, number)


def test_parse_plate_rejects_non_plates():
    assert campaign.parse_plate("") is None
    assert campaign.parse_plate("لوري") is None


def test_vehicle_resolution_is_strict(world):
    index = campaign.FleetIndex(_load())
    assert index.resolve("ب15/5217")["vehicle_id"] == world["lorry"]
    assert index.resolve("5217")["vehicle_id"] == world["lorry"]          # رقم فقط وفريد
    assert index.resolve("15/5217")["vehicle_id"] == world["lorry"]       # رقم السلسلة بدون الحرف
    assert index.resolve("3279ب13")["vehicle_id"] == world["post"]        # صيغة الارتكازات
    assert index.resolve("ب12/5217")["status"] == "series-mismatch"       # مانخمّنش
    assert index.resolve("ب12/9999")["status"] == "unregistered"
    assert index.resolve("لوري")["status"] == "none"


# ───────────── السائقين ─────────────

def test_driver_resolution_links_only_when_sure(world):
    drivers = campaign.DriverIndex(_load(), DAY)
    assert drivers.resolve("سامح فهمي عبدالحميد")["value"] == {"kind": "personnel", "id": world["driver"]}
    assert drivers.resolve("ا.ش/ سامح فهمي")["value"] == {"kind": "personnel", "id": world["driver"]}   # رتبة + اسم مختصر
    assert drivers.resolve("مصطفى عبدالعزيز مصطفى")["value"] == {"kind": "conscript", "id": world["conscript"]}
    stranger = drivers.resolve("ناصر مجهول الهوية")
    assert stranger["status"] == "text" and stranger["value"]["name"] == "ناصر مجهول الهوية"
    assert drivers.resolve("سامح")["status"] == "text"                    # كلمة واحدة مش كفاية
    assert drivers.resolve("ـــــ")["status"] == "none"


# ───────────── الخطة والتطبيق ─────────────

def test_import_fills_empty_day_and_reports_unresolved(world):
    data = _load()
    plan = _plan(_run(data, world["root"]))
    sheet = data["day_campaign"][DAY]

    lorry = sheet["lorries"]["LOR-2"]
    assert lorry["vehicle_id"] == world["lorry"]
    assert lorry["driver"] == {"kind": "personnel", "id": world["driver"]}
    assert lorry["attached"] == [{"assignment_id": world["تفتيش فيصل"]}]

    service = sheet["services"][world["مأمورية امداد"]]
    assert service["vehicles"][0]["vehicle_id"] == world["pickup"]
    assert service["driver"] == {"kind": "conscript", "id": world["conscript"]}

    daily = next(iter(sheet["daily"].values()))
    assert daily["driver"] == {"kind": "text", "id": "", "name": "ناصر مجهول الهوية"}
    assert "vehicle_id" not in daily                                      # اللوحة مش في السجل: ما اتكتبش حاجة

    post = sheet["posts"][next(iter(sheet["posts"]))]
    assert post["vehicle_id"] == world["post"] and post["plate_text"] == "3279ب13"
    assert sheet["plates"] == {"rows": [["ب15/5217", "ب12/4997"]]}

    kinds = {(u["kind"], u["row"]) for u in plan.unresolved}
    assert ("vehicle", "التدخل السريع") in kinds                          # لوحة غير مسجلة
    assert ("service", "خدمة مش موجودة") in kinds                         # مفيش تكليف بالاسم ده
    assert plan.stats["plates_resolved"] < plan.stats["plates"]
    assert plan.conflicts == []


def test_daily_row_is_linked_to_its_basic_service_by_name(world):
    data = _load()
    basics = {"from": "2026-01-01", "items": [{"id": "AFB-77", "name": "ارتكاز الاسعاف"}]}
    data.setdefault("reference_lists", {})["afraad_basic"] = [basics]
    data["reference_lists"]["campaign_daily"] = [{"from": "2026-01-01", "items": [
        {"id": "CD-005", "name": "ارتكاز الاسعاف"}]}]
    root = world["root"] / "other"
    _write_sheet(root, [], [["", "ارتكاز الاسعاف", "يحيى غريب عطيه", "4997", "مايك"]])
    campaign.run_import(data, root, start="2026-07-01")
    entry = data["day_campaign"][DAY]["daily"]["CD-005"]
    assert entry["basic_entry_id"] == "AFB-77" and entry["vehicle_id"] == world["pickup"]


def test_conflicting_fields_are_skipped_but_empty_ones_still_filled(world):
    data = _load()
    other = world["post"]
    data["day_campaign"] = {DAY: {"lorries": {"LOR-2": {"vehicle_id": other}}}}
    plan = _plan(_run(data, world["root"]))
    lorry = data["day_campaign"][DAY]["lorries"]["LOR-2"]
    assert lorry["vehicle_id"] == other                                   # ما اتلمسش
    assert lorry["driver"]["id"] == world["driver"]                       # الفاضي اتملى
    assert [(c.path, c.current, c.value) for c in plan.conflicts] == [
        (("lorries", "LOR-2", "vehicle_id"), other, world["lorry"])]


def test_equivalent_stored_value_is_not_a_conflict(world):
    """اسم السائق النصي المختصر/الأطول لنفس الشخص مش تعارض."""
    data = _load()
    data["day_campaign"] = {DAY: {"lorries": {"LOR-2": {
        "driver": {"kind": "text", "name": "سامح فهمي"}}}}}
    plan = _plan(_run(data, world["root"]))
    assert not [c for c in plan.conflicts if c.path[-1] == "driver"]
    assert data["day_campaign"][DAY]["lorries"]["LOR-2"]["driver"] == {"kind": "text", "name": "سامح فهمي"}


def test_inherited_values_are_replaced_and_flagged(world):
    data = _load()
    data["day_campaign"] = {"2026-07-09": {"lorries": {"LOR-2": {"vehicle_id": world["post"]}}}}
    plan = _plan(_run(data, world["root"]))
    op = next(o for o in plan.added if o.path == ("lorries", "LOR-2", "vehicle_id"))
    assert op.overrides_inherited and data["day_campaign"][DAY]["lorries"]["LOR-2"]["vehicle_id"] == world["lorry"]


def test_second_run_adds_nothing(world):
    data = _load()
    _run(data, world["root"])
    snapshot = repr(data["day_campaign"])
    again = _plan(_run(data, world["root"]))
    assert again.added == [] and again.conflicts == [] and again.same > 0
    assert repr(data["day_campaign"]) == snapshot


# ───────────── الهجرة 022: dry-run / --write / idempotency ─────────────

def _tree_digest():
    digest = hashlib.sha1()
    for path in sorted(store.DATA_DIR.rglob("*.json")):
        digest.update(path.name.encode() + path.read_bytes())
    return digest.hexdigest()


def test_migration_dry_run_writes_nothing_then_write_is_idempotent(world, monkeypatch, capsys, tmp_path):
    migration = import_module("migrations.022_import_campaign")
    report_path = tmp_path / "preview.md"
    base = ["022", "--archive-root", str(world["root"]), "--from", "2026-07-01"]
    before = _tree_digest()

    monkeypatch.setattr(sys, "argv", base + ["--report", str(report_path)])
    migration.run(from_schema=6, to_schema=6, migrate=migration.migrate, title="t")
    assert _tree_digest() == before                                       # dry-run ما كتبش حاجة
    assert "عرض بس" in capsys.readouterr().out
    text = report_path.read_text(encoding="utf-8")
    assert DAY in text and "غير محلول" in text and "LOR-2" in text

    monkeypatch.setattr(sys, "argv", base + ["--write"])
    migration.run(from_schema=6, to_schema=6, migrate=migration.migrate, title="t")
    written = _tree_digest()
    assert written != before
    data = _load()
    assert data["day_campaign"][DAY]["lorries"]["LOR-2"]["vehicle_id"] == world["lorry"]
    assert any(c["entity"] == "import" and c["entity_id"] == "campaign-022" for c in data["change_log"])

    capsys.readouterr()
    migration.run(from_schema=6, to_schema=6, migrate=migration.migrate, title="t")   # --write تاني
    assert _tree_digest() == written                                      # مفيش تغيير ولا إعادة كتابة
    assert "متملية بالفعل" in capsys.readouterr().out
