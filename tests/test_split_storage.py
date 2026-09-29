"""التخزين المقسّم — ملف لكل يوم، والكتابة للي اتغيّر بس.

السبب اللي البند ده اتعمل عشانه: تعديل خانة واحدة في اليومية كان بيعيد
كتابة ملف البيانات كله (أكتر من 2 ميجا) وياخد منه نسخة مضغوطة كاملة.
الاختبارات هنا بتقفل السلوك ده: **الملف اللي ما اتغيّرش ما بيتلمسش**.
"""
import json

from backend import store

DAY = "2026-04-10"
OTHER = "2026-04-11"


def _mtimes():
    return {p: p.stat().st_mtime_ns for p in store.DATA_DIR.rglob("*.json")}


def _add(client, day=DAY, name="خدمة"):
    return client.post(f"/api/assignments/{day}", json={"name": name, "kind": "خارجية"})


# ---------- الشكل على القرص ----------

def test_each_day_lands_in_its_own_file(client):
    _add(client, DAY)
    _add(client, OTHER)

    assert store.day_path(DAY).exists()
    assert store.day_path(OTHER).exists()
    blob = json.loads(store.day_path(DAY).read_text(encoding="utf-8"))
    assert [a["name"] for a in blob["assignments"]] == ["خدمة"]


def test_day_files_are_nested_by_year_and_month(client):
    """مجلد واحد فيه آلاف الملفات تقيل في متصفح الملفات على ويندوز."""
    _add(client, DAY)
    path = store.day_path(DAY)
    assert path.parent.name == "04" and path.parent.parent.name == "2026"


def test_core_holds_the_force_and_never_the_days(client):
    _add(client, DAY)
    core = json.loads(store.core_file().read_text(encoding="utf-8"))
    assert "officers" in core and "leaves" in core
    for key in store.DAY_SECTIONS:
        assert key not in core, f"«{key}» مفروض يتوزّع على ملفات الأيام"


def test_everything_in_one_day_file_lives_together(client):
    """تكليفات اليوم وحالات ضباطه وتأكيده وقفله ملف واحد — التعديل عليهم
    بيحصل مع بعض في نفس الجلسة."""
    _add(client, DAY)
    client.put(f"/api/duty/{DAY}/OFF-001", json={"taqseera": True})
    client.post(f"/api/board/{DAY}/confirm", json={})
    client.post(f"/api/day-status/{DAY}/close", json={})

    blob = json.loads(store.day_path(DAY).read_text(encoding="utf-8"))
    assert set(blob) == {"assignments", "officer_states", "confirm", "status",
                          "assignment_seq"}


# ---------- الكتابة للي اتغيّر بس ----------

def test_editing_one_day_leaves_every_other_file_untouched(client):
    """ده البند كله: تعديل خانة بيكتب ملف يومها وبس."""
    _add(client, DAY)
    _add(client, OTHER)
    before = _mtimes()

    _add(client, DAY, name="خدمة تانية")
    after = _mtimes()

    changed = [p.name for p in after if after[p] != before.get(p)]
    assert changed == [f"{DAY}.json"], f"اتكتب كمان: {changed}"


def test_a_request_that_changes_nothing_writes_nothing(client):
    """قراءة أو تعديل بنفس القيم مالوش سبب يلمس القرص."""
    _add(client, DAY)
    before = _mtimes()

    client.get(f"/api/board/{DAY}")
    client.get("/api/bootstrap/officers")
    assert _mtimes() == before

    row = json.loads(store.day_path(DAY).read_text(encoding="utf-8"))["assignments"][0]
    client.patch(f"/api/assignments/{DAY}/{row['id']}", json={"name": row["name"]})
    assert _mtimes() == before, "تعديل بنفس القيمة مالوش أثر على القرص"


def test_changing_a_person_writes_core_not_the_days(client):
    _add(client, DAY)
    before = _mtimes()

    client.patch("/api/person/OFF-001", json={"post": "منصب جديد"})
    changed = [p.name for p in _mtimes() if _mtimes()[p] != before.get(p)]
    assert changed == [store.CORE_NAME]


def test_emptying_a_day_removes_its_file(client):
    """اليوم اللي اتفضّى لازم ملفه يختفي، وإلا بيرجع لوحده في أول قراءة."""
    r = _add(client, DAY)
    client.delete(f"/api/assignments/{DAY}/{r.get_json()['id']}")
    assert not store.day_path(DAY).exists()
    assert DAY not in store.load_data()["day_assignments"]


# ---------- ذهاب وعودة ----------

def test_split_and_merge_are_exact_inverses(client):
    """أي فقد أو تحريف هنا معناه بيانات ضايعة — ده الضمان الأساسي."""
    _add(client, DAY)
    client.put(f"/api/duty/{OTHER}/OFF-001", json={"note": "عمل بالإدارة"})

    data = store.load_data()
    data.pop("_fp", None)
    assert store.merge(*store.split(data)) == data


def test_assemble_matches_what_the_app_reads(client):
    _add(client, DAY)
    live = store.load_data()
    live.pop("_fp", None)
    assembled = store.assemble()
    for key in store.DAY_SECTIONS:
        assert assembled.get(key, {}) == live[key]


def test_a_day_with_only_an_officer_state_still_gets_a_file(client):
    """اليوم ممكن يبقى فيه حالة ضابط من غير أي تكليف — ده يوم حقيقي."""
    client.put(f"/api/duty/{DAY}/OFF-001", json={"status": "غياب"})
    assert store.day_path(DAY).exists()
    blob = json.loads(store.day_path(DAY).read_text(encoding="utf-8"))
    assert set(blob) == {"officer_states"}
    assert store.load_data()["day_officers"][DAY]["OFF-001"]["status"] == "غياب"


# ---------- الكاش ----------

def test_cached_files_are_reparsed_when_they_change_on_disk(client):
    """الكاش بيتقاس بـmtime والحجم — ملف اتغيّر من برّه لازم يتقرا تاني."""
    _add(client, DAY)
    assert len(store.load_data()["day_assignments"][DAY]) == 1

    store.day_path(DAY).write_text(
        json.dumps({"assignments": []}, ensure_ascii=False), encoding="utf-8")
    assert DAY not in store.load_data()["day_assignments"]
