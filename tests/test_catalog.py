"""كتالوج الخدمات بشكله الجديد — الحقول، والحماية من الحذف/التسمية المدمّرة."""


def _add(client, **over):
    body = {"name": "خدمة تجريبية", "kind": "خارجية", "section": "الخدمات الطارئة"}
    body.update(over)
    return client.post("/api/services", json=body)


def test_new_service_gets_the_full_shape(client):
    svc = _add(client).get_json()
    for field in ("board_label", "sub", "section", "shifts", "default_strength",
                  "default_weapon", "default_time", "party", "needs",
                  "appears_in", "aliases"):
        assert field in svc, f"الحقل {field} ناقص"
    assert svc["board_label"] == svc["name"]
    assert svc["shifts"] == ["صباحية", "ليلية"]
    assert svc["appears_in"] == ["board"]


def test_search_is_no_longer_a_service_kind(client):
    """«+N بحث» بقى تابع لجهة تشغيل الضابط مش لنوع الخدمة — الدليل في 20/8."""
    assert _add(client, kind="بحث").status_code == 400


def test_unknown_section_is_refused(client):
    assert _add(client, section="قسم مخترع").status_code == 400


def test_shifts_keep_canonical_order_and_never_empty(client):
    svc = _add(client, shifts=["ليلية", "صباحية"]).get_json()
    assert svc["shifts"] == ["صباحية", "ليلية"]
    svc2 = _add(client, name="خدمة صبح", shifts=["حاجة غلط"]).get_json()
    assert svc2["shifts"] == ["صباحية", "ليلية"]


def test_morning_only_service_is_representable(client):
    """محور 1 و2 وقول 48 والإسعاف صباحية بس في الوورد — العمود الليلي «ــــ»."""
    svc = _add(client, name="محور 1", shifts=["صباحية"]).get_json()
    assert svc["shifts"] == ["صباحية"]


def test_rename_keeps_the_old_name_as_an_alias(client):
    """الاسم القديم لازم يفضل معروف عشان الاستيراد من الوورد يفضل يتعرّف عليه."""
    svc = _add(client, name="ترحيلة بدر").get_json()
    out = client.patch(f"/api/services/{svc['id']}", json={"name": "ترحيلة بدر 7ص"}).get_json()
    assert out["name"] == "ترحيلة بدر 7ص"
    assert "ترحيله بدر" in out["aliases"], out["aliases"]


def test_rename_to_an_existing_name_is_refused(client):
    a = _add(client, name="خدمة أ").get_json()
    _add(client, name="خدمة ب")
    assert client.patch(f"/api/services/{a['id']}", json={"name": "خدمة ب"}).status_code == 409


def test_duplicate_name_is_matched_after_normalisation(client):
    """«ترحيلة» و«ترحيله» نفس الاسم — التطبيع بيمنع خدمتين لنفس الحاجة."""
    _add(client, name="ترحيلة المحكمة")
    assert _add(client, name="ترحيله المحكمه").status_code == 409


def test_delete_is_blocked_by_a_board_assignment(client, data_file):
    """قبل كده الفحص كان على يومية التشغيل بس، فكان ينفع تمسح خدمة لسه
    على اللوحة وتسيب خانتها بلا مرجع."""
    import json
    svc = _add(client, name="خدمة على اللوحة").get_json()
    data = json.loads(data_file.read_text(encoding="utf-8"))
    data["day_assignments"] = {"2026-04-10": [{"id": "AS-0001", "service_id": svc["id"],
                                               "officer_ids": []}]}
    data_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    r = client.delete(f"/api/services/{svc['id']}")
    assert r.status_code == 409
    assert "مستخدمة" in r.get_json()["error"]


def test_unused_service_can_still_be_deleted(client):
    svc = _add(client, name="خدمة مش مستخدمة").get_json()
    assert client.delete(f"/api/services/{svc['id']}").status_code == 200
