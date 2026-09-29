"""جدول تفتيشات زيارات الأهالي الأسبوعي — إدارة الجدول + تحطيطه التلقائي
على اليومية التفصيلية أول ما يوم الأسبوع بتاعه يتفتح لأول مرة."""
from backend.utils import weekday_name

SATURDAY = "2026-04-11"    # اتأكد بـ weekday_name تحت — أي تاريخ، مش مهم بالظبط
FRIDAY = "2026-04-10"


def _add(client, weekday, **over):
    body = {"name": "تفتيش فيصل", "weapon": "دونك", "count": 5}
    body.update(over)
    return client.post(f"/api/inspection-schedule/{weekday}", json=body)


def test_schedule_starts_empty_for_every_weekday(client):
    d = client.get("/api/inspection-schedule").get_json()
    assert len(d["weekdays"]) == 7
    assert all(d["schedule"][w] == [] for w in d["weekdays"])


def test_add_entry_defaults_and_returns_it(client):
    r = _add(client, "السبت", name="تفتيش عتاقة", weapon="", count="")
    assert r.status_code == 201, r.get_json()
    entry = r.get_json()
    assert entry["name"] == "تفتيش عتاقة"
    assert entry["weapon"] == "دونك"      # الافتراضي لما يتبعت فاضي
    assert entry["count"] == 5

    d = client.get("/api/inspection-schedule").get_json()
    assert entry["id"] in {e["id"] for e in d["schedule"]["السبت"]}


def test_add_entry_rejects_empty_name_and_unknown_weekday(client):
    assert _add(client, "السبت", name="").status_code == 400
    assert _add(client, "يوم مخترع").status_code == 400


def test_edit_and_delete_entry(client):
    entry = _add(client, "الأحد", name="تفتيش السويس").get_json()

    r = client.patch(f"/api/inspection-schedule/الأحد/{entry['id']}",
                     json={"count": 8, "weapon": "خرطوش"})
    assert r.status_code == 200
    assert r.get_json()["count"] == 8 and r.get_json()["weapon"] == "خرطوش"

    r = client.delete(f"/api/inspection-schedule/الأحد/{entry['id']}")
    assert r.status_code == 200
    assert entry["id"] not in {e["id"] for e in
                                client.get("/api/inspection-schedule").get_json()["schedule"]["الأحد"]}


def test_edit_missing_entry_404s(client):
    assert client.patch("/api/inspection-schedule/السبت/INS-999",
                        json={"name": "x"}).status_code == 404
    assert client.delete("/api/inspection-schedule/السبت/INS-999").status_code == 404


def test_inspections_are_seeded_onto_the_board_on_first_open(client):
    day = SATURDAY
    weekday = weekday_name(day)
    _add(client, weekday, name="تفتيش فيصل", weapon="دونك", count=5)
    _add(client, weekday, name="تفتيش عتاقة", weapon="دونك", count=5)

    b = client.get(f"/api/board/{day}").get_json()
    section = next((s for s in b["sections"] if s["name"] == "تفتيشات"), None)
    assert section is not None, b["sections"]
    names = {r["name"] for r in section["rows"]}
    assert names == {"تفتيش فيصل", "تفتيش عتاقة"}
    row = next(r for r in section["rows"] if r["name"] == "تفتيش فيصل")
    assert row["weapon"] == "دونك"
    assert row["conscript_count"] == 5
    assert row["officers"] == [] and row["personnel"] == []


def test_seeding_only_happens_once_even_if_the_row_is_deleted(client):
    day = SATURDAY
    weekday = weekday_name(day)
    _add(client, weekday, name="تفتيش فيصل")

    b = client.get(f"/api/board/{day}").get_json()
    section = next(s for s in b["sections"] if s["name"] == "تفتيشات")
    row_id = section["rows"][0]["id"]
    r = client.delete(f"/api/assignments/{day}/{row_id}")
    assert r.status_code == 200, r.get_json()

    # نفس اليوم اتفتح قبل كده (حتى لو اتمسحت خانته) — مايترجعش لوحده
    b2 = client.get(f"/api/board/{day}").get_json()
    section2 = next((s for s in b2["sections"] if s["name"] == "تفتيشات"), None)
    assert section2 is None or not section2["rows"]


def test_changing_the_schedule_does_not_touch_an_already_seeded_day(client):
    day = SATURDAY
    weekday = weekday_name(day)
    _add(client, weekday, name="تفتيش فيصل")
    client.get(f"/api/board/{day}")   # يتفتح ويتحط عليه

    _add(client, weekday, name="تفتيش عتاقة")   # الجدول اتغيّر بعد كده
    b = client.get(f"/api/board/{day}").get_json()
    section = next(s for s in b["sections"] if s["name"] == "تفتيشات")
    assert {r["name"] for r in section["rows"]} == {"تفتيش فيصل"}


def test_a_weekday_with_no_schedule_leaves_the_board_untouched(client):
    day = FRIDAY
    weekday = weekday_name(day)
    assert client.get("/api/inspection-schedule").get_json()["schedule"][weekday] == []

    b = client.get(f"/api/board/{day}").get_json()
    assert not any(s["name"] == "تفتيشات" for s in b["sections"])
