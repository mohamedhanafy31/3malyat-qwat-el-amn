"""توريث يومية الحملة لكل صف على حدة من أحدث يوم سابق فيه قيمة الصف."""
from backend import campaign

FULL, PARTIAL, LATER = "2026-12-01", "2026-12-02", "2026-12-03"


def _vehicle(client, number="4997"):
    return client.post("/api/vehicles", json={
        "plate_series": "ب12", "plate_number": number, "type": "بيك اب"}).get_json()


def _person(client, name="سائق توريث", code="971"):
    return client.post("/api/person", json={
        "type": "personnel", "name": name, "code": code, "phone": "0101",
        "join_date": "2020-01-01", "role": "أمين شرطة", "post": "سائق"}).get_json()


def _touch(client, day):
    """يحفظ اليوم بصف واحد بس (سائق LOR-4، من غير مركبة)، زي يوم ناقص."""
    if not hasattr(client, "_night"):
        client._night = _person(client, "سائق الليل", "972")
    assert client.put(f"/api/campaign/{day}/lorry/LOR-4", json={
        "driver": {"kind": "personnel", "id": client._night["id"]}}).status_code == 200


def _view(client, day):
    response = client.get(f"/api/campaign/{day}")
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _row(view, section, ident):
    return next(row for row in view[section] if row["id"] == ident)


def _seed(client):
    """يوم كامل (مركبة وسائق لكل صف) ثم يوم ناقص بعده فيه صف واحد بس."""
    vehicles = [_vehicle(client, str(5000 + i)) for i in range(4)]
    driver = _person(client)
    client.put(f"/api/campaign/{FULL}/lorry/LOR-1", json={
        "vehicle_id": vehicles[0]["id"], "driver": {"kind": "personnel", "id": driver["id"]}})
    client.put(f"/api/campaign/{FULL}/lorry/LOR-2", json={"vehicle_id": vehicles[1]["id"]})
    post = client.post(f"/api/campaign/{FULL}/posts", json={"name": "كمين توريث"}).get_json()["posts"][-1]
    assert post["name"] == "كمين توريث"
    client.put(f"/api/campaign/{FULL}/post/{post['id']}", json={
        "vehicle_id": vehicles[2]["id"], "driver_text": "سائق الكمين"})
    client.put(f"/api/campaign/{FULL}/plates", json={"rows": [["ب13/9416"]]})
    _touch(client, PARTIAL)
    return vehicles, driver, post["id"]


def test_partial_day_does_not_cut_inheritance_for_later_days(client):
    vehicles, driver, post_id = _seed(client)
    view = _view(client, LATER)
    lorry = _row(view, "lorries", "LOR-1")
    assert lorry["vehicle"]["id"] == vehicles[0]["id"] and lorry["driver"]["id"] == driver["id"]
    assert lorry["inherited"] is True
    assert _row(view, "lorries", "LOR-2")["vehicle"]["id"] == vehicles[1]["id"]
    post = _row(view, "posts", post_id)
    assert post["vehicle"]["id"] == vehicles[2]["id"] and post["driver_text"] == "سائق الكمين"
    assert view["plates"]["rows"] == [["ب13/9416"]] and view["plates"]["inherited"] is True
    # اليوم الناقص نفسه كان بيورّث من الكامل وبيفضل كده
    assert _row(_view(client, PARTIAL), "posts", post_id)["vehicle"]["id"] == vehicles[2]["id"]


def test_inheritance_is_per_row_and_per_field_latest_value_wins(client):
    vehicles, driver, post_id = _seed(client)
    # اليوم الناقص بيغيّر مركبة LOR-1 بس؛ السائق يفضل من اليوم الكامل
    client.put(f"/api/campaign/{PARTIAL}/lorry/LOR-1", json={"vehicle_id": vehicles[3]["id"]})
    lorry = _row(_view(client, LATER), "lorries", "LOR-1")
    assert lorry["vehicle"]["id"] == vehicles[3]["id"]
    assert lorry["driver"]["id"] == driver["id"]
    assert _row(_view(client, LATER), "lorries", "LOR-2")["vehicle"]["id"] == vehicles[1]["id"]


def test_campaign_exposes_source_day_per_visible_inherited_field(client):
    vehicles, driver, post_id = _seed(client)
    client.put(f"/api/campaign/{PARTIAL}/lorry/LOR-1", json={"vehicle_id": vehicles[3]["id"]})
    daily = client.post(f"/api/campaign/{FULL}/daily-rows", json={"name": "قول مصدر"}).get_json()
    daily_id = next(row["id"] for row in daily["daily"] if row["name"] == "قول مصدر")
    client.put(f"/api/campaign/{FULL}/daily/{daily_id}", json={
        "vehicle_id": vehicles[1]["id"], "driver": {"kind": "personnel", "id": driver["id"]}})

    carried = client.post(f"/api/assignments/{LATER}", json={
        "name": "خدمة محمولة بمصدر", "kind": "خارجية", "section": "الخدمات الطارئة",
    }).get_json()
    client.post(f"/api/campaign/{LATER}/lorry/LOR-1/service", json={
        "assignment_id": carried["id"]})

    view = _view(client, LATER)
    lorry = _row(view, "lorries", "LOR-1")
    assert lorry["inherited_from"] == {"driver": FULL, "vehicle": PARTIAL}
    assert _row(view, "lorries", "LOR-2")["inherited_from"] == {"vehicle": FULL}
    assert _row(view, "posts", post_id)["inherited_from"] == {"driver": FULL, "vehicle": FULL}
    assert _row(view, "daily", daily_id)["inherited_from"] == {"driver": FULL, "vehicle": FULL}
    assert view["plates"]["inherited_from"] == {"plates": FULL}
    service = _row(view, "service_rows", carried["id"])
    assert service["inherited_from"] == {"driver": FULL, "vehicle": PARTIAL}


def test_current_values_have_no_inherited_source_day(client):
    vehicle = _vehicle(client, "5991")
    driver = _person(client, "سائق اليوم الحالي", "973")
    client.put(f"/api/campaign/{LATER}/lorry/LOR-1", json={
        "vehicle_id": vehicle["id"], "driver": {"kind": "personnel", "id": driver["id"]}})
    client.put(f"/api/campaign/{LATER}/plates", json={"rows": [["ب13/9001"]]})
    view = _view(client, LATER)
    assert _row(view, "lorries", "LOR-1")["inherited_from"] == {}
    assert view["plates"]["inherited_from"] == {}


def test_explicit_clear_stops_the_walk_back(client):
    vehicles, driver, post_id = _seed(client)
    client.put(f"/api/campaign/{PARTIAL}/lorry/LOR-1", json={"driver": None})
    lorry = _row(_view(client, LATER), "lorries", "LOR-1")
    assert lorry["driver"] is None                      # المسح الصريح مايرجعش لليوم الأقدم
    assert lorry["vehicle"]["id"] == vehicles[0]["id"]  # والمركبة (مش اتمسحت) لسه موروثة

    client.put(f"/api/campaign/{PARTIAL}/lorry/LOR-2", json={"vehicle_id": ""})
    assert _row(_view(client, LATER), "lorries", "LOR-2")["vehicle"] is None


def test_explicit_empty_driver_object_is_a_clear(client, data_file):
    vehicles, driver, post_id = _seed(client)
    _touch(client, PARTIAL)
    from backend import store
    data = store.load_data()
    data["day_campaign"][PARTIAL].setdefault("lorries", {})["LOR-1"] = {"driver": {}}
    store.save_data(data)
    lorry = _row(_view(client, LATER), "lorries", "LOR-1")
    assert lorry["driver"] is None and lorry["vehicle"]["id"] == vehicles[0]["id"]


def test_walk_back_stops_at_the_window(client):
    vehicles, *_ = _seed(client)
    far = "2027-01-20"  # أبعد من نافذة ٣١ يوم عن اليوم الكامل
    _touch(client, far)
    assert _row(_view(client, far), "lorries", "LOR-1")["vehicle"] is None
    inside = "2027-01-01"  # ٣١ يوم بالظبط لسه جوه النافذة
    _touch(client, inside)
    assert _row(_view(client, inside), "lorries", "LOR-1")["vehicle"]["id"] == vehicles[0]["id"]


def test_days_before_the_cutoff_keep_single_previous_day_inheritance(client):
    old_full, old_partial, old_later = "2026-10-01", "2026-10-02", "2026-10-03"
    vehicle = _vehicle(client, "5900")
    client.put(f"/api/campaign/{old_full}/lorry/LOR-1", json={"vehicle_id": vehicle["id"]})
    _touch(client, old_partial)
    assert _row(_view(client, old_partial), "lorries", "LOR-1")["vehicle"]["id"] == vehicle["id"]
    assert _row(_view(client, old_later), "lorries", "LOR-1")["vehicle"] is None


def test_inheritance_days_helper():
    days = ["2026-10-01", "2026-11-04", "2026-12-01", "2026-12-02"]
    assert campaign.inheritance_days(days, "2026-10-20") == ["2026-10-01"]
    # من INHERIT_WALK_FROM بيتطبق مدى الرجوع: 10-01 أبعد من 31 يوم عن 11-04.
    assert campaign.inheritance_days(days, "2026-11-04") == []
    assert campaign.inheritance_days(days, "2026-10-25") == ["2026-10-01"]
    assert campaign.inheritance_days(days, "2026-12-03") == ["2026-11-04", "2026-12-01", "2026-12-02"]
    assert campaign.inheritance_days(days, "2026-09-01") == []
    assert campaign.inheritance_days(days, "2027-03-01") == []


def test_saving_a_later_day_does_not_touch_earlier_days(client, data_file):
    vehicles, *_ = _seed(client)
    from backend import store
    before = store.load_data()["day_campaign"][FULL]
    client.put(f"/api/campaign/{LATER}/lorry/LOR-3", json={"vehicle_id": vehicles[3]["id"]})
    after = store.load_data()["day_campaign"]
    assert after[FULL] == before and "LOR-1" not in (after[LATER].get("lorries") or {})
