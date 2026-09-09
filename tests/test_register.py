"""دفتر 43 — صف لكل ضابط، عمود لكل يوم، والخانة رمز حالته.

الدفتر ده بيتستخدم كإثبات رسمي لتواجد الفرد من عدمه في يوم معيّن (اتساءل
عنه في المحاكم بالصيغة دي)، فالاختبارات هنا بتركّز على إن كل رمز صادق
وبيرجّع لمصدره، وإن الفرق بين «مفيش سجل» و«موجود بالإدارة» واضح.
"""
DAY = "2026-04-10"


def _add(client, day=DAY, **over):
    body = {"service_id": "SVC-001", "shift": "صباحية"}
    body.update(over)
    return client.post(f"/api/assignments/{day}", json=body)


def _month(client, year=2026, month=4):
    return client.get(f"/api/register/{year}/{month}").get_json()


def _row(reg, officer_id):
    return next(r for r in reg["rows"] if r["id"] == officer_id)


def _cell(reg, officer_id, day):
    return next(c for c in _row(reg, officer_id)["cells"] if c["day"] == day)


def test_grid_is_officers_by_days_of_the_month(client):
    _add(client, officer_ids=["OFF-002"])
    reg = _month(client)
    assert len(reg["days"]) == 30                      # أبريل
    assert reg["days"][0] == "2026-04-01"
    assert all(len(r["cells"]) == 30 for r in reg["rows"])
    assert {r["id"] for r in reg["rows"]} == {"OFF-001", "OFF-002"}


def test_a_day_with_no_roster_is_not_read_as_admin_work(client):
    """أخطر التباس في سجل بيتستخدم كإثبات: غياب اليومية مش معناه إن
    الضابط كان موجود بالإدارة، ولا معناه إنه كان غايب."""
    _add(client, officer_ids=["OFF-002"])
    reg = _month(client)
    assert _cell(reg, "OFF-002", DAY)["code"] == "ص"
    blank = _cell(reg, "OFF-002", "2026-04-11")
    assert blank["code"] == "·"
    assert blank["family"] == "بدون سجل"
    assert reg["recorded_days"] == [DAY]


def test_unrecorded_days_are_excluded_from_the_tally(client):
    _add(client, officer_ids=["OFF-002"])
    tally = _row(_month(client), "OFF-002")["tally"]
    assert tally["days"] == 1, "يوم واحد بس هو اللي فيه يومية"
    assert tally["by_family"] == {"عمل": 1, "راحة": 0, "خارج": 0}


def test_every_cell_carries_the_service_behind_it(client):
    """الضغط على الخانة لازم يوري الخدمة — ده أساس حجّية الدفتر."""
    _add(client, officer_ids=["OFF-002"])
    cell = _cell(_month(client), "OFF-002", DAY)
    assert [s["name"] for s in cell["services"]] == ["دورية خارجية"]
    assert cell["services"][0]["shift"] == "صباحية"


def test_each_state_has_its_own_symbol(client):
    """رمز مفصّل لكل حالة — مش «عمل» موحّد."""
    codes = {}
    for status in ("غياب", "مرضي", "فرقة", "انتداب"):
        client.put(f"/api/duty/{DAY}/OFF-001", json={"status": status})
        codes[status] = _cell(_month(client), "OFF-001", DAY)["code"]
    assert len(set(codes.values())) == 4, codes
    assert codes["غياب"] == "غ" and codes["مرضي"] == "ض"


def test_night_and_morning_are_different_symbols(client):
    _add(client, officer_ids=["OFF-002"], shift="صباحية")
    assert _cell(_month(client), "OFF-002", DAY)["code"] == "ص"

    client.post(f"/api/assignments/2026-04-12",
                json={"service_id": "SVC-001", "shift": "ليلية",
                      "officer_ids": ["OFF-001"]})
    assert _cell(_month(client), "OFF-001", "2026-04-12")["code"] == "ل"


def test_daily_totals_answer_who_was_present(client):
    _add(client, officer_ids=["OFF-002"])
    client.put(f"/api/duty/{DAY}/OFF-001", json={"status": "غياب"})
    totals = next(t for t in _month(client)["totals"] if t["day"] == DAY)
    assert totals == {"day": DAY, "recorded": True, "force": 2,
                      "working": 1, "resting": 0, "away": 1}


def test_officer_who_left_mid_month_is_marked_apart(client):
    """مش على القوة ≠ غايب ≠ مفيش سجل — تلات حالات مختلفة، ولازم تفضل
    مميزة عن بعضها في سجل بيثبت التواجد."""
    _add(client, officer_ids=["OFF-002"])                    # 10 أبريل: بالقوة
    client.post("/api/assignments/2026-04-15",
                json={"service_id": "SVC-001", "officer_ids": ["OFF-001"]})
    client.post("/api/person/OFF-002/remove", json={"leave_date": "2026-04-12"})

    reg = _month(client)
    assert _cell(reg, "OFF-002", DAY)["code"] == "ص"         # كان بالقوة
    assert _cell(reg, "OFF-002", "2026-04-15")["code"] == "—"   # خرج قبلها
    assert _cell(reg, "OFF-002", "2026-04-20")["code"] == "·"   # ومفيش يومية أصلًا


def test_an_officer_never_on_force_gets_no_row(client):
    """الدفتر بيعرض اللي كانوا على القوة في الشهر ده بس."""
    client.post("/api/person/OFF-002/remove", json={"leave_date": "2026-03-01"})
    client.post("/api/assignments/2026-04-15",
                json={"service_id": "SVC-001", "officer_ids": ["OFF-001"]})
    assert {r["id"] for r in _month(client)["rows"]} == {"OFF-001"}


def test_officer_page_covers_every_recorded_day(client):
    _add(client, officer_ids=["OFF-002"])
    client.post("/api/assignments/2026-05-02",
                json={"service_id": "SVC-001", "officer_ids": ["OFF-002"]})
    out = client.get("/api/register/officer/OFF-002").get_json()
    assert out["tally"]["days"] == 2
    assert [m["month"] for m in out["months"]] == ["2026-04", "2026-05"]
    assert out["tally"]["services"] == [{"name": "دورية خارجية", "count": 2}]


def test_officer_page_counts_services_by_name(client):
    """«حصر لعدد الخدمات وأنواعها» — الخدمة بالاسم مش بالخانة بس."""
    client.post("/api/services", json={"name": "هدف سوميد", "kind": "حراسات",
                                        "section": "الأهداف"})
    guard = client.get("/api/bootstrap/catalog").get_json()["services"][-1]["id"]
    _add(client, officer_ids=["OFF-002"])
    _add(client, day="2026-04-11", service_id=guard, officer_ids=["OFF-002"])
    out = client.get("/api/register/officer/OFF-002").get_json()
    assert {s["name"]: s["count"] for s in out["tally"]["services"]} == {
        "دورية خارجية": 1, "هدف سوميد": 1}
    assert out["tally"]["by_code"] == {"ص": 1, "ح": 1}


def test_legend_covers_every_code_in_use(client):
    _add(client, officer_ids=["OFF-002"])
    reg = _month(client)
    known = {l["code"] for l in reg["legend"]}
    used = {c["code"] for r in reg["rows"] for c in r["cells"]}
    assert used <= known, used - known


def test_bad_month_and_unknown_officer_are_refused(client):
    assert client.get("/api/register/2026/13").status_code == 400
    assert client.get("/api/register/officer/OFF-999").status_code == 404
