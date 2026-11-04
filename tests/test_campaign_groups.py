import io
from urllib.parse import quote

from docx import Document

from backend import campaign, store

DAY = "2026-07-10"


def _vehicle(client, number="4997"):
    return client.post("/api/vehicles", json={
        "plate_series": "ب12", "plate_number": number, "type": "بيك اب"}).get_json()


def _assignment(client, name, day=DAY):
    return client.post(f"/api/assignments/{day}", json={
        "name": name, "kind": "خارجية", "section": "الخدمات الطارئة"}).get_json()


def _view(client, day=DAY):
    return client.get(f"/api/campaign/{day}").get_json()


def _services(view):
    return {row["id"]: row for row in view["services"]}


def _group(client, ids, title="توصيل مجندين المباريات 1م", day=DAY, **extra):
    view = _view(client, day)
    return client.post(f"/api/campaign/{day}/groups", json={
        "title": title, "members": ids, "revision": view["revision"], **extra})


def _two(client):
    return (_assignment(client, "مباراة ملعب ش المثلث")["id"],
            _assignment(client, "مباراة ملعب ش التوفيق")["id"])


def test_create_group_makes_one_line_and_hides_members(client):
    a, b = _two(client)
    c = _assignment(client, "خدمة أخرى")["id"]
    response = _group(client, [a, b])
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    rows = _services(body)
    assert a not in rows and b not in rows and c in rows
    group = rows[body["group_id"]]
    assert group["kind"] == "group" and group["name"] == "توصيل مجندين المباريات 1م"
    assert [m["id"] for m in group["members"]] == [a, b]
    assert a not in {x["assignment_id"] for x in body["pickers"]["attachable"]}


def test_create_group_validation(client):
    a, b = _two(client)
    assert _group(client, [a]).status_code == 400
    assert _group(client, [a, a]).status_code == 400
    assert _group(client, [a, b], title="  ").status_code == 400
    assert _group(client, [a, "ASG-999"]).status_code == 404
    assert _group(client, [a, b]).status_code == 200
    c = _assignment(client, "ثالثة")["id"]
    again = _group(client, [a, c])
    assert again.status_code == 409
    # لوري ملحق
    assert client.post(f"/api/campaign/{DAY}/lorry/LOR-3/service", json={"assignment_id": c}).status_code == 200
    d = _assignment(client, "رابعة")["id"]
    assert _group(client, [c, d]).status_code == 409


def test_group_vehicle_driver_inherited_by_members(client):
    a, b = _two(client)
    gid = _group(client, [a, b]).get_json()["group_id"]
    vehicle = _vehicle(client)
    response = client.put(f"/api/campaign/{DAY}/group/{gid}", json={
        "vehicle_id": vehicle["id"], "driver": {"kind": "text", "name": "سائق المجموعة"},
        "revision": _view(client)["revision"]})
    assert response.status_code == 200, response.get_json()
    row = _services(response.get_json())[gid]
    assert row["vehicle"]["id"] == vehicle["id"] and row["driver"]["name"] == "سائق المجموعة"
    data = store.load_data(lambda view: {DAY})
    for member in (a, b):
        got = campaign.service_vehicles(data, DAY, member)
        assert [x["vehicle_id"] for x in got] == [vehicle["id"]]
        assert got[0]["driver"]["name"] == "سائق المجموعة"
    # الخدمة العضو مقفولة للتعديل المباشر
    assert client.put(f"/api/campaign/{DAY}/service/{a}", json={"vehicle_id": ""}).status_code == 409
    # المركبة مرجعية فلا تُحذف
    assert client.delete(f"/api/vehicles/{vehicle['id']}").status_code == 409


def test_ungroup_restores_members_with_their_own_entries(client):
    a, b = _two(client)
    own = _vehicle(client, "5001")
    assert client.put(f"/api/campaign/{DAY}/service/{a}", json={
        "vehicle_id": own["id"], "driver": {"kind": "text", "name": "سائق أ"}}).status_code == 200
    created = _group(client, [a, b]).get_json()
    gid = created["group_id"]
    # بيبدأ بمركبة أول عضو مسكّن
    assert _services(created)[gid]["vehicle"]["id"] == own["id"]
    other = _vehicle(client, "5002")
    client.put(f"/api/campaign/{DAY}/group/{gid}", json={"vehicle_id": other["id"]})
    out = client.delete(f"/api/campaign/{DAY}/groups/{gid}", json={"revision": _view(client)["revision"]})
    assert out.status_code == 200
    rows = _services(out.get_json())
    assert gid not in rows and a in rows and b in rows
    assert rows[a]["vehicles"][0]["vehicle_id"] == own["id"]
    assert rows[a]["driver"]["name"] == "سائق أ" or rows[a]["vehicles"][0]["driver"]["name"] == "سائق أ"
    assert rows[b]["vehicles"] == []


def test_rename_add_remove_members(client):
    a, b = _two(client)
    c = _assignment(client, "ثالثة")["id"]
    gid = _group(client, [a, b]).get_json()["group_id"]
    rev = lambda: _view(client)["revision"]
    out = client.patch(f"/api/campaign/{DAY}/groups/{gid}", json={"title": "جديد", "add": [c], "revision": rev()})
    assert out.status_code == 200, out.get_json()
    row = _services(out.get_json())[gid]
    assert row["name"] == "جديد" and [m["id"] for m in row["members"]] == [a, b, c]
    out = client.patch(f"/api/campaign/{DAY}/groups/{gid}", json={"remove": [c], "revision": rev()})
    assert c in _services(out.get_json())
    assert client.patch(f"/api/campaign/{DAY}/groups/{gid}", json={"remove": [b], "revision": rev()}).status_code == 400
    assert client.patch(f"/api/campaign/{DAY}/groups/{gid}", json={"remove": ["x"], "revision": rev()}).status_code == 404
    assert client.patch(f"/api/campaign/{DAY}/groups/NOPE", json={"title": "x", "revision": rev()}).status_code == 404
    data = store.load_data(lambda view: {DAY})
    from backend import changes
    assert {e["action"] for e in changes.recent(data, entity="campaign_group")} >= {"create", "update"}


def test_stale_revision_rejected(client):
    a, b = _two(client)
    first = _view(client)["revision"]
    assert _group(client, [a, b]).status_code == 200
    stale = client.post(f"/api/campaign/{DAY}/groups", json={
        "title": "x", "members": [a, b], "revision": first})
    assert stale.status_code == 409 and stale.get_json()["code"] == "stale_revision"


def test_groups_not_inherited_next_day(client):
    a, b = _two(client)
    _group(client, [a, b])
    next_day = "2026-07-11"
    na, nb = _assignment(client, "مباراة ملعب ش المثلث", next_day)["id"], _assignment(client, "مباراة ملعب ش التوفيق", next_day)["id"]
    view = _view(client, next_day)
    assert {na, nb} <= set(_services(view))
    assert not any(row["kind"] == "group" for row in view["services"])


def test_export_single_row_with_group_title(client):
    a, b = _two(client)
    gid = _group(client, [a, b], title="توصيل مجندين المباريات 1م").get_json()["group_id"]
    vehicle = _vehicle(client)
    client.put(f"/api/campaign/{DAY}/group/{gid}", json={
        "vehicle_id": vehicle["id"], "driver": {"kind": "text", "name": "سائق المجموعة"}})
    doc = Document(io.BytesIO(client.get(f"/api/campaign/{DAY}/export.docx").data))
    texts = [c.text for table in doc.tables for row in table.rows
             for c in {id(cell._tc): cell for cell in row.cells}.values()]
    assert texts.count("توصيل مجندين المباريات 1م") == 1
    assert not any("ش المثلث" in t or "ش التوفيق" in t for t in texts)


def test_closed_day_requires_reason(client):
    a, b = _two(client)
    client.post(f"/api/day-status/{DAY}/close", json={})
    body = {"title": "مجموعة", "members": [a, b], "revision": _view(client)["revision"]}
    refused = client.post(f"/api/campaign/{DAY}/groups", json=body)
    assert refused.status_code == 409 and refused.get_json()["needs_reason"] is True
    allowed = client.post(f"/api/campaign/{DAY}/groups", json=body,
                          headers={"X-Retro-Reason": quote("تصحيح")})
    assert allowed.status_code == 200, allowed.get_json()
    assert any(x["kind"] == "group" for x in allowed.get_json()["services"])


def test_group_writes_follow_sibling_campaign_permissions(client, anon_client, conscript_client):
    a, b = _two(client)
    body = {"title": "x", "members": [a, b], "revision": _view(client)["revision"]}
    assert anon_client.post(f"/api/campaign/{DAY}/groups", json=body).status_code == 401
    # نفس صلاحية بقية كتابات الحملة (put lorry) للدور نفسه
    sibling = conscript_client.put(f"/api/campaign/{DAY}/lorry/LOR-1", json={"vehicle_id": ""}).status_code
    assert conscript_client.post(f"/api/campaign/{DAY}/groups", json=body).status_code == sibling or sibling == 200


def test_group_revision_matches_campaign_scope_when_other_days_have_status(client):
    """مسار المجموعات بيحمّل أيام الحالة كمان؛ توكن المراجعة لازم يفضل نفس
    توكن GET وباقي نقاط الحملة، وإلا كل تجميع يرجع stale_revision."""
    store.with_data(lambda data: day_status_close(data, "2026-07-01"))
    a, b = _two(client)
    created = _group(client, [a, b])
    assert created.status_code == 200, created.get_json()
    assert created.get_json()["revision"] == _view(client)["revision"]


def day_status_close(data, day):
    from backend import day_status
    day_status.close_day(data, day, "اختبار")
