"""ترتيب عرض خدمات اليومية من غير تغيير ترتيبها التشغيلي المخزّن."""

DAY = "2026-04-10"


def _add(client, name, section="الخدمات الطارئة", **over):
    payload = {"name": name, "kind": "خارجية", "section": section, **over}
    response = client.post(f"/api/assignments/{DAY}", json=payload)
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def _move(client, row_id, direction):
    return client.post(f"/api/assignments/{DAY}/{row_id}/move",
                       json={"direction": direction})


def _section(board, name):
    return next(section for section in board["sections"] if section["name"] == name)


def _names(rows):
    return [row["name"] for row in rows]


def test_move_swaps_display_order_in_its_section_only_and_keeps_storage_order(client):
    first = _add(client, "طارئة أ")
    second = _add(client, "طارئة ب")
    _add(client, "طارئة ج")
    _add(client, "أساسية أ", "الخدمات أساسية")
    _add(client, "أساسية ب", "الخدمات أساسية")

    response = _move(client, second["id"], "up")
    assert response.status_code == 200, response.get_json()
    board = response.get_json()
    assert _names(_section(board, "الخدمات الطارئة")["rows"]) == [
        "طارئة ب", "طارئة أ", "طارئة ج"]
    assert _names(_section(board, "الخدمات أساسية")["rows"]) == ["أساسية أ", "أساسية ب"]

    # النقل للعرض فقط؛ أول خدمة اتحط عليها الضابط تعتمد على الترتيب ده.
    stored = client.get(f"/api/assignments/{DAY}").get_json()["assignments"]
    assert [row["id"] for row in stored[:2]] == [first["id"], second["id"]]


def test_move_at_the_edge_is_a_no_op(client):
    first = _add(client, "الأولى")
    _add(client, "الثانية")
    before = client.get(f"/api/assignments/{DAY}").get_json()["assignments"]

    response = _move(client, first["id"], "up")
    assert response.status_code == 200
    assert _names(_section(response.get_json(), "الخدمات الطارئة")["rows"]) == [
        "الأولى", "الثانية"]
    after = client.get(f"/api/assignments/{DAY}").get_json()["assignments"]
    assert after == before


def test_extra_rows_in_a_fixed_slot_section_can_be_reordered(client):
    section_name = "ضابط عظيم الإدارة"
    first = _add(client, "دور إضافي صباحي", section_name, kind="داخلية", shift="صباحية")
    second = _add(client, "دور إضافي ليلي", section_name, kind="داخلية", shift="ليلية")

    response = _move(client, second["id"], "up")
    assert response.status_code == 200
    section = _section(response.get_json(), section_name)
    extras = [row for row in section["rows"] if not row["slot"]]
    assert [row["id"] for row in extras] == [second["id"], first["id"]]
    assert [row["shift"] for row in section["rows"] if row["slot"]] == ["صباحية", "ليلية"]


def test_move_refuses_closed_day(client):
    row = _add(client, "خدمة")
    assert client.post(f"/api/day-status/{DAY}/close", json={}).status_code == 201
    assert _move(client, row["id"], "down").status_code == 409


def test_move_reports_unknown_id(client):
    response = _move(client, "AS-9999", "up")
    assert response.status_code == 404


def test_move_rejects_bad_direction(client):
    row = _add(client, "خدمة")
    assert _move(client, row["id"], "sideways").status_code == 400


def test_move_does_not_change_the_officers_first_stored_service(client):
    first = _add(client, "خارجية أولى", kind="خارجية", shift="صباحية",
                 officer_ids=["OFF-002"])
    second = _add(client, "داخلية ثانية", kind="داخلية", shift="ليلية",
                  officer_ids=["OFF-002"])
    before = client.get(f"/api/duty/{DAY}").get_json()
    before_row = next(row for row in before["rows"] if row["id"] == "OFF-002")
    assert (before_row["group"], before_row["bucket"]) == ("خارجية", "صباحية")

    assert _move(client, second["id"], "up").status_code == 200
    after = client.get(f"/api/duty/{DAY}").get_json()
    after_row = next(row for row in after["rows"] if row["id"] == "OFF-002")
    assert after["summary"] == before["summary"]
    assert [item["assignment_id"] for item in after_row["services"]] == [first["id"], second["id"]]
    assert (after_row["group"], after_row["bucket"]) == ("خارجية", "صباحية")


def test_move_alone_does_not_make_a_confirmed_day_pending(client):
    _add(client, "الأولى")
    second = _add(client, "الثانية")
    assert client.post(f"/api/board/{DAY}/confirm", json={}).status_code == 201

    assert _move(client, second["id"], "up").status_code == 200
    state = client.get(f"/api/board/{DAY}/confirm").get_json()
    assert state["confirmed"] is True and state["pending"] is False
    repeated = client.post(f"/api/board/{DAY}/confirm", json={}).get_json()
    assert repeated["changes"] == 0


def test_add_with_after_id_places_the_copy_immediately_after_its_source(client):
    source = _add(client, "الأصل")
    following = _add(client, "الخدمة التالية")
    copy = _add(client, "نسخة الأصل", after_id=source["id"])

    board = client.get(f"/api/board/{DAY}").get_json()
    rows = _section(board, "الخدمات الطارئة")["rows"]
    assert [row["id"] for row in rows] == [source["id"], copy["id"], following["id"]]


def test_after_id_from_another_section_is_ignored(client):
    first = _add(client, "طارئة أولى")
    second = _add(client, "طارئة ثانية")
    other_section = _add(client, "أساسية", "الخدمات أساسية")
    added = _add(client, "طارئة جديدة", after_id=other_section["id"])

    board = client.get(f"/api/board/{DAY}").get_json()
    rows = _section(board, "الخدمات الطارئة")["rows"]
    assert [row["id"] for row in rows] == [first["id"], second["id"], added["id"]]


def test_placing_after_source_does_not_change_stored_assignment_order(client):
    source = _add(client, "الأصل")
    following = _add(client, "التالي")
    copy = _add(client, "النسخة", after_id=source["id"])

    stored = client.get(f"/api/assignments/{DAY}").get_json()["assignments"]
    assert [row["id"] for row in stored] == [source["id"], following["id"], copy["id"]]
