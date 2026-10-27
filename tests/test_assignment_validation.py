"""حدود حقول خانة اليومية، وتأكيد الخانة الشاغرة المكررة.

القيمة الغلط بترجع 400 صريح بدل ما تتقص أو تتحوّل صفر بصمت.
"""
import pytest

DAY = "2026-04-10"


def _body(**over):
    body = {"name": "دورية خارجية", "kind": "خارجية", "section": "الخدمات أساسية",
            "shift": "صباحية"}
    body.update(over)
    return body


def _post(client, day=DAY, **over):
    return client.post(f"/api/assignments/{day}", json=_body(**over))


def _rows(client, day=DAY):
    return client.get(f"/api/assignments/{day}").get_json()["assignments"]


@pytest.mark.parametrize("field,limit", [
    ("name", 120), ("section", 60), ("weapon", 120),
    ("party", 120), ("note", 500),
])
def test_text_fields_are_capped_on_create_and_edit(client, field, limit):
    ok = _post(client, **{field: "س" * limit, "name": "خدمة حد" if field != "name" else "س" * limit})
    assert ok.status_code == 201, ok.get_json()

    r = _post(client, **{field: "س" * (limit + 1)})
    assert r.status_code == 400
    assert str(limit) in r.get_json()["error"]

    row_id = ok.get_json()["id"]
    r = client.patch(f"/api/assignments/{DAY}/{row_id}", json={field: "س" * (limit + 1)})
    assert r.status_code == 400
    stored = next(x for x in _rows(client) if x["id"] == row_id)
    assert len(stored[field]) == limit, "التعديل المرفوض ما يلمسش الخانة"


@pytest.mark.parametrize("value", [-1, 10000, "abc", "1.5", 2.5, True, [], {}])
def test_bad_conscript_count_is_rejected_not_zeroed(client, value):
    r = _post(client, conscript_count=value)
    assert r.status_code == 400, value
    assert _rows(client) == []


@pytest.mark.parametrize("value", [-3, 10000, "x", True])
def test_bad_count_inside_conscript_classes_is_rejected(client, value):
    r = _post(client, conscripts=[{"class": "قتالية", "count": value}])
    assert r.status_code == 400, value


def test_conscripts_must_be_a_list(client):
    r = _post(client, conscripts="قتالية")
    assert r.status_code == 400


def test_valid_counts_are_stored_including_the_bounds(client):
    r = _post(client, conscript_count=9999,
              conscripts=[{"class": "قتالية", "count": 0}, {"class": "فض", "count": "12"}])
    assert r.status_code == 201, r.get_json()
    row = r.get_json()
    assert row["conscript_count"] == 9999
    assert row["conscripts"] == [{"class": "قتالية", "count": 0}, {"class": "فض", "count": 12}]

    r = client.patch(f"/api/assignments/{DAY}/{row['id']}", json={"conscript_count": ""})
    assert r.status_code == 200 and r.get_json()["conscript_count"] == 0, "الفاضي = صفر"


@pytest.mark.parametrize("field", ["officer_ids", "personnel_ids"])
@pytest.mark.parametrize("value", ["OFF-001", 7, {"id": "OFF-001"}])
def test_people_ids_must_be_a_list(client, field, value):
    """نص زي "OFF-001" كان بيتلف عليه حرف حرف — «O» و«F»... كل حرف
    كأنه id، والنتيجة رسالة «ضابط غير موجود» مضللة أو 500."""
    r = _post(client, **{field: value})
    assert r.status_code == 400
    assert _rows(client) == []


def test_clean_people_rejects_a_string_instead_of_iterating_it(client):
    from backend import assignments
    from backend.store import load_data

    ids, err, status = assignments.clean_people(load_data(), DAY, "OFF-001", "officers")
    assert ids is None and status == 400 and err


def test_command_role_can_be_saved_vacant_then_assigned_and_removed(client):
    created = _post(client, officer_ids=[], personnel_ids=[],
                    officer_command_required=True, personnel_command_required=True)
    assert created.status_code == 201, created.get_json()
    row = created.get_json()
    assert row["officer_command_required"] is True
    assert row["personnel_command_required"] is True
    assert row["officer_ids"] == [] and row["personnel_ids"] == []

    board_rows = [r for section in client.get(f"/api/board/{DAY}").get_json()["sections"]
                  for r in section["rows"]]
    shown = next(r for r in board_rows if r.get("id") == row["id"])
    assert shown["officer_command_vacant"] is True
    assert shown["personnel_command_vacant"] is True
    confirmed = client.post(f"/api/board/{DAY}/confirm", json={})
    assert confirmed.status_code == 201, confirmed.get_json()

    assigned = client.patch(f"/api/assignments/{DAY}/{row['id']}", json={
        "officer_ids": ["OFF-001"], "officer_command_required": True})
    assert assigned.status_code == 200
    assert assigned.get_json()["officer_ids"] == ["OFF-001"]

    removed = client.patch(f"/api/assignments/{DAY}/{row['id']}", json={
        "officer_command_required": False})
    assert removed.status_code == 200
    assert removed.get_json()["officer_command_required"] is False
    assert removed.get_json()["officer_ids"] == []


@pytest.mark.parametrize("field", ["officer_command_required", "personnel_command_required"])
def test_command_role_flag_must_be_boolean(client, field):
    r = _post(client, **{field: "true"})
    assert r.status_code == 400
    assert _rows(client) == []


def test_section_copy_keeps_vacant_command_role_without_copying_people(client):
    source_day, target_day = "2026-04-09", "2026-04-10"
    source = _post(client, day=source_day, section="قسم تجريبي",
                   officer_ids=["OFF-001"], officer_command_required=True).get_json()
    response = client.post(f"/api/board/{target_day}/section-copy", json={
        "section": "قسم تجريبي", "source_day": source_day, "ids": [source["id"]],
    })
    assert response.status_code == 201, response.get_json()
    copied = response.get_json()["rows"][0]
    assert copied["officer_ids"] == []
    assert copied["officer_command_required"] is True


# ---------- الخانة الشاغرة المكررة ----------

def test_identical_vacant_row_asks_for_confirmation(client):
    first = _post(client)
    assert first.status_code == 201

    r = _post(client, name="  دوريه   خارجيه ")          # نفس الاسم بعد التطبيع
    assert r.status_code == 409
    body = r.get_json()
    assert body["code"] == "possible_duplicate"
    assert body["existing_id"] == first.get_json()["id"]
    assert body["error"]
    assert len(_rows(client)) == 1


def test_allow_duplicate_keeps_an_intentional_twin(client):
    _post(client)
    r = _post(client, allow_duplicate=True)
    assert r.status_code == 201, r.get_json()
    assert len(_rows(client)) == 2


def test_only_a_literal_true_skips_the_check(client):
    _post(client)
    assert _post(client, allow_duplicate="true").status_code == 409


@pytest.mark.parametrize("over", [
    {"name": "دورية داخلية"},
    {"section": "قسم آخر"},
    {"kind": "داخلية"},
    {"shift": "ليلية"},
])
def test_rows_that_differ_in_any_key_are_not_duplicates(client, over):
    _post(client)
    r = _post(client, **over)
    assert r.status_code == 201, r.get_json()


def test_rows_with_people_are_not_vacant_duplicates(client):
    _post(client, officer_ids=["OFF-001"])
    assert _post(client).status_code == 201, "الموجودة مش شاغرة"
    assert _post(client, officer_ids=["OFF-002"]).status_code == 201, "الجديدة مش شاغرة"


def test_editing_a_row_is_never_blocked_as_a_duplicate(client):
    _post(client)
    other = _post(client, name="خدمة تانية").get_json()
    r = client.patch(f"/api/assignments/{DAY}/{other['id']}", json={"name": "دورية خارجية"})
    assert r.status_code == 200, r.get_json()


def test_same_row_on_another_day_is_not_a_duplicate(client):
    _post(client)
    assert _post(client, day="2026-04-11").status_code == 201
