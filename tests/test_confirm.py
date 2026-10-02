"""تأكيد اليومية التفصيلية — الحفظ بيكتب، والتأكيد بيعتمد ويسجّل.

المطلوب اللي البند ده اتعمل عشانه: سطر مقروء في السجل يقول الضابط كان على
إيه وبقى على إيه، بوقت التأكيد — مش خمس سطور حفظ متتالية بأوقات متفرقة.
"""
DAY = "2026-04-10"


def _add(client, name, day=DAY, **over):
    body = {"name": name, "kind": "خارجية", "section": "الخدمات أساسية", **over}
    return client.post(f"/api/assignments/{day}", json=body).get_json()


def _confirm(client, day=DAY, **kw):
    return client.post(f"/api/board/{day}/confirm", json=kw)


def _entries(client, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get(f"/api/changes{'?' + q if q else ''}").get_json()["entries"]


def _texts(client, **params):
    return [e["text"] for e in _entries(client, **params)]


def test_a_day_with_no_confirmation_yet_is_marked_pending(client):
    _add(client, "تدخل سريع")
    state = client.get(f"/api/board/{DAY}/confirm").get_json()
    assert state["confirmed"] is False and state["pending"] is True


def test_the_first_confirmation_does_not_spam_a_line_per_service(client):
    """أول تأكيد مالوش خط أساس يتقارن بيه — تسجيل كل خدمة موجودة كـ«جديدة»
    ضوضاء مش معلومة."""
    _add(client, "تدخل سريع")
    _add(client, "أمن المعسكر")
    body = _confirm(client).get_json()
    assert body["first"] is True and body["count"] == 2
    assert _entries(client, entity="assignment") == []
    assert len(_entries(client, entity="day_confirm")) == 1


def test_after_confirming_the_day_is_no_longer_pending(client):
    _add(client, "تدخل سريع")
    _confirm(client)
    state = client.get(f"/api/board/{DAY}/confirm").get_json()
    assert state["confirmed"] is True and state["pending"] is False


def test_saving_after_a_confirmation_marks_the_day_pending_again(client):
    _add(client, "تدخل سريع")
    _confirm(client)
    _add(client, "خدمة زيادة")
    assert client.get(f"/api/board/{DAY}/confirm").get_json()["pending"] is True


def test_moving_an_officer_between_services_reads_as_one_sentence(client):
    """ده بالظبط الشكل المطلوب: «كان كذا ← بقى كذا» لصف واحد في الصفحة."""
    old = _add(client, "تدخل سريع", shift="ليلية", officer_ids=["OFF-002"])
    new = _add(client, "أمن المعسكر", shift="ليلية")
    _confirm(client)

    client.patch(f"/api/assignments/{DAY}/{old['id']}", json={"officer_ids": []})
    client.patch(f"/api/assignments/{DAY}/{new['id']}", json={"officer_ids": ["OFF-002"]})
    _confirm(client)

    moves = _entries(client, entity="duty_move", entity_id="OFF-002")
    assert len(moves) == 1
    assert moves[0]["action"] == "update"
    assert moves[0]["text"] == "نقيب/ محمود علي: كان «تدخل سريع ليل» ← أصبح «أمن المعسكر ليل»"


def test_putting_an_officer_on_a_service_for_the_first_time_reads_as_assignment(client):
    row = _add(client, "تدخل سريع", shift="صباحية")
    _confirm(client)
    client.patch(f"/api/assignments/{DAY}/{row['id']}", json={"officer_ids": ["OFF-001"]})
    _confirm(client)

    move = _entries(client, entity="duty_move", entity_id="OFF-001")[0]
    assert move["action"] == "assign"
    assert move["text"] == "عقيد/ أحمد محمد: كُلِّف بـ«تدخل سريع صبح»"


def test_taking_an_officer_off_every_service_reads_as_removal(client):
    row = _add(client, "تدخل سريع", shift="صباحية", officer_ids=["OFF-001"])
    _confirm(client)
    client.patch(f"/api/assignments/{DAY}/{row['id']}", json={"officer_ids": []})
    _confirm(client)

    move = _entries(client, entity="duty_move", entity_id="OFF-001")[0]
    assert move["action"] == "unassign"
    assert "أُزيل من «تدخل سريع صبح»" in move["text"]


def test_a_field_change_on_a_service_is_described_in_arabic(client):
    row = _add(client, "تدخل سريع")
    _confirm(client)
    client.patch(f"/api/assignments/{DAY}/{row['id']}", json={"weapon": "آلي", "party": "فيصل"})
    _confirm(client)

    text = _entries(client, entity="assignment", entity_id=row["id"])[0]["text"]
    assert "التسليح: «—» ← «آلي»" in text
    assert "الجهة: «—» ← «فيصل»" in text


def test_every_change_in_one_confirmation_carries_the_same_timestamp(client):
    """الوقت المعروض هو لحظة التأكيد — مش لحظة كل حفظ على حدة."""
    a = _add(client, "خدمة أ", officer_ids=["OFF-001"])
    _add(client, "خدمة ب")
    _confirm(client)

    client.patch(f"/api/assignments/{DAY}/{a['id']}", json={"weapon": "آلي", "officer_ids": []})
    _add(client, "خدمة ج")
    body = _confirm(client).get_json()

    stamps = {e["ts"] for e in _entries(client, day=DAY)}
    assert stamps == {body["at"]}


def test_confirming_twice_with_no_edits_is_allowed_and_logged(client):
    """التأكيد ممكن يتعمل أكتر من مرة عادي — وإنه اتعمل معلومة تشغيلية
    في حد ذاتها (حد راجع اليومية الساعة دي)."""
    _add(client, "تدخل سريع")
    _confirm(client)
    body = _confirm(client).get_json()
    assert body["changes"] == 0

    texts = _texts(client, entity="day_confirm")
    assert any("إعادة تأكيد" in t for t in texts)


def test_a_confirmation_only_reports_changes_since_the_previous_one(client):
    row = _add(client, "تدخل سريع")
    _confirm(client)
    client.patch(f"/api/assignments/{DAY}/{row['id']}", json={"name": "اسم تاني"})
    _confirm(client)
    body = _confirm(client).get_json()           # تالت تأكيد، من غير أي تعديل
    assert body["changes"] == 0


def test_the_confirmed_snapshot_is_capped_so_the_file_does_not_grow_forever(client, monkeypatch):
    from backend import confirm, store
    monkeypatch.setattr(confirm, "MAX_SNAPSHOT_DAYS", 2)
    for day in ("2026-04-10", "2026-04-11", "2026-04-12"):
        _add(client, "خدمة", day=day)
        _confirm(client, day=day)

    kept = sorted(store.load_data()["day_confirm"])
    assert kept == ["2026-04-11", "2026-04-12"]


def test_the_board_carries_the_confirmation_state_so_the_page_needs_one_call(client):
    _add(client, "تدخل سريع")
    board = client.get(f"/api/board/{DAY}").get_json()
    assert board["confirm"]["pending"] is True


def test_bulk_confirmation_lists_and_confirms_every_pending_roster(client):
    days = ("2026-04-10", "2026-04-11")
    for day in days:
        _add(client, "خدمة", day=day)

    pending = client.get("/api/board/unconfirmed").get_json()
    assert pending["count"] == 2
    assert [row["day"] for row in pending["days"]] == list(days)

    result = client.post("/api/board/confirm-unconfirmed", json={
        "days": list(days), "confirmed_by": "المراجع",
    }).get_json()
    assert result["count"] == 2
    assert client.get("/api/board/unconfirmed").get_json()["count"] == 0
    for day in days:
        state = client.get(f"/api/board/{day}/confirm").get_json()
        assert state["confirmed"] is True and state["by"] == "المراجع"


def test_bulk_confirmation_rejects_a_non_list_day_selection(client):
    response = client.post("/api/board/confirm-unconfirmed", json={"days": DAY})
    assert response.status_code == 400
