DAY = "2026-07-10"


def _assignment(client, name):
    return client.post(f"/api/assignments/{DAY}", json={
        "name": name, "kind": "خارجية", "section": "الخدمات الطارئة"}).get_json()


def test_remove_restore_keeps_assignment_and_campaign_values(client):
    service = _assignment(client, "خدمة اختبار الإزالة")
    ident = service["id"]
    before = client.put(f"/api/campaign/{DAY}/service/{ident}", json={
        "driver_text": "سائق محفوظ", "plate_text": "ب15/1487"}).get_json()
    assert before["services"]
    removed = client.delete(f"/api/campaign/{DAY}/service/{ident}/removed")
    assert removed.status_code == 200
    payload = removed.get_json()
    assert ident not in {row["id"] for row in payload["service_rows"]}
    assert payload["removed_services"][0]["id"] == ident
    restored = client.post(f"/api/campaign/{DAY}/service/{ident}/restore")
    assert restored.status_code == 200
    assert ident in {row["id"] for row in restored.get_json()["service_rows"]}


def test_group_member_cannot_be_removed(client):
    one = _assignment(client, "خدمة مجموعة أ")
    two = _assignment(client, "خدمة مجموعة ب")
    group = client.post(f"/api/campaign/{DAY}/groups", json={
        "title": "مجموعة اختبار", "members": [one["id"], two["id"]]}).get_json()
    assert group.get("group_id")
    response = client.delete(f"/api/campaign/{DAY}/service/{one['id']}/removed")
    assert response.status_code == 409
    assert "فك التجميع أولًا" in response.get_json()["error"]


# ---- ما بعد الإزالة: التصدير، اسم اللوري، الصفحات التانية، الحماية ----

from io import BytesIO

from docx import Document


def _export_rows(client, day=DAY):
    response = client.get(f"/api/campaign/{day}/export.docx")
    assert response.status_code == 200
    document = Document(BytesIO(response.data))
    return [" | ".join(dict.fromkeys(cell.text.strip() for cell in row.cells if cell.text.strip()))
            for row in document.tables[0].rows]


def _payload(client, day=DAY):
    return client.get(f"/api/campaign/{day}").get_json()


def test_removed_service_leaves_the_export_and_returns_on_restore(client):
    ident = _assignment(client, "خدمة تتشال من التصدير")["id"]
    client.put(f"/api/campaign/{DAY}/service/{ident}", json={"driver_text": "س", "plate_text": "ب15/1487"})
    assert any("خدمة تتشال من التصدير" in row for row in _export_rows(client))

    assert client.delete(f"/api/campaign/{DAY}/service/{ident}/removed").status_code == 200
    assert not any("خدمة تتشال من التصدير" in row for row in _export_rows(client))

    assert client.post(f"/api/campaign/{DAY}/service/{ident}/restore").status_code == 200
    assert any("خدمة تتشال من التصدير" in row for row in _export_rows(client))


def test_removed_attached_service_disappears_from_the_lorry_label_and_returns(client):
    ident = _assignment(client, "خدمة ملحقة بلوري")["id"]
    attach = client.post(f"/api/campaign/{DAY}/lorry/LOR-1/service", json={"assignment_id": ident})
    assert attach.status_code == 200

    def lorry():
        return next(row for row in _payload(client)["lorries"] if row["id"] == "LOR-1")

    assert "خدمة ملحقة بلوري" in lorry()["name"]
    assert client.delete(f"/api/campaign/{DAY}/service/{ident}/removed").status_code == 200
    assert "خدمة ملحقة بلوري" not in lorry()["name"]
    assert ident not in [item.get("assignment_id") for item in lorry()["attached"]]
    assert not any("خدمة ملحقة بلوري" in row for row in _export_rows(client))

    assert client.post(f"/api/campaign/{DAY}/service/{ident}/restore").status_code == 200
    assert "خدمة ملحقة بلوري" in lorry()["name"]      # الإلحاق نفسه ما اتمسحش
    assert any("خدمة ملحقة بلوري" in row for row in _export_rows(client))


def test_removing_a_service_from_the_campaign_does_not_touch_other_pages(client):
    ident = _assignment(client, "خدمة لا تؤثر على اللوحة")["id"]

    def snapshot():
        board = client.get(f"/api/board/{DAY}").get_json()
        board.pop("revision", None)
        duty = client.get(f"/api/duty/{DAY}").get_json()
        duty.pop("revision", None)
        return board, duty

    before = snapshot()
    client.delete(f"/api/campaign/{DAY}/service/{ident}/removed")
    assert snapshot() == before
    client.post(f"/api/campaign/{DAY}/service/{ident}/restore")
    assert snapshot() == before


def test_removed_counters_and_stale_ids(client):
    ident = _assignment(client, "خدمة العداد")["id"]
    total_before = _payload(client)["summary"]["overall"]["total"]
    client.delete(f"/api/campaign/{DAY}/service/{ident}/removed")
    assert _payload(client)["summary"]["overall"]["total"] == total_before - 1
    # لو التكليف نفسه اتمسح من اللوحة، المعرّف المزال بيتنضّف ومابيفضلش في القايمة
    assert client.delete(f"/api/assignments/{DAY}/{ident}").status_code == 200
    assert _payload(client)["removed_services"] == []


def test_remove_restore_guards(client, anon_client):
    ident = _assignment(client, "خدمة الحماية")["id"]
    assert client.delete(f"/api/campaign/{DAY}/service/AS-9999/removed").status_code == 404
    assert client.post(f"/api/campaign/{DAY}/service/AS-9999/restore").status_code in (404, 409)
    assert anon_client.delete(f"/api/campaign/{DAY}/service/{ident}/removed").status_code == 401
    assert client.post(f"/api/day-status/{DAY}/close").status_code == 201
    closed = client.delete(f"/api/campaign/{DAY}/service/{ident}/removed")
    assert closed.status_code == 409
    assert ident in {row["id"] for row in _payload(client)["service_rows"]}
