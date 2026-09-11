"""شبكة الأمان في طبقة التخزين — النسخ الاحتياطي وفحص بنية الملف."""
import json

import pytest

from backend import store


def test_write_snapshots_previous_version(client, data_file):
    """كل كتابة بتحتفظ بالنسخة اللي قبلها — الكتابة الذرية بتحمي من ملف
    مقطوع، مش من تعديل غلط. ده اللي بيخلي الرجوع ممكن.

    النسخ بقت مضغوطة (.json.gz) لتوفير المساحة؛ المحتوى نفسه ما اتغيّرش.
    """
    before = json.loads(data_file.read_text(encoding="utf-8"))
    client.post("/api/services", json={"name": "خدمة جديدة", "kind": "خارجية"})

    backups = store._backup_files()
    assert len(backups) == 1, "لازم تتعمل نسخة واحدة قبل الكتابة"
    assert backups[0].name.endswith(".json.gz"), "النسخ الجديدة مضغوطة"
    assert store.read_backup(backups[0]) == before, "النسخة لازم تكون الحالة السابقة بالظبط"


def test_backup_is_much_smaller_than_the_live_file(client, data_file):
    """الضغط هو سبب التغيير — لازم يكون فرق حقيقي مش شكلي."""
    client.post("/api/services", json={"name": "خدمة", "kind": "خارجية"})
    backup = store._backup_files()[0]
    assert backup.stat().st_size < data_file.stat().st_size


def test_live_data_file_is_never_compressed(client, data_file):
    """الملف الشغّال بيفضل JSON عادي مقروء — الضغط على النسخ بس."""
    client.post("/api/services", json={"name": "خدمة", "kind": "خارجية"})
    assert data_file.read_bytes()[:2] != b"\x1f\x8b"
    json.loads(data_file.read_text(encoding="utf-8"))      # لازم يفضل يتقري كنص


def test_backups_are_capped(client, monkeypatch):
    monkeypatch.setattr(store, "BACKUP_KEEP", 3)
    for i in range(6):
        client.post("/api/services", json={"name": f"خدمة-{i}", "kind": "خارجية"})
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
    client.post("/api/services", json={"name": "خدمة", "kind": "خارجية"})
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
    client.post("/api/services", json={"name": "قبل", "kind": "خارجية"})
    marker = store._backup_files()[-1].name
    n_before = len(store.read_backup(store.backup_dir() / marker)["services"])

    client.post("/api/services", json={"name": "بعد", "kind": "خارجية"})
    assert len(json.loads(data_file.read_text(encoding="utf-8"))["services"]) > n_before

    store.restore_backup(marker)
    assert len(json.loads(data_file.read_text(encoding="utf-8"))["services"]) == n_before


def test_write_stamps_schema_version(client, data_file):
    client.post("/api/services", json={"name": "خدمة", "kind": "خارجية"})
    assert json.loads(data_file.read_text(encoding="utf-8"))["schema"] == store.SCHEMA_VERSION


def test_older_schema_is_refused_loudly(data_file):
    """ملف ببنية قديمة يتقفل بصوت عالي — قراءته بالكود الجديد بتطلع
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

    r = client.get("/api/bootstrap/catalog")
    assert r.status_code == 503
    assert "schema" in r.get_json()["error"] or "بنية" in r.get_json()["error"]
