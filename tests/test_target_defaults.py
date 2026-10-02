"""ضباط الأهداف المبدئيون من آخر تأكيد لليوم السابق."""
import json

from backend import store


SOURCE = "2026-04-13"
DAY = "2026-04-14"


def _set_target(client, day, name, officer_ids):
    response = client.put(
        f"/api/board/{day}/target/{name}", json={"officer_ids": officer_ids})
    assert response.status_code == 200, response.get_json()


def _confirm(client, day):
    response = client.post(f"/api/board/{day}/confirm", json={})
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def _target_section(payload):
    return next(section for section in payload["sections"]
                if section["name"] == "الأهداف")


def _assigned(payload, name):
    section = _target_section(payload)
    row = next(row for row in section["rows"] if row["name"] == name)
    return [officer["id"] for officer in row["officers"]]


def _saved(data_file):
    return json.loads(data_file.read_text(encoding="utf-8"))


def _add_raw_officers(data_file, rows):
    data = _saved(data_file)
    data["officers"].extend(rows)
    data_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _officer(officer_id, name, **overrides):
    return {
        "id": officer_id, "name": name, "role": "ملازم", "code": officer_id,
        "phone": "", "join_date": "2020-01-01", "leave_date": "",
        "post": "", "status": "active", "rest_system": "—", "rest_day": "",
        **overrides,
    }


def test_opening_uses_the_latest_confirmed_targets_only(client, data_file):
    _set_target(client, SOURCE, "سوميد", ["OFF-002"])
    first = _confirm(client, SOURCE)

    # تعديل غير مؤكد لا يدخل اليوم التالي؛ المصدر هو اللقطة المعتمدة لا
    # مسودة اليوم السابق الحالية.
    _set_target(client, SOURCE, "سوميد", ["OFF-001"])
    client.post(f"/api/assignments/{SOURCE}", json={
        "name": "خدمة لا تنسخ", "kind": "خارجية", "officer_ids": ["OFF-002"],
    })

    board = client.get(f"/api/board/{DAY}").get_json()
    assert _assigned(board, "سوميد") == ["OFF-002"]
    assert _target_section(board)["seeded_from"] == SOURCE

    client.post(f"/api/assignments/{DAY}", json={"name": "أول تعديل", "kind": "خارجية"})

    saved = _saved(data_file)
    marker = saved["target_defaults"][DAY]
    assert marker["source_day"] == SOURCE
    assert marker["confirmed_at"] == first["at"]
    assert marker["targets"]["سوميد"] == ["OFF-002"]
    assert not any(row.get("name") == "خدمة لا تنسخ"
                   for row in saved.get("day_assignments", {}).get(DAY, []))
    day_blob = json.loads(store.day_path(DAY).read_text(encoding="utf-8"))
    assert "target_defaults" in day_blob
    assert "target_defaults" not in json.loads(
        store.core_file().read_text(encoding="utf-8"))


def test_rejected_ids_in_an_old_snapshot_leave_only_that_target_vacant(
        client, data_file):
    _set_target(client, SOURCE, "سوميد", ["OFF-001"])
    _set_target(client, SOURCE, "عيون موسي", ["OFF-002"])
    _confirm(client, SOURCE)

    # بيانات قديمة تالفة فيها نفس المعرّف لضابط وفرد: فلتر القوة يراه
    # ضابطًا، لكن فهرس الأشخاص يحلّه للفرد فيرفضه تحقق الحفظ. ده يجبر
    # مسار `(row, error, status)` الحقيقي من خلال طلب GET عادي.
    data = _saved(data_file)
    data["officers"].append(_officer("DUP-001", "سجل ضابط قديم"))
    data["personnel"].append({
        "id": "DUP-001", "name": "سجل فرد بنفس المعرّف", "role": "فرد",
        "code": "DUP-001", "phone": "", "join_date": "2020-01-01",
        "leave_date": "", "status": "active",
    })
    snapshot = data["day_confirm"][SOURCE]["rows"]
    sumed = next(row for row in snapshot if row.get("name") == "سوميد")
    sumed["officer_ids"] = ["DUP-001"]
    data_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    response = client.get(f"/api/board/{DAY}")
    assert response.status_code == 200
    board = response.get_json()
    assert _assigned(board, "سوميد") == []
    assert _assigned(board, "عيون موسي") == ["OFF-002"]
    client.post(f"/api/assignments/{DAY}", json={"name": "أول تعديل", "kind": "خارجية"})
    assert _saved(data_file)["target_defaults"][DAY]["targets"]["سوميد"] == []


def test_ineligible_officers_are_dropped_after_weekly_rest_is_registered(
        client, data_file):
    source = "2026-04-10"       # الجمعة
    day = "2026-04-11"          # السبت — يوم راحة OFF-001
    _add_raw_officers(data_file, [
        _officer("OFF-003", "باقي في الهدف"),
        _officer("OFF-004", "خرج من القوة", leave_date=source, status="archived"),
        _officer("OFF-005", "ضابط العيادة"),
        _officer("OFF-006", "في إجازة"),
        _officer("OFF-007", "غياب مكتوب"),
    ])
    ids = ["OFF-001", "OFF-003", "OFF-004", "OFF-005", "OFF-006", "OFF-007"]
    _set_target(client, source, "سوميد", ids)
    assert client.patch("/api/command-groups", json={"طبي": ["OFF-005"]}).status_code == 200
    assert client.post("/api/leaves", json={
        "person_id": "OFF-006", "type": "إجازة طارئة", "start": day, "end": day,
    }).status_code == 201
    # فتح يومية الضباط يشغّل نفس تجهيز اليوم ويسجّل الراحة الأسبوعية أولًا.
    assert client.get(f"/api/duty/{day}").status_code == 200
    assert client.put(f"/api/duty/{day}/OFF-007", json={"status": "غياب"}).status_code == 200

    _confirm(client, source)     # اليوم التالي موجود، فيتبذر فور التأكيد
    board = client.get(f"/api/board/{day}").get_json()
    assert _assigned(board, "سوميد") == ["OFF-003"]

    saved = _saved(data_file)
    assert any(leave.get("person_id") == "OFF-001"
               and leave.get("start") == day
               and leave.get("origin") == "auto_weekly"
               for leave in saved["leaves"])
    assert saved["target_defaults"][day]["targets"]["سوميد"] == ["OFF-003"]


def test_no_confirmation_writes_nothing_and_a_later_open_retries(client, data_file):
    _set_target(client, SOURCE, "سوميد", ["OFF-002"])

    first = client.get(f"/api/board/{DAY}").get_json()
    assert _assigned(first, "سوميد") == []
    assert "seeded_from" not in _target_section(first)
    assert DAY not in _saved(data_file).get("target_defaults", {})

    _confirm(client, SOURCE)
    retried = client.get(f"/api/board/{DAY}").get_json()
    assert _assigned(retried, "سوميد") == ["OFF-002"]
    assert _target_section(retried)["seeded_from"] == SOURCE


def test_reconfirmation_updates_untouched_defaults_but_never_modified_ones(
        client, data_file):
    _set_target(client, SOURCE, "سوميد", ["OFF-001"])
    _confirm(client, SOURCE)
    assert _assigned(client.get(f"/api/board/{DAY}").get_json(), "سوميد") == ["OFF-001"]

    _set_target(client, SOURCE, "سوميد", ["OFF-002"])
    second = _confirm(client, SOURCE)
    board = client.get(f"/api/board/{DAY}").get_json()
    assert _assigned(board, "سوميد") == ["OFF-002"]
    client.post(f"/api/assignments/{DAY}", json={"name": "أول تعديل", "kind": "خارجية"})
    assert _saved(data_file)["target_defaults"][DAY]["confirmed_at"] == second["at"]

    _set_target(client, DAY, "سوميد", ["OFF-001"])
    assert "seeded_from" not in _target_section(
        client.get(f"/api/board/{DAY}").get_json())
    _set_target(client, SOURCE, "سوميد", ["OFF-001", "OFF-002"])
    _confirm(client, SOURCE)

    board = client.get(f"/api/board/{DAY}").get_json()
    assert _assigned(board, "سوميد") == ["OFF-001"]
    assert _saved(data_file)["target_defaults"][DAY]["modified"] is True


def test_confirm_seeds_an_existing_empty_next_day(client):
    _set_target(client, SOURCE, "سوميد", ["OFF-002"])
    # حالة يومية تجعل اليوم التالي موجودًا من غير أي صف هدف أو علامة بذر.
    assert client.put(f"/api/duty/{DAY}/OFF-001", json={"note": "مراجعة"}).status_code == 200

    _confirm(client, SOURCE)
    assert _assigned(client.get(f"/api/board/{DAY}").get_json(), "سوميد") == ["OFF-002"]


def test_confirm_registers_existing_next_days_weekly_rest_before_seeding(client):
    source = "2026-04-10"
    day = "2026-04-11"
    _set_target(client, source, "سوميد", ["OFF-001"])
    # اليوم موجود بحالة محفوظة، لكن GET التجهيز لم يحصل بعد.
    assert client.put(f"/api/duty/{day}/OFF-002", json={"note": "مراجعة"}).status_code == 200

    _confirm(client, source)
    board = client.get(f"/api/board/{day}").get_json()
    assert _assigned(board, "سوميد") == []
    assert _target_section(board)["seeded_from"] == source


def test_closed_next_day_is_never_seeded_or_refreshed(client, data_file):
    _set_target(client, SOURCE, "سوميد", ["OFF-002"])
    assert client.post(f"/api/day-status/{DAY}/close", json={}).status_code == 201
    _confirm(client, SOURCE)

    board = client.get(f"/api/board/{DAY}").get_json()
    assert _assigned(board, "سوميد") == []
    assert DAY not in _saved(data_file).get("target_defaults", {})


def test_seeded_get_fast_path_does_not_write_again(client):
    _set_target(client, SOURCE, "سوميد", ["OFF-002"])
    _confirm(client, SOURCE)
    client.get(f"/api/board/{DAY}")
    before = {path: path.stat().st_mtime_ns for path in store.DATA_DIR.rglob("*.json")}

    board = client.get(f"/api/board/{DAY}").get_json()
    assert _target_section(board)["seeded_from"] == SOURCE
    assert {path: path.stat().st_mtime_ns for path in store.DATA_DIR.rglob("*.json")} == before
