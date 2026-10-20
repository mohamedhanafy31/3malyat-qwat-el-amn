"""مدير/وكيل الإدارة أعلى اتنين في أي قايمة ضباط، بغض النظر عن الرتبة."""


def test_deputy_ranks_ahead_of_higher_or_equal_rank_officers(client):
    """في الـfixture: OFF-001 عقيد، OFF-002 نقيب. لو OFF-002 وكيل الإدارة،
    لازم يظهر قبل OFF-001 رغم إن رتبته أقل."""
    client.patch("/api/command", json={"وكيل الإدارة": "OFF-002"})
    active = client.get("/api/data").get_json()["officers"]["active"]
    assert [o["id"] for o in active] == ["OFF-002", "OFF-001"]


def test_director_ahead_of_deputy(client):
    client.patch("/api/command", json={"مدير الإدارة": "OFF-002", "وكيل الإدارة": "OFF-001"})
    active = client.get("/api/data").get_json()["officers"]["active"]
    assert [o["id"] for o in active] == ["OFF-002", "OFF-001"]


def test_officers_on_day_also_respects_command_order(client):
    client.patch("/api/command", json={"وكيل الإدارة": "OFF-002"})
    rows = client.get("/api/duty/2026-06-01").get_json()["rows"]
    assert rows[0]["id"] == "OFF-002"


def test_archiving_command_holder_clears_the_post(client):
    client.patch("/api/command", json={"مدير الإدارة": "OFF-001"})
    r = client.post("/api/person/OFF-001/remove", json={"leave_date": "2026-06-01"})
    assert r.status_code == 200
    assert client.get("/api/data").get_json()["command"]["مدير الإدارة"] is None


def test_officers_page_order_matches_duty_page_rank_order(client):
    """صفحة بيانات الضباط لازم تعرض الضباط بنفس الترتيب القيادي والرتبة المستخدم في يومية الضباط."""
    bootstrap = client.get("/api/bootstrap/officers").get_json()
    officers_page_ids = [o["id"] for o in bootstrap["officers"]["active"]]

    duty = client.get("/api/duty/2026-06-01").get_json()
    duty_page_ids = [o["id"] for o in duty["rows"]]

    assert officers_page_ids == duty_page_ids



def test_seniority_key_orders_year_then_number_for_mixed_code_formats():
    from backend.utils import seniority_key

    codes = ["1223/2006", "765/2002", "2023/1657", "2007", "1043/2003", "159/2008", "ض-01", ""]
    ordered = sorted(codes, key=seniority_key)
    assert ordered == ["765/2002", "1043/2003", "1223/2006", "2007", "159/2008",
                       "2023/1657", "", "ض-01"]
    # الرقم الأكبر من 2040 مش سنة: «2060/2013» رقم 2060 سنة 2013
    assert seniority_key("2060/2013")[:3] == (0, 2013, 2060)
    assert seniority_key("٧٦٥/٢٠٠٢")[:3] == (0, 2002, 765)


def test_same_rank_officers_follow_seniority_number_not_name(client):
    client.patch("/api/person/OFF-002", json={"role": "عقيد", "code": "50/2001"})
    client.patch("/api/person/OFF-001", json={"code": "7/2009"})
    rows = client.get("/api/duty/2026-06-01").get_json()["rows"]
    assert [r["id"] for r in rows] == ["OFF-002", "OFF-001"]
    client.patch("/api/person/OFF-001", json={"code": "7/1999"})
    rows = client.get("/api/duty/2026-06-01").get_json()["rows"]
    assert [r["id"] for r in rows] == ["OFF-001", "OFF-002"]


def test_command_posts_stay_ahead_of_seniority(client):
    client.patch("/api/person/OFF-002", json={"role": "عقيد", "code": "50/2001"})
    client.patch("/api/person/OFF-001", json={"code": "7/1999"})
    client.patch("/api/command", json={"مدير الإدارة": "OFF-002"})
    rows = client.get("/api/duty/2026-06-01").get_json()["rows"]
    assert rows[0]["id"] == "OFF-002"
