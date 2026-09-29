"""قايمة الاختيار في مودال الخانة (`board.roster`) — بس اللي كانوا على
القوة في يوم اللوحة نفسه، مش كل ضابط/فرد اتسجّل في السيستم يومًا.

قبل كده كانت الصفحة بتاخد قايمة ثابتة من `bootstrap` (كل الضباط، نشطين
ومتأرشفين مع بعض) فأي ضابط خرج من القوة كان لسه ظاهر في قايمة الاختيار
لأي يوم — حتى النهاردة.
"""
DAY = "2026-04-10"
OLD_DAY = "2026-01-01"


def _roster(client, day=DAY):
    return client.get(f"/api/board/{day}").get_json()["roster"]


def _archive_officer(client, officer_id, leave_date):
    r = client.post(f"/api/person/{officer_id}/remove", json={"leave_date": leave_date})
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def _add_personnel(client, name="فرد اختبار", code="900", join_date="2020-01-01"):
    r = client.post("/api/person", json={
        "type": "personnel", "name": name, "code": code, "phone": "0100",
        "join_date": join_date, "role": "أمين شرطة"})
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def test_roster_lists_only_officers_currently_on_the_force(client):
    """OFF-001 و OFF-002 نشطين في الـfixture — الاتنين لازم يظهروا."""
    roster = _roster(client)
    ids = {o["id"] for o in roster["officers"]}
    assert ids == {"OFF-001", "OFF-002"}


def test_an_officer_who_left_the_force_disappears_from_the_roster(client):
    _archive_officer(client, "OFF-002", "2026-02-01")
    ids = {o["id"] for o in _roster(client, DAY)["officers"]}
    assert ids == {"OFF-001"}, "الضابط اللي خرج من القوة ما يفضلش في قايمة الاختيار"


def test_an_archived_officer_still_appears_for_a_day_he_was_on_force_in(client):
    """تعديل يوم قديم لازم يفضل شغّال — الضابط كان على القوة يومها فعلًا،
    وده اللي بيخلّي تكليفه القديم قابل للتعديل من غير ما يختفي بالغلط."""
    _archive_officer(client, "OFF-002", "2026-02-01")
    ids = {o["id"] for o in _roster(client, OLD_DAY)["officers"]}
    assert "OFF-002" in ids, "كان على القوة في 2026-01-01 — لازم يظهر"


def test_officer_who_had_not_joined_yet_is_excluded_from_an_old_day(client):
    """العكس بالظبط: ضابط لسه ما انضمش يوم اللوحة القديم مايظهرش فيه."""
    client.patch("/api/person/OFF-002", json={"join_date": "2026-03-01"})
    ids = {o["id"] for o in _roster(client, OLD_DAY)["officers"]}
    assert "OFF-002" not in ids


def test_personnel_roster_follows_the_same_rule_as_officers(client):
    p = _add_personnel(client, code="901")
    assert p["id"] in {x["id"] for x in _roster(client)["personnel"]}

    client.post(f"/api/person/{p['id']}/remove", json={"leave_date": "2026-02-01"})
    assert p["id"] not in {x["id"] for x in _roster(client, DAY)["personnel"]}
    assert p["id"] in {x["id"] for x in _roster(client, OLD_DAY)["personnel"]}


def test_roster_reports_the_officers_rank_as_it_was_on_that_day(client):
    """الرتبة بتتغيّر بالترقيات — قايمة الاختيار لازم تعرض الرتبة يوم
    اللوحة نفسه مش الرتبة الحالية، زي باقي شاشات النظام. OFF-001 «عقيد»
    من الـfixture، وهنسجّل ترقية لـ«لواء» سارية من بعد OLD_DAY."""
    r = client.patch("/api/person/OFF-001",
                     json={"role": "لواء", "effective_from": "2026-03-01"})
    assert r.status_code == 200, r.get_json()

    before = next(o for o in _roster(client, OLD_DAY)["officers"] if o["id"] == "OFF-001")
    assert before["role"] == "عقيد", "قبل الترقية — الرتبة الأصلية"

    after = next(o for o in _roster(client, DAY)["officers"] if o["id"] == "OFF-001")
    assert after["role"] == "لواء", "الـfixture ثابت على 2026-04-10، بعد الترقية"


def test_assigning_someone_not_on_the_force_is_still_rejected_by_the_backend(client):
    """قايمة الاختيار عرض بس — المنع الحقيقي في الحفظ، والاتنين لازم يتفقوا."""
    client.patch("/api/person/OFF-002", json={"join_date": "2026-05-01"})
    r = client.post(f"/api/assignments/{DAY}",
                    json={"name": "خدمة", "kind": "خارجية", "officer_ids": ["OFF-002"]})
    assert r.status_code == 400
    assert "OFF-002" not in {o["id"] for o in _roster(client, DAY)["officers"]}


def test_an_officer_on_leave_that_day_is_hidden_from_the_roster(client):
    """الضابط في راحة/إجازة تغطي يوم اللوحة ميظهرش في قايمة اختيار خانة
    جديدة — بحث «تسكين الخدمات» كان بيعرضه زي أي ضابط تاني، فكان ممكن
    يتعيّن على خدمة وهو في الخوارج."""
    r = client.post("/api/leaves", json={
        "person_id": "OFF-002", "type": "أسبوعية", "start": DAY, "end": DAY})
    assert r.status_code == 201, r.get_json()
    ids = {o["id"] for o in _roster(client, DAY)["officers"]}
    assert "OFF-002" not in ids
    # يوم تاني بعيد عن الراحة يفضل ظاهر فيه عادي
    assert "OFF-002" in {o["id"] for o in _roster(client, OLD_DAY)["officers"]}


def test_an_officer_already_assigned_before_going_on_leave_stays_in_the_edit_modal(client):
    """الفلترة دي عرض بحث بس — لو الضابط اتعيّن قبل كده على خدمة وبعدين
    اتسجّلت له راحة تغطي نفس اليوم، الحفظ نفسه لازم يفضل شغّال (مش هدفنا
    نمسح تكليف موجود بالغلط)، والعرض بيرجّعه من `withCurrent` في الواجهة."""
    r = client.post(f"/api/assignments/{DAY}",
                    json={"name": "خدمة", "kind": "خارجية", "officer_ids": ["OFF-002"]})
    assert r.status_code == 201, r.get_json()
    r = client.post("/api/leaves", json={
        "person_id": "OFF-002", "type": "أسبوعية", "start": DAY, "end": DAY})
    assert r.status_code == 201, r.get_json()
    board = client.get(f"/api/board/{DAY}").get_json()
    assert "OFF-002" not in {o["id"] for o in board["roster"]["officers"]}
    occasional = next(s for s in board["sections"] if s["name"] == "الخدمات الطارئة")
    row = next(r for r in occasional["rows"] if r["name"] == "خدمة")
    assert row["officers"][0]["id"] == "OFF-002", "التكليف الموجود يفضل زي ما هو"


def test_assigning_a_personnel_not_on_the_force_is_also_rejected(client):
    """نفس القيد كان على الضباط بس — فرد اتأرشف قبل اليوم ده كان ينفع
    يتكلّف عليه من غير أي فحص، فرقان عن الضباط."""
    fard = _add_personnel(client, join_date="2026-05-01")   # انضم بعد DAY
    r = client.post(f"/api/assignments/{DAY}",
                    json={"name": "خدمة", "kind": "خارجية", "personnel_ids": [fard["id"]]})
    assert r.status_code == 400
    assert fard["id"] not in {p["id"] for p in _roster(client, DAY)["personnel"]}


def test_clinic_officers_are_not_offered_or_listed_in_computed_board_sections(client):
    """حالة مكتوبة بالإيد بتغلب «طبية» في حساب اليومية، فلازم
    اللوحة تستبعد ضابط العيادة بالهوية مش بالمجموعة الناتجة.
    """
    assert client.patch("/api/command-groups", json={"طبي": ["OFF-002"]}).status_code == 200
    assert client.put(f"/api/duty/{DAY}/OFF-002", json={"status": "غياب"}).status_code == 200

    board = client.get(f"/api/board/{DAY}").get_json()
    assert "OFF-002" not in {o["id"] for o in board["roster"]["officers"]}
    computed = {"عمل بالإدارة", "الراحات", "التقصيرات", "الخوارج"}
    assert all("OFF-002" not in {r["id"] for r in section["rows"]}
               for section in board["sections"] if section["name"] in computed)

    duty_row = next(r for r in client.get(f"/api/duty/{DAY}").get_json()["rows"]
                    if r["id"] == "OFF-002")
    assert (duty_row["group"], duty_row["bucket"]) == ("خوارج", "غياب")


def test_stored_assignment_keeps_a_clinic_officer_while_new_picking_hides_him(client):
    """المنع في قايمة الاختيار بس؛ الحفظ لسه بيقبله وصف الخدمة يعرضه."""
    assert client.patch("/api/command-groups", json={"طبي": ["OFF-002"]}).status_code == 200
    saved = client.post(f"/api/assignments/{DAY}", json={
        "name": "خدمة محفوظة", "kind": "خارجية", "officer_ids": ["OFF-002"],
    })
    assert saved.status_code == 201, saved.get_json()

    board = client.get(f"/api/board/{DAY}").get_json()
    assert "OFF-002" not in {o["id"] for o in board["roster"]["officers"]}
    occasional = next(s for s in board["sections"] if s["name"] == "الخدمات الطارئة")
    row = next(r for r in occasional["rows"] if r["name"] == "خدمة محفوظة")
    assert [o["id"] for o in row["officers"]] == ["OFF-002"]
