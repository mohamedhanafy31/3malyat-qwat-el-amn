"""سجل التغييرات التشغيلية — مين عدّل إيه وإمتى، بالقيمة قبل وبعد.

تغييرات اليومية التفصيلية بتتسجّل وقت **تأكيد** اليومية مش وقت الحفظ —
التفاصيل في tests/test_confirm.py.
"""
from urllib.parse import quote

DAY = "2026-04-10"


def _entries(client, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get(f"/api/changes{'?' + q if q else ''}").get_json()["entries"]


def _confirm(client, **kw):
    return client.post(f"/api/board/{DAY}/confirm", json={}, **kw)


def test_saving_an_assignment_records_nothing_on_its_own(client):
    """الحفظ مسوّدة — المشغّل بيلعب في اليومية طول اليوم، والسجل كان
    بيمتلئ بخطوات وسيطة مالهاش معنى تشغيلي."""
    client.post(f"/api/assignments/{DAY}", json={"name": "دورية خارجية", "kind": "خارجية"})
    assert _entries(client, entity="assignment") == []


def test_confirming_records_a_newly_added_service(client):
    _confirm(client)                                  # خط الأساس
    r = client.post(f"/api/assignments/{DAY}", json={"name": "دورية خارجية", "kind": "خارجية"})
    aid = r.get_json()["id"]
    _confirm(client)

    entries = _entries(client, entity="assignment", entity_id=aid)
    assert len(entries) == 1
    assert entries[0]["action"] == "create"
    assert entries[0]["before"] is None
    assert entries[0]["after"]["name"] == "دورية خارجية"


def test_confirming_records_an_edit_with_before_and_after(client):
    r = client.post(f"/api/assignments/{DAY}", json={"name": "دورية خارجية", "kind": "خارجية"})
    aid = r.get_json()["id"]
    _confirm(client)
    client.patch(f"/api/assignments/{DAY}/{aid}", json={"name": "اسم جديد"})
    _confirm(client)

    update = next(e for e in _entries(client, entity="assignment", entity_id=aid)
                  if e["action"] == "update")
    assert update["before"]["name"] == "دورية خارجية"
    assert update["after"]["name"] == "اسم جديد"


def test_confirming_records_a_deletion_with_the_final_state(client):
    r = client.post(f"/api/assignments/{DAY}", json={"name": "خدمة للحذف", "kind": "خارجية"})
    aid = r.get_json()["id"]
    _confirm(client)
    client.delete(f"/api/assignments/{DAY}/{aid}")
    _confirm(client)

    delete = next(e for e in _entries(client, entity="assignment", entity_id=aid)
                  if e["action"] == "delete")
    assert delete["before"]["name"] == "خدمة للحذف"
    assert delete["after"] is None


def test_officer_state_change_is_recorded(client):
    client.put(f"/api/duty/{DAY}/OFF-001", json={"taqseera": True})
    entries = _entries(client, entity="officer_state", entity_id="OFF-001")
    assert len(entries) == 1
    assert entries[0]["after"]["taqseera"] is True


def test_clearing_an_empty_state_records_nothing(client):
    """مفيش تغيير حقيقي حصل — مفيش داعي لسجل فاضي."""
    client.delete(f"/api/duty/{DAY}/OFF-001")
    assert _entries(client, entity="officer_state", entity_id="OFF-001") == []


def test_leave_lifecycle_is_recorded(client):
    r = client.post("/api/leaves", json={
        "person_id": "OFF-002", "type": "أسبوعية", "start": "2026-02-01", "end": "2026-02-01"})
    lid = r.get_json()["id"]
    client.patch(f"/api/leaves/{lid}", json={"note": "تعديل"})
    client.delete(f"/api/leaves/{lid}")

    entries = _entries(client, entity="leave", entity_id=lid)
    actions = [e["action"] for e in entries]
    assert actions == ["delete", "update", "create"], "الأحدث أولًا"


def test_entity_filter_only_returns_that_entity(client):
    client.post(f"/api/assignments/{DAY}", json={"name": "خدمة", "kind": "خارجية"})
    _confirm(client)
    client.post("/api/leaves", json={
        "person_id": "OFF-002", "type": "أسبوعية", "start": "2026-02-01", "end": "2026-02-01"})
    entries = _entries(client, entity="leave")
    assert all(e["entity"] == "leave" for e in entries)
    assert len(entries) == 1


def test_day_filter_only_returns_that_days_entries(client):
    client.post(f"/api/assignments/{DAY}", json={"name": "خدمة", "kind": "خارجية"})
    _confirm(client)
    client.post("/api/board/2026-04-11/confirm", json={})

    entries = _entries(client, day=DAY)
    assert entries and all(e["day"] == DAY for e in entries)


def test_edited_by_is_captured_from_the_header(client):
    client.post(f"/api/assignments/{DAY}", json={"name": "خدمة", "kind": "خارجية"})
    _confirm(client, headers={"X-Edited-By": quote("محمد")})
    entries = _entries(client, entity="day_confirm")
    assert entries[0]["edited_by"] == "محمد"


def test_log_is_capped(client, monkeypatch):
    from backend import changes, store
    monkeypatch.setattr(changes, "MAX_ENTRIES", 3)

    def mutate(data):
        for i in range(6):
            changes.record(data, "assignment", f"AS-{i}", "create", after={"i": i})
        return None

    store.with_data(mutate)
    data = store.load_data()
    assert len(changes.log(data)) == 3
    assert [e["entity_id"] for e in changes.log(data)] == ["AS-3", "AS-4", "AS-5"]


def test_entries_dropped_from_the_cap_are_archived_not_lost(client, monkeypatch):
    """السطور اللي بتتشال من data.json لما السقف يوصله مش لازم تروح
    للأبد — بتتضاف لملف أرشيف قبل الحذف."""
    import json
    from backend import changes, store

    monkeypatch.setattr(changes, "MAX_ENTRIES", 3)

    def mutate(data):
        for i in range(6):
            changes.record(data, "assignment", f"AS-{i}", "create", after={"i": i})
        return None

    store.with_data(mutate)

    archived = [json.loads(line) for line in changes._archive_path().read_text(
        encoding="utf-8").splitlines()]
    assert [e["entity_id"] for e in archived] == ["AS-0", "AS-1", "AS-2"]
