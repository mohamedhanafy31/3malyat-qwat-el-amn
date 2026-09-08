"""شبكة الأمان في طبقة التخزين — النسخ الاحتياطي وفحص بنية الملف."""
import json

import pytest

from backend import store


def test_write_snapshots_previous_version(client, data_file):
    """كل كتابة بتحتفظ بالنسخة اللي قبلها — الكتابة الذرية بتحمي من ملف
    مقطوع، مش من تعديل غلط. ده اللي بيخلي الرجوع ممكن."""
    before = json.loads(data_file.read_text(encoding="utf-8"))
    client.post("/api/services", json={"name": "خدمة جديدة", "kind": "خارجية"})

    backups = sorted(store.backup_dir().glob("data-*.json"))
    assert len(backups) == 1, "لازم تتعمل نسخة واحدة قبل الكتابة"
    saved = json.loads(backups[0].read_text(encoding="utf-8"))
    assert saved == before, "النسخة لازم تكون الحالة السابقة بالظبط"


def test_backups_are_capped(client, monkeypatch):
    monkeypatch.setattr(store, "BACKUP_KEEP", 3)
    for i in range(6):
        client.post("/api/services", json={"name": f"خدمة-{i}", "kind": "خارجية"})
    assert len(list(store.backup_dir().glob("data-*.json"))) == 3


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
