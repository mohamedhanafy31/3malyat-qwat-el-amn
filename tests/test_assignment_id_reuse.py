"""رقم التكليف (AS-xxxx) ما يتكررش جوّه اليوم ده، حتى لو اتشال آخر صف
وحد جديد اتضاف بعده — وإلا تأكيد اليومية بيقرا الصف الجديد كـ«تعديل» على
الصف المحذوف بدل «حذف + إضافة»، وسطر السجل بيقول كذب.
"""
import json

from backend import store

DAY = "2026-04-10"


def _add(client, name, day=DAY, **over):
    body = {"name": name, "kind": "خارجية", "section": "الخدمات أساسية", **over}
    return client.post(f"/api/assignments/{day}", json=body).get_json()


def test_deleting_the_last_row_then_adding_one_does_not_reuse_its_id(client):
    first = _add(client, "تدخل سريع")
    second = _add(client, "أمن المعسكر")
    assert first["id"] != second["id"]

    client.delete(f"/api/assignments/{DAY}/{second['id']}")
    third = _add(client, "خدمة جديدة")

    assert third["id"] != second["id"], "الرقم المحذوف رجع تاني على خدمة تانية"
    assert third["id"] not in {first["id"], second["id"]}


def test_confirm_sees_a_real_delete_and_create_not_a_disguised_rename(client):
    """السطر في السجل لازم يقول «خدمة اتشالت» + «خدمة جديدة» مش «تعديل»
    على نفس الصف اللي في الحقيقة اتشال وحل محله صف تاني."""
    _add(client, "تدخل سريع")
    second = _add(client, "أمن المعسكر")
    client.post(f"/api/board/{DAY}/confirm", json={})   # أول تأكيد = خط أساس

    client.delete(f"/api/assignments/{DAY}/{second['id']}")
    _add(client, "خدمة جديدة")
    client.post(f"/api/board/{DAY}/confirm", json={})

    entries = client.get(f"/api/changes?entity=assignment").get_json()["entries"]
    actions = {e["action"] for e in entries}
    assert "delete" in actions and "create" in actions
    assert "update" not in actions


def test_emptying_a_day_then_reusing_it_still_starts_a_fresh_counter(client):
    """اليوم اللي يفضى تمامًا ملفه بيختفي — والعدّاد بيبدأ من جديد لما
    اليوم يستخدم تاني، من غير ما ده يأثر على أي يوم فيه تكليفات لسه."""
    row = _add(client, "تدخل سريع")
    client.delete(f"/api/assignments/{DAY}/{row['id']}")
    assert not store.day_path(DAY).exists()

    fresh = _add(client, "خدمة جديدة")
    assert fresh["id"] == "AS-0001"


def test_other_days_are_never_touched_by_another_days_counter(client):
    other = "2026-04-11"
    _add(client, "خدمة يوم 10", day=DAY)
    row = _add(client, "خدمة يوم 11", day=other)
    assert row["id"] == "AS-0001", "كل يوم عدّاده مستقل"


def test_counter_lives_in_the_day_file_not_core(client):
    """لازم يفضل مبدأ «الملف اللي ما اتغيّرش ما بيتلمسش» — عدّاد التكليفات
    جوّه ملف اليوم، مش في core.json."""
    _add(client, "تدخل سريع")
    core = json.loads(store.core_file().read_text(encoding="utf-8"))
    assert "day_assignment_seq" not in core
    blob = json.loads(store.day_path(DAY).read_text(encoding="utf-8"))
    assert blob.get("assignment_seq") == 1
