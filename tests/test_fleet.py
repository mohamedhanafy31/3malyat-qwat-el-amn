def vehicle(client, **overrides):
    body = {"plate_series": "ب12", "plate_number": "4997", "type": "بيك اب",
            "model": "شفورلية"}
    body.update(overrides)
    return client.post("/api/vehicles", json=body)


def test_vehicle_crud_and_archived_filter(client):
    created = vehicle(client)
    assert created.status_code == 201, created.get_json()
    item = created.get_json()
    assert item["plate"] == "ب12/4997" and "بيك اب" in item["label"]

    updated = client.patch(f"/api/vehicles/{item['id']}", json={"archived": True})
    assert updated.status_code == 200
    assert client.get("/api/vehicles").get_json()["vehicles"] == []
    assert len(client.get("/api/vehicles?archived=1").get_json()["vehicles"]) == 1
    assert client.delete(f"/api/vehicles/{item['id']}").status_code == 200


def test_vehicle_validation_and_duplicate_plate(client):
    assert vehicle(client, type="دراجة").status_code == 400
    assert vehicle(client, plate_number="").status_code == 400
    assert vehicle(client, status="disabled").status_code == 400
    assert vehicle(client, plate_number="٤٩٩٧").status_code == 201
    assert vehicle(client, plate_number="4997").status_code == 409


def test_conscript_crud_and_duplicate_name(client):
    created = client.post("/api/conscripts", json={"name": "  سائق   حملة ", "phone": "0100"})
    assert created.status_code == 201, created.get_json()
    item = created.get_json()
    assert item["name"] == "سائق حملة"
    assert client.post("/api/conscripts", json={"name": "سائق حملة"}).status_code == 409
    assert client.patch(f"/api/conscripts/{item['id']}", json={"is_driver": False}).status_code == 200
    assert client.delete(f"/api/conscripts/{item['id']}").status_code == 200


def test_drivers_includes_effective_personnel_and_driver_conscript(client):
    person = client.post("/api/person", json={
        "type": "personnel", "name": "سائق قوة", "code": "991",
        "phone": "0101", "join_date": "2020-01-01", "role": "أمين شرطة",
        "post": "سائق الجلالة",
    }).get_json()
    client.post("/api/person", json={
        "type": "personnel", "name": "غير سائق", "code": "992",
        "phone": "0102", "join_date": "2020-01-01", "role": "أمين شرطة",
        "post": "مساعد",
    })
    conscript = client.post("/api/conscripts", json={"name": "سائق مجند"}).get_json()
    response = client.get("/api/drivers?day=2026-04-10")
    assert response.status_code == 200, response.get_json()
    data = response.get_json()
    assert any(item["id"] == person["id"] and item["post"] == "سائق الجلالة"
               for item in data["personnel"])
    assert any(item["id"] == conscript["id"] for item in data["conscripts"])
    assert not any(item["name"] == "غير سائق" for item in data["personnel"])


def test_external_vehicle_needs_party_and_shows_in_label(client):
    assert vehicle(client, plate_number="1111", origin="external").status_code == 400
    created = vehicle(client, plate_number="1111", origin="external", party="مديرية أمن السويس")
    assert created.status_code == 201
    body = created.get_json()
    assert body["origin"] == "external" and body["party"] == "مديرية أمن السويس"
    assert body["label"].endswith("(خارجية: مديرية أمن السويس)")
    listing = client.get("/api/vehicles?origin=external").get_json()
    assert [v["id"] for v in listing["vehicles"]] == [body["id"]]
    assert "external" in listing["origins"]
    # الرجوع لتبع الحملة بيمسح الجهة، والافتراضي تبع الحملة
    edited = client.patch(f"/api/vehicles/{body['id']}", json={"origin": "internal"}).get_json()
    assert edited["origin"] == "internal" and edited["party"] == ""
    assert vehicle(client, plate_number="2222").get_json()["origin"] == "internal"
