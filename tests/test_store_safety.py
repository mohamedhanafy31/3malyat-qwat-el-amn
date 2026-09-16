"""شبكة الأمان في طبقة التخزين — النسخ الاحتياطي وفحص بنية البيانات.

البيانات بقت مجلد (`data/core.json` + `data/days/…`) مش ملف واحد.
`data_file` في conftest بيدّي واجهة قراءة/كتابة على **كل** البيانات
مجمّعة، عشان الاختبار يفضل يتكلم عن البيانات مش عن تقسيمها.
"""
import json

import pytest

from backend import store


def test_write_snapshots_previous_version(client, data_file):
    """النسخة بتتاخد قبل الكتابة — الكتابة الذرية بتحمي من ملف مقطوع،
    مش من تعديل غلط. ده اللي بيخلي الرجوع ممكن.

    النسخة ملف واحد مضغوط فيه كل حاجة مجمّعة، عشان الاستعادة تفضل «ارجع
    للحظة دي» مش «ركّب مية ملف».
    """
    before = json.loads(data_file.read_text(encoding="utf-8"))
    client.post("/api/assignments/2026-04-10", json={"name": "خدمة جديدة", "kind": "خارجية"})

    backups = store._backup_files()
    assert len(backups) == 1, "لازم تتعمل نسخة واحدة قبل الكتابة"
    assert backups[0].name.endswith(".json.gz"), "النسخ مضغوطة"
    assert store.read_backup(backups[0]) == before, "النسخة لازم تكون الحالة السابقة بالظبط"


def test_backup_is_much_smaller_than_the_live_data(client, data_file):
    """الضغط هو سبب التغيير — لازم يكون فرق حقيقي مش شكلي."""
    client.post("/api/assignments/2026-04-10", json={"name": "خدمة", "kind": "خارجية"})
    assert store._backup_files()[0].stat().st_size < data_file.size()


def test_live_data_is_never_compressed(client, data_file):
    """الملفات الشغّالة بتفضل JSON عادي مقروء — الضغط على النسخ بس."""
    client.post("/api/assignments/2026-04-10", json={"name": "خدمة", "kind": "خارجية"})
    for path in store.DATA_DIR.rglob("*.json"):
        assert path.read_bytes()[:2] != b"\x1f\x8b"
        json.loads(path.read_text(encoding="utf-8"))      # لازم يفضل يتقري كنص


def test_backups_are_capped(client, monkeypatch):
    monkeypatch.setattr(store, "BACKUP_KEEP", 3)
    monkeypatch.setattr(store, "BACKUP_MIN_GAP", 0)     # نسخة لكل كتابة هنا
    for i in range(6):
        client.post(f"/api/assignments/2026-04-{i+1:02d}",
                    json={"name": f"خدمة-{i}", "kind": "خارجية"})
    assert len(store._backup_files()) == 3


def test_day_only_edits_do_not_snapshot_on_every_write(client, data_file):
    """أخد نسخة مضغوطة من كل البيانات مع كل تعديل خانة كان نص مشكلة
    الأداء. تعديل اليوميات بياخد نسخة كل `BACKUP_MIN_GAP` ثانية، واللي
    بينهم موثّق في `change_log`."""
    for i in range(5):
        client.post("/api/assignments/2026-04-10",
                    json={"name": f"خدمة-{i}", "kind": "خارجية"})
    assert len(store._backup_files()) == 1, "خمس تعديلات يوم = نسخة واحدة"


def test_changing_the_force_always_snapshots(client, data_file):
    """القوة والراحات مالهاش مصدر تاني تترجع منه، فأي تغيير فيها بياخد
    نسخة فورًا مهما كان وقت آخر واحدة."""
    for i in range(3):
        client.post("/api/leaves", json={"person_id": "OFF-002", "type": "أسبوعية",
                                          "start": f"2026-02-0{i+1}", "end": f"2026-02-0{i+1}"})
    assert len(store._backup_files()) == 3


def test_legacy_uncompressed_backups_still_readable(client, data_file):
    """النسخ القديمة (و نسخ ما-قبل-الهجرة اللي migrations/ بتكتبها) لازم
    تفضل ظاهرة وقابلة للاستعادة بعد التحويل للضغط."""
    store.backup_dir().mkdir(exist_ok=True)
    legacy = store.backup_dir() / "data-20200101-000000-000000.json"
    legacy.write_text(data_file.read_text(encoding="utf-8"), encoding="utf-8")

    names = [r["name"] for r in store.list_backups()]
    assert legacy.name in names
    assert next(r for r in store.list_backups() if r["name"] == legacy.name)["ok"]


def test_corrupt_backup_is_flagged_and_never_restored(client, data_file):
    """نسخة متقطعة أو تالفة لازم تترفض قبل ما تلمس البيانات الشغّالة."""
    client.post("/api/assignments/2026-04-10", json={"name": "خدمة", "kind": "خارجية"})
    good = store._backup_files()[0]
    truncated = store.backup_dir() / "data-20200102-000000-000000.json.gz"
    truncated.write_bytes(good.read_bytes()[: good.stat().st_size // 2])

    row = next(r for r in store.list_backups() if r["name"] == truncated.name)
    assert row["ok"] is False

    before = data_file.read_bytes()
    with pytest.raises(store.DataUnreadable):
        store.restore_backup(truncated.name)
    assert data_file.read_bytes() == before, "الاستعادة الفاشلة ما تلمسش البيانات"


def test_restore_round_trip(client, data_file):
    """استعادة نسخة بترجّع الحالة اللي كانت وقتها بالظبط."""
    client.post("/api/assignments/2026-04-10", json={"name": "قبل", "kind": "خارجية"})
    marker = store._backup_files()[-1].name
    n_before = len(store.read_backup(store.backup_dir() / marker).get("day_assignments", {})
                   .get("2026-04-10", []))

    client.post("/api/assignments/2026-04-10", json={"name": "بعد", "kind": "خارجية"})
    assert len(json.loads(data_file.read_text(encoding="utf-8"))
               ["day_assignments"]["2026-04-10"]) > n_before

    store.restore_backup(marker)
    after = json.loads(data_file.read_text(encoding="utf-8")).get("day_assignments", {})
    assert len(after.get("2026-04-10", [])) == n_before


def test_restore_removes_days_that_did_not_exist_yet(client, data_file):
    """الاستعادة «ارجع للحظة دي» مش «ادمج فوق اللي موجود» — يوم اتعمل بعد
    النسخة لازم يختفي، وإلا الرجوع بيسيب نص التعديل مكانه."""
    client.post("/api/assignments/2026-04-10", json={"name": "قديم", "kind": "خارجية"})
    marker = store._backup_files()[-1].name

    client.post("/api/assignments/2026-05-20", json={"name": "يوم جديد", "kind": "خارجية"})
    assert store.day_path("2026-05-20").exists()

    store.restore_backup(marker)
    assert not store.day_path("2026-05-20").exists()


def test_write_stamps_schema_version(client, data_file):
    client.post("/api/assignments/2026-04-10", json={"name": "خدمة", "kind": "خارجية"})
    assert json.loads(data_file.read_text(encoding="utf-8"))["schema"] == store.SCHEMA_VERSION


def test_older_schema_is_refused_loudly(data_file):
    """بيانات ببنية قديمة تتقفل بصوت عالي — قراءتها بالكود الجديد بتطلع
    أرقام غلط في اليوميات، وده أسوأ من رسالة خطأ."""
    data = json.loads(data_file.read_text(encoding="utf-8"))
    data["schema"] = store.SCHEMA_VERSION - 1
    data_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(store.SchemaMismatch, match="migrations/"):
        store.load_data()


def test_newer_schema_is_refused_too(data_file):
    data = json.loads(data_file.read_text(encoding="utf-8"))
    data["schema"] = store.SCHEMA_VERSION + 1
    data_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(store.SchemaMismatch):
        store.load_data()


def test_schema_mismatch_returns_503_not_500(client, data_file):
    data = json.loads(data_file.read_text(encoding="utf-8"))
    data["schema"] = store.SCHEMA_VERSION + 1
    data_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    r = client.get("/api/bootstrap/board")
    assert r.status_code == 503
    assert "schema" in r.get_json()["error"] or "بنية" in r.get_json()["error"]


def test_a_corrupt_day_file_stops_everything_instead_of_reading_empty(client, data_file):
    """ملف يوم مقطوع من قطع كهربا لازم يوقف الدنيا بصوت عالي. الرجوع
    بيوم فاضي كان هيخلي اللوحة تبان فاضية، وأول حفظ بعدها يكتب الفاضي
    ده فوق البيانات الحقيقية."""
    client.post("/api/assignments/2026-04-10", json={"name": "خدمة", "kind": "خارجية"})
    store.day_path("2026-04-10").write_text('{"assignments": [', encoding="utf-8")
    store._cache.clear()

    with pytest.raises(store.DataUnreadable, match="2026-04-10"):
        store.load_data()
