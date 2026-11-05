DAY = "2026-07-10"


def _vehicle(client, **extra):
    body = {"plate_series": "ب12", "plate_number": "4997", "type": "بيك اب"}
    body.update(extra)
    return client.post("/api/vehicles", json=body).get_json()


def _person(client, name, code):
    return client.post("/api/person", json={
        "type": "personnel", "name": name, "code": code, "phone": "0101",
        "join_date": "2020-01-01", "role": "أمين شرطة", "post": "سائق",
    }).get_json()


def _assignment(client, day, name):
    return client.post(f"/api/assignments/{day}", json={
        "name": name, "kind": "خارجية", "section": "الخدمات الطارئة",
    }).get_json()


def _campaign(client, day):
    response = client.get(f"/api/campaign/{day}")
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _row(rows, name):
    return next(item for item in rows if item["name"] == name)


def test_campaign_status_rules_and_section_summaries(client):
    driver = _person(client, "سائق الحالة", "980")
    vehicle_a = _vehicle(client, plate_number="6101")
    vehicle_b = _vehicle(client, plate_number="6102")

    client.put(f"/api/campaign/{DAY}/lorry/LOR-1", json={
        "vehicle_id": vehicle_a["id"], "driver": {"kind": "personnel", "id": driver["id"]}})
    client.put(f"/api/campaign/{DAY}/lorry/LOR-2", json={
        "driver": {"kind": "personnel", "id": driver["id"]}})
    client.put(f"/api/campaign/{DAY}/lorry/LOR-4", json={"vehicle_id": vehicle_b["id"]})
    client.put(f"/api/campaign/{DAY}/lorry/LOR-A1", json={
        "driver": {"kind": "personnel", "id": driver["id"]}})

    complete_post = client.post(f"/api/campaign/{DAY}/posts", json={
        "name": "ارتكاز كامل", "driver_text": "سائق حر"}).get_json()["posts"][0]
    client.put(f"/api/campaign/{DAY}/post/{complete_post['id']}", json={"plate_text": "ب13/7001"})
    client.post(f"/api/campaign/{DAY}/posts", json={"name": "ارتكاز ناقص", "driver_text": "سائق"})
    client.post(f"/api/campaign/{DAY}/posts", json={"name": "ارتكاز فارغ"})

    driver_only = client.post(f"/api/campaign/{DAY}/daily-rows", json={
        "name": "  سائق   بورتوفيق "}).get_json()["daily"][-1]
    regular = client.post(f"/api/campaign/{DAY}/daily-rows", json={"name": "قول عادي"}).get_json()["daily"][-1]
    client.put(f"/api/campaign/{DAY}/daily/{driver_only['id']}", json={
        "driver": {"kind": "personnel", "id": driver["id"]}})
    client.put(f"/api/campaign/{DAY}/daily/{regular['id']}", json={
        "driver": {"kind": "personnel", "id": driver["id"]}})

    view = _campaign(client, DAY)
    lorries = {row["id"]: row for row in view["lorries"]}
    assert (lorries["LOR-1"]["status"], lorries["LOR-1"]["missing"]) == ("complete", [])
    assert (lorries["LOR-2"]["status"], lorries["LOR-2"]["missing"]) == ("partial", ["vehicle"])
    assert (lorries["LOR-3"]["status"], lorries["LOR-3"]["missing"]) == ("empty", ["driver", "vehicle"])
    assert (lorries["LOR-4"]["status"], lorries["LOR-4"]["missing"]) == ("partial", ["driver"])
    assert view["summary"]["sections"]["lorries"] == {
        "complete": 1, "partial": 2, "empty": 1, "optional": 0, "missing": 3, "total": 4}

    appointments = {row["id"]: row for row in view["appointments"]}
    assert appointments["LOR-A1"]["status"] == "partial"
    assert appointments["LOR-A2"]["status"] == appointments["LOR-A3"]["status"] == "optional"
    assert view["summary"]["sections"]["appointments"]["total"] == 1
    assert view["summary"]["sections"]["appointments"]["optional"] == 2

    posts = {row["name"]: row for row in view["posts"]}
    assert posts["ارتكاز كامل"]["status"] == "complete"
    assert posts["ارتكاز ناقص"]["missing"] == ["vehicle"]
    assert posts["ارتكاز فارغ"]["status"] == "empty"
    assert view["summary"]["sections"]["posts"]["missing"] == 2

    daily = {row["id"]: row for row in view["daily"]}
    assert daily[driver_only["id"]]["status"] == "complete"
    assert daily[regular["id"]]["status"] == "partial"
    assert daily[regular["id"]]["missing"] == ["vehicle"]
    assert view["summary"]["overall"]["total"] == sum(
        item["total"] for item in view["summary"]["sections"].values())


def test_service_direct_carried_and_group_status_rules(client):
    driver = _person(client, "سائق الخدمات", "981")
    vehicles = [_vehicle(client, plate_number=str(6200 + index)) for index in range(1, 5)]
    missing_driver = _assignment(client, DAY, "مباشر ناقص")
    fallback_driver = _assignment(client, DAY, "مباشر كامل")
    carried_complete = _assignment(client, DAY, "محمول كامل")
    carried_partial = _assignment(client, DAY, "محمول ناقص")
    grouped_a = _assignment(client, DAY, "عضو مجموعة أ")
    grouped_b = _assignment(client, DAY, "عضو مجموعة ب")

    client.put(f"/api/campaign/{DAY}/service/{missing_driver['id']}", json={
        "vehicles": [{"vehicle_id": vehicles[0]["id"]}]})
    client.put(f"/api/campaign/{DAY}/service/{fallback_driver['id']}", json={
        "vehicles": [{"vehicle_id": vehicles[1]["id"]}],
        "driver": {"kind": "personnel", "id": driver["id"]}})
    client.put(f"/api/campaign/{DAY}/lorry/LOR-3", json={
        "vehicle_id": vehicles[2]["id"], "driver": {"kind": "personnel", "id": driver["id"]}})
    client.post(f"/api/campaign/{DAY}/lorry/LOR-3/service", json={
        "assignment_id": carried_complete["id"]})
    client.post(f"/api/campaign/{DAY}/lorry/LOR-A1/service", json={
        "assignment_id": carried_partial["id"]})
    grouped = client.post(f"/api/campaign/{DAY}/groups", json={
        "title": "مجموعة مكتملة", "members": [grouped_a["id"], grouped_b["id"]]}).get_json()
    group_id = grouped["group_id"]
    client.put(f"/api/campaign/{DAY}/group/{group_id}", json={
        "vehicle_id": vehicles[3]["id"], "driver": {"kind": "personnel", "id": driver["id"]}})

    view = _campaign(client, DAY)
    rows = {row["name"]: row for row in view["service_rows"]}
    assert (rows["مباشر ناقص"]["status"], rows["مباشر ناقص"]["missing"]) == ("partial", ["driver"])
    assert rows["مباشر كامل"]["status"] == "complete"
    assert rows["محمول كامل"]["status"] == "complete"
    assert rows["محمول كامل"]["status_text"] == "على لوري فيصل"
    assert rows["محمول كامل"]["service_vehicles"][0]["lorry_name"] == "فيصل"
    assert rows["محمول ناقص"]["status"] == "partial"
    assert rows["محمول ناقص"]["missing"] == ["driver", "vehicle"]
    assert "على لوري المديرية" in rows["محمول ناقص"]["status_text"]
    assert rows["مجموعة مكتملة"]["status"] == "complete"
    assert view["summary"]["sections"]["services"]["total"] == 5


def test_duplicate_warnings_cover_posts_and_every_direct_vehicle(client):
    driver = _person(client, "سائق مكرر", "982")
    shared = _vehicle(client, plate_number="6301")
    first_only = _vehicle(client, plate_number="6302")
    driver_other = _vehicle(client, plate_number="6303")
    first = _assignment(client, DAY, "خدمة أولى")
    second = _assignment(client, DAY, "خدمة ثانية")
    third = _assignment(client, DAY, "خدمة ثالثة")
    post = client.post(f"/api/campaign/{DAY}/posts", json={
        "name": "ارتكاز مشترك", "driver_text": "نص حر"}).get_json()["posts"][0]

    client.put(f"/api/campaign/{DAY}/lorry/LOR-2", json={"vehicle_id": shared["id"]})
    client.put(f"/api/campaign/{DAY}/post/{post['id']}", json={"vehicle_id": shared["id"]})
    client.put(f"/api/campaign/{DAY}/service/{first['id']}", json={"vehicles": [
        {"vehicle_id": first_only["id"], "driver": {"kind": "personnel", "id": driver["id"]}},
        {"vehicle_id": shared["id"]}]})
    client.put(f"/api/campaign/{DAY}/service/{second['id']}", json={
        "vehicles": [{"vehicle_id": shared["id"]}]})
    client.put(f"/api/campaign/{DAY}/service/{third['id']}", json={
        "vehicles": [{"vehicle_id": driver_other["id"],
                      "driver": {"kind": "personnel", "id": driver["id"]}}]})

    view = _campaign(client, DAY)
    first_row = _row(view["service_rows"], "خدمة أولى")
    assert any("المركبة مستخدمة أيضًا في" in text and "خدمة ثانية" in text
               for text in first_row["warnings"])
    assert any("السائق مستخدم أيضًا في" in text and "خدمة ثالثة" in text
               for text in first_row["warnings"])
    post_row = _row(view["posts"], "ارتكاز مشترك")
    assert any("القنصلية" in text and "المركبة مستخدمة أيضًا" in text
               for text in post_row["warnings"])


def test_duplicate_warnings_ignore_projections_carriers_and_group_members(client):
    driver = _person(client, "سائق غير مكرر", "983")
    lorry_driver = _person(client, "سائق اللوري", "984")
    direct_vehicle = _vehicle(client, plate_number="6401")
    lorry_vehicle = _vehicle(client, plate_number="6402")
    group_vehicle = _vehicle(client, plate_number="6403")
    direct = _assignment(client, DAY, "إسقاط أول مركبة")
    carried = _assignment(client, DAY, "خدمة على لوري")
    grouped_a = _assignment(client, DAY, "مشترك مجموعة أ")
    grouped_b = _assignment(client, DAY, "مشترك مجموعة ب")

    client.put(f"/api/campaign/{DAY}/service/{direct['id']}", json={
        "vehicles": [{"vehicle_id": direct_vehicle["id"],
                      "driver": {"kind": "personnel", "id": driver["id"]}}]})
    client.put(f"/api/campaign/{DAY}/lorry/LOR-3", json={
        "vehicle_id": lorry_vehicle["id"], "driver": {"kind": "personnel", "id": lorry_driver["id"]}})
    client.post(f"/api/campaign/{DAY}/lorry/LOR-3/service", json={"assignment_id": carried["id"]})
    grouped = client.post(f"/api/campaign/{DAY}/groups", json={
        "title": "مجموعة بلا تكرار", "members": [grouped_a["id"], grouped_b["id"]]}).get_json()
    client.put(f"/api/campaign/{DAY}/group/{grouped['group_id']}", json={
        "vehicle_id": group_vehicle["id"], "driver": {"kind": "text", "name": "سائق مجموعة"}})

    view = _campaign(client, DAY)
    assert not _row(view["service_rows"], "إسقاط أول مركبة")["warnings"]
    assert not _row(view["service_rows"], "خدمة على لوري")["warnings"]
    assert not _row(view["service_rows"], "مجموعة بلا تكرار")["warnings"]
