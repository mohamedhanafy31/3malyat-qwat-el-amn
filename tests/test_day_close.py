"""إغلاق اليوم — اليوم بيقفل لوحده الساعة ١٢ بالليل، والمقفول يرفض أي تعديل.

«النهاردة» مثبّت على 2019-01-01 من conftest، فـDAY و OTHER_DAY أيام جاية
(مفتوحة)، والأيام اللي قبل التثبيت بتختبر القفل التلقائي.
"""
DAY = "2026-04-10"
OTHER_DAY = "2026-04-11"
PAST_DAY = "2018-12-31"        # اليوم اللي قبل «النهاردة» المثبّت


def test_day_starts_open(client):
    s = client.get(f"/api/day-status/{DAY}").get_json()
    assert s["closed"] is False


def test_a_day_that_already_passed_is_closed_without_anyone_closing_it(client):
    """القفل التلقائي: مفيش مجدول ولا حالة متخزّنة — اليوم فات يبقى مقفول."""
    s = client.get(f"/api/day-status/{PAST_DAY}").get_json()
    assert s["closed"] is True and s["auto"] is True


def test_the_automatic_close_blocks_edits_like_a_manual_one(client):
    r = client.post(f"/api/assignments/{PAST_DAY}", json={"name": "خدمة", "kind": "خارجية"})
    assert r.status_code == 409
    assert "تلقائيًا الساعة 12" in r.get_json()["error"]


def test_today_is_still_open_at_the_end_of_its_own_day(client, frozen_today):
    """اليوم الحالي مايتقفلش غير في منتصف الليل اللي بعده، مش في نصّه."""
    frozen_today(DAY)
    assert client.get(f"/api/day-status/{DAY}").get_json()["closed"] is False


def test_a_future_day_stays_open_for_advance_planning(client, frozen_today):
    frozen_today(DAY)
    assert client.get(f"/api/day-status/{OTHER_DAY}").get_json()["closed"] is False


def test_stage_distinguishes_not_yet_open_from_open_from_closed(client, frozen_today):
    """الحالة الثلاثية: يوم جاي «لسة متفتحش»، النهاردة «مفتوح»، يوم فات
    «مغلق» — تصنيف عرض بس، مايأثرش على `check_open`."""
    frozen_today(DAY)
    assert client.get(f"/api/day-status/{OTHER_DAY}").get_json()["stage"] == "not_open"
    assert client.get(f"/api/day-status/{DAY}").get_json()["stage"] == "open"
    assert client.get(f"/api/day-status/{PAST_DAY}").get_json()["stage"] == "closed"


def test_manually_closing_a_future_day_reports_closed_stage_not_not_open(client, frozen_today):
    frozen_today(DAY)
    client.post(f"/api/day-status/{OTHER_DAY}/close", json={})
    assert client.get(f"/api/day-status/{OTHER_DAY}").get_json()["stage"] == "closed"


def test_closing_a_day_records_who_and_when(client):
    r = client.post(f"/api/day-status/{DAY}/close", json={"closed_by": "أحمد"})
    assert r.status_code == 201
    body = r.get_json()
    assert body["closed"] is True and body["closed_by"] == "أحمد" and body["closed_at"]

    s = client.get(f"/api/day-status/{DAY}").get_json()
    assert s["closed"] is True and s["auto"] is False


def test_closing_an_already_closed_day_409s(client):
    client.post(f"/api/day-status/{DAY}/close", json={})
    assert client.post(f"/api/day-status/{DAY}/close", json={}).status_code == 409


def test_closing_one_day_does_not_affect_another(client):
    client.post(f"/api/day-status/{DAY}/close", json={})
    s = client.get(f"/api/day-status/{OTHER_DAY}").get_json()
    assert s["closed"] is False


def test_adding_an_assignment_on_a_closed_day_is_blocked(client):
    client.post(f"/api/day-status/{DAY}/close", json={})
    r = client.post(f"/api/assignments/{DAY}", json={"name": "خدمة", "kind": "خارجية"})
    assert r.status_code == 409


def test_editing_an_assignment_on_a_closed_day_is_blocked(client):
    entry = client.post(f"/api/assignments/{DAY}",
                        json={"name": "خدمة", "kind": "خارجية"}).get_json()
    client.post(f"/api/day-status/{DAY}/close", json={})
    r = client.patch(f"/api/assignments/{DAY}/{entry['id']}", json={"name": "اسم جديد"})
    assert r.status_code == 409


def test_deleting_an_assignment_on_a_closed_day_is_blocked(client):
    entry = client.post(f"/api/assignments/{DAY}",
                        json={"name": "خدمة", "kind": "خارجية"}).get_json()
    client.post(f"/api/day-status/{DAY}/close", json={})
    assert client.delete(f"/api/assignments/{DAY}/{entry['id']}").status_code == 409


def test_clearing_the_whole_day_is_blocked_when_closed(client):
    client.post(f"/api/assignments/{DAY}", json={"name": "خدمة", "kind": "خارجية"})
    client.post(f"/api/day-status/{DAY}/close", json={})
    assert client.delete(f"/api/assignments/{DAY}").status_code == 409


def test_confirming_a_closed_day_is_blocked(client):
    client.post(f"/api/day-status/{DAY}/close", json={})
    assert client.post(f"/api/board/{DAY}/confirm", json={}).status_code == 409


def test_setting_officer_state_on_a_closed_day_is_blocked(client):
    client.post(f"/api/day-status/{DAY}/close", json={})
    r = client.put(f"/api/duty/{DAY}/OFF-001", json={"taqseera": True})
    assert r.status_code == 409


def test_clearing_officer_state_on_a_closed_day_is_blocked(client):
    client.put(f"/api/duty/{DAY}/OFF-001", json={"taqseera": True})
    client.post(f"/api/day-status/{DAY}/close", json={})
    assert client.delete(f"/api/duty/{DAY}/OFF-001").status_code == 409


def test_reopen_requires_a_reason(client):
    client.post(f"/api/day-status/{DAY}/close", json={})
    assert client.post(f"/api/day-status/{DAY}/reopen", json={}).status_code == 400


def test_reopening_an_open_day_409s(client):
    assert client.post(f"/api/day-status/{DAY}/reopen", json={"reason": "س"}).status_code == 409


def test_reopen_unblocks_edits_again(client):
    client.post(f"/api/day-status/{DAY}/close", json={})
    r = client.post(f"/api/day-status/{DAY}/reopen", json={"reason": "غلط في القفل"})
    assert r.status_code == 200
    assert r.get_json()["closed"] is False

    assert client.post(f"/api/assignments/{DAY}",
                       json={"name": "خدمة", "kind": "خارجية"}).status_code == 201


def test_reopen_works_on_an_automatically_closed_day_too(client):
    r = client.post(f"/api/day-status/{PAST_DAY}/reopen", json={"reason": "تصحيح أرشيف"})
    assert r.status_code == 200
    assert client.post(f"/api/assignments/{PAST_DAY}",
                       json={"name": "خدمة", "kind": "خارجية"}).status_code == 201


def test_an_exceptional_reopen_expires_at_the_next_midnight(client, frozen_today):
    """الفتح الاستثنائي مش فتح دائم — لو فضل صالح كان القفل التلقائي مالوش
    أي معنى بعد أول مرة حد يفتح فيها يوم قديم."""
    client.post(f"/api/day-status/{PAST_DAY}/reopen", json={"reason": "تصحيح أرشيف"})
    assert client.get(f"/api/day-status/{PAST_DAY}").get_json()["closed"] is False

    frozen_today("2019-01-02")           # عدّى منتصف الليل
    assert client.get(f"/api/day-status/{PAST_DAY}").get_json()["closed"] is True


def test_close_and_reopen_are_recorded_in_the_change_log(client):
    client.post(f"/api/day-status/{DAY}/close", json={"closed_by": "أحمد"})
    client.post(f"/api/day-status/{DAY}/reopen", json={"reason": "غلط في القفل"})

    entries = client.get(f"/api/changes?entity=day_lock&entity_id={DAY}").get_json()["entries"]
    actions = [e["action"] for e in entries]
    assert actions == ["reopen", "close"]
    assert entries[0]["reason"] == "غلط في القفل"
