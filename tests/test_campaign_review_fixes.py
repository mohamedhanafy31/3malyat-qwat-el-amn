"""مراجعة يومية الحملة بالمتصفح: التحذيرات، حدود الطول، وحراس لإصلاحات الواجهة."""
from pathlib import Path


def _vehicle(client, **extra):
    body = {"plate_series": "ب12", "plate_number": "4997", "type": "بيك اب"}
    body.update(extra)
    return client.post("/api/vehicles", json=body).get_json()


def _assignment(client, day, name):
    return client.post(f"/api/assignments/{day}", json={
        "name": name, "kind": "خارجية", "section": "الخدمات الطارئة"}).get_json()


def _campaign(client, day):
    response = client.get(f"/api/campaign/{day}")
    assert response.status_code == 200, response.get_json()
    return response.get_json()


ROOT = Path(__file__).resolve().parent.parent
DAY = "2026-07-10"
JS = (ROOT / "static" / "js" / "campaign.js").read_text(encoding="utf-8")
CORE = (ROOT / "static" / "js" / "core.js").read_text(encoding="utf-8")


# ------------------------------------------------------------- الباك إند

def test_post_and_lorry_with_the_same_name_are_told_apart_in_warnings(client):
    vehicle = _vehicle(client)
    lorry = _campaign(client, DAY)["lorries"][0]
    created = client.post(f"/api/campaign/{DAY}/posts", json={"name": lorry["base_name"]})   # نفس اسم اللوري
    assert created.status_code == 200
    post = next(p for p in created.get_json()["posts"] if p["name"] == lorry["base_name"])
    assert client.put(f"/api/campaign/{DAY}/post/{post['id']}", json={"vehicle_id": vehicle["id"]}).status_code == 200
    assert client.put(f"/api/campaign/{DAY}/lorry/{lorry['id']}", json={"vehicle_id": vehicle["id"]}).status_code == 200

    warnings = [w["text"] for w in _campaign(client, DAY)["warnings"]]

    assert f"المركبة مستخدمة أيضًا في: {post['name']} (ارتكاز)" in warnings    # تحذير اللوري بيسمّي الارتكاز بلاحقة
    assert f"المركبة مستخدمة أيضًا في: {lorry['base_name']}" in warnings      # وتحذير الارتكاز بيسمّي اللوري من غير لاحقة
    page_rows = [w["row"] for w in _campaign(client, DAY)["warnings"]]
    assert f"{post['name']} (ارتكاز)" in page_rows                          # وفي قايمة التنبيهات العامة كمان


def test_same_vehicle_twice_in_one_service_is_not_reported_as_used_in_itself(client):
    service = _assignment(client, DAY, "خدمة خطين")
    vehicle = _vehicle(client)
    out = client.put(f"/api/campaign/{DAY}/service/{service['id']}", json={
        "vehicles": [{"vehicle_id": vehicle["id"]}, {"vehicle_id": vehicle["id"]}]}).get_json()
    row = next(r for r in out["service_rows"] if r["id"] == service["id"])

    assert "المركبة مكررة داخل نفس الخدمة." in row["warnings"]
    assert not any("أيضًا في" in w and "خدمة خطين" in w for w in row["warnings"])


def test_post_creation_rejects_oversized_fields(client):
    for body in ({"name": "ا" * 201}, {"name": "ارتكاز", "number": "1" * 21},
                 {"name": "ارتكاز", "driver_text": "س" * 201}):
        response = client.post(f"/api/campaign/{DAY}/posts", json=body)
        assert response.status_code == 400, body
    assert client.post(f"/api/campaign/{DAY}/posts", json={"name": "ارتكاز سليم"}).status_code == 200


def test_free_text_driver_is_length_limited(client):
    service = _assignment(client, DAY, "خدمة سائق طويل")
    response = client.put(f"/api/campaign/{DAY}/service/{service['id']}", json={
        "driver": {"kind": "text", "name": "س" * 201}})
    assert response.status_code == 400 and "200" in response.get_json()["error"]


# ------------------------------------------------------------- حراس الواجهة

def test_combo_does_not_prefill_or_swallow_typing_when_a_modal_opens():
    """مودال الإلحاق: النص الافتراضي «اختر…» كان بيرجع جوّه الحقل بعد فتح القايمة فالكتابة بتتلزق عليه."""
    assert "if (_cbSel !== sel) _cbOpen(sel);" in CORE                     # النقر على قايمة مفتوحة مابيقفلهاش
    assert "if (_cbSel === sel && !sel.multiple) _cbRender(_cbInput.value);" in CORE
    assert "_cbSel === sel ? _cbClose() : _cbOpen(sel)" not in CORE


def test_superseded_get_requests_do_not_toast_a_false_timeout():
    assert "older._superseded=true" in CORE
    assert "controller?._superseded" in CORE


def test_rapid_day_navigation_keeps_every_click_and_drops_stale_responses():
    assert "const seq = ++CAMPAIGN_LOAD_SEQ;" in JS
    assert "if (seq !== CAMPAIGN_LOAD_SEQ) return;" in JS
    assert '$("#dutyDate").value = day;\n  await loadDay(day);' in JS


def test_failed_campaign_writes_are_toasted_and_stale_revision_is_explained():
    assert "showToast(CAMPAIGN_SAVE_ERROR, true);" in JS
    assert 'errorCode === "stale_revision"' in JS


def test_closed_days_are_read_only_with_an_exceptional_reopen_action():
    assert 'board.toggleAttribute("inert", closed)' in JS
    assert "ACTIONS.reopenCampaignDay" in JS and "/api/day-status/${DAY}/reopen" in JS
    assert '<div id="campaignClosedNote"></div>' in JS


def test_next_gap_prefers_a_missing_field_in_the_same_row():
    assert "const sameRow = sourceRow && controls.find(" in JS
    assert "const next = sameRow || controls.slice(index + 1).find(isGap);" in JS


def test_service_lines_and_vehicle_choices_are_labelled_distinctly():
    assert "const lineSuffix = row =>" in JS and "— مركبة ${row.lineIndex + 1}" in JS
    assert JS.count("${lineSuffix(row)}") == 3                               # سائق + مركبة + نوع
    # «مستخدمة في» في القايمة بس — الاختيار الحالي بيفضل رقم اللوحة نظيف
    assert 'vehicle.id === selected ? "" : esc(usedIn(vehicle))' in JS


def test_removing_a_service_does_not_empty_the_vehicle_picker(client):
    """باج حقيقي: وجود خدمة محذوفة كان بيبوّظ pickers.vehicles فمفيش رقم مركبة يظهر في أي قايمة."""
    vehicle = _vehicle(client)
    service = _assignment(client, DAY, "خدمة هتتشال")
    client.put(f"/api/campaign/{DAY}/service/{service['id']}", json={"vehicles": [{"vehicle_id": vehicle["id"]}]})
    before = [v["id"] for v in _campaign(client, DAY)["pickers"]["vehicles"]]
    assert vehicle["id"] in before

    out = client.delete(f"/api/campaign/{DAY}/service/{service['id']}/removed").get_json()

    assert out["removed_services"]
    after = out["pickers"]["vehicles"]
    assert [v["id"] for v in after] == before
    assert all(v["label"] and v["plate"] for v in after)
