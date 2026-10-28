"""صفحة قادة الأهداف: مناصب مؤرخة مستقلة عن التغطية اليومية."""
from backend.board import target_rows_for_day
from backend.people import effective
from backend.store import load_data


DAY = "2026-04-10"


def snapshot(client, day=DAY):
    response = client.get(f"/api/target-commanders/{day}")
    assert response.status_code == 200
    return response.get_json()


def blank_assignments(payload):
    return {target["name"]: None for target in payload["targets"]}


def save(client, payload, assignments, day=DAY):
    return client.put(f"/api/target-commanders/{day}", json={
        "revision": payload["revision"], "assignments": assignments,
    })


def test_page_explains_fixed_commander_and_has_sidebar_link(client):
    html = client.get("/target-commanders").get_data(as_text=True)
    assert 'data-page="target_commanders"' in html
    assert "القائد الثابت غير الضابط المعيّن يوميًا" in html
    assert 'href="/target-commanders"' in html
    assert client.get("/api/bootstrap/target_commanders").status_code == 200


def test_assigning_commander_updates_board_from_effective_day_only(client):
    payload = snapshot(client)
    assignments = blank_assignments(payload)
    supervisor = payload["targets"][0]["name"]
    assignments[supervisor] = "OFF-001"

    response = save(client, payload, assignments)
    assert response.status_code == 200
    saved = response.get_json()
    assert len(saved["changed"]) == 1
    assert saved["targets"][0]["commanders"][0]["id"] == "OFF-001"

    data = load_data(())
    person = next(row for row in data["officers"] if row["id"] == "OFF-001")
    assert effective(person, DAY)["post"] == "رئيس قسم الحراسات المشددة"
    assert effective(person, "2026-04-09")["post"] == ""
    rows = target_rows_for_day(data, DAY)
    assert rows[0]["commander"][0]["id"] == "OFF-001"


def test_changing_and_vacating_commander_preserve_previous_days(client):
    first = snapshot(client, "2026-04-10")
    assignments = blank_assignments(first)
    target = first["targets"][1]["name"]
    assignments[target] = "OFF-001"
    assert save(client, first, assignments, "2026-04-10").status_code == 200

    second = snapshot(client, "2026-04-15")
    assignments = blank_assignments(second)
    assignments[target] = "OFF-002"
    assert save(client, second, assignments, "2026-04-15").status_code == 200

    data = load_data(())
    old = target_rows_for_day(data, "2026-04-14")[1]["commander"]
    new = target_rows_for_day(data, "2026-04-15")[1]["commander"]
    assert [row["id"] for row in old] == ["OFF-001"]
    assert [row["id"] for row in new] == ["OFF-002"]

    third = snapshot(client, "2026-04-20")
    assignments = blank_assignments(third)
    assert save(client, third, assignments, "2026-04-20").status_code == 200
    assert target_rows_for_day(load_data(()), "2026-04-20")[1]["commander"] == []


def test_duplicate_or_unknown_officer_is_rejected_atomically(client):
    payload = snapshot(client)
    assignments = blank_assignments(payload)
    assignments[payload["targets"][0]["name"]] = "OFF-001"
    assignments[payload["targets"][1]["name"]] = "OFF-001"
    response = save(client, payload, assignments)
    assert response.status_code == 400
    assert "لأكثر من هدف" in response.get_json()["error"]
    assert all(not target["commanders"] for target in snapshot(client)["targets"])

    fresh = snapshot(client)
    assignments = blank_assignments(fresh)
    assignments[fresh["targets"][0]["name"]] = "OFF-NOT-THERE"
    response = save(client, fresh, assignments)
    assert response.status_code == 400
    assert all(not target["commanders"] for target in snapshot(client)["targets"])


def test_stale_revision_and_incomplete_table_are_rejected(client):
    old = snapshot(client)
    assignments = blank_assignments(old)
    assignments[old["targets"][0]["name"]] = "OFF-001"
    assert save(client, old, assignments).status_code == 200

    stale = save(client, old, blank_assignments(old))
    assert stale.status_code == 409
    assert stale.get_json()["code"] == "stale_revision"

    current = snapshot(client)
    incomplete = {current["targets"][0]["name"]: None}
    response = save(client, current, incomplete)
    assert response.status_code == 400
    assert "كل الأهداف" in response.get_json()["error"]


def test_past_day_is_read_only(client, frozen_today):
    frozen_today("2026-04-11")
    payload = snapshot(client, "2026-04-10")
    response = save(client, payload, blank_assignments(payload), "2026-04-10")
    assert response.status_code == 409
    assert "عرضه فقط" in response.get_json()["error"]
