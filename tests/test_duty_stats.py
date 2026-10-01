"""إحصائيات تشغيل الضباط — تجميع على مدى أيام، عكس اليومية اللي بتعرض
يوم واحد بس."""
DAY = "2026-04-10"
DAY2 = "2026-04-11"


def _add(client, day=DAY, **over):
    body = {"name": "دورية خارجية", "kind": "خارجية", "section": "الخدمات أساسية",
            "shift": "صباحية"}
    body.update(over)
    return client.post(f"/api/assignments/{day}", json=body)


def _stats(client, date_from=DAY, date_to=DAY2):
    r = client.get(f"/api/duty/stats?date_from={date_from}&date_to={date_to}")
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def test_bootstrap_ships_weekdays_for_the_weekday_chart(client):
    """صفحة الإحصائيات لازم يكون ليها فرع في bootstrap(page) — من غيره
    الصفحة بترجع 404 صامت والفرونت إند بيفضل META فاضي، فعمود «نمط
    التشغيل الأسبوعي» بيرسم شارت فاضي تمامًا من غير أي رسالة خطأ واضحة."""
    d = client.get("/api/bootstrap/duty_stats")
    assert d.status_code == 200, d.get_json()
    assert d.get_json()["meta"]["weekdays"]


def test_a_day_thats_only_closed_with_no_assignments_is_not_counted(client):
    """يوم اتقفل بدري من غير ما حد يكتب فيه تكليف أو حالة ضابط لسه مش
    «يوم شغل فعلي» — نفس التفرقة اللي register.py::recorded_days()
    بيعملها. لو اتحسب غلط، كل ضابط على القوة هيظهر «صافي» ليوم محدش
    شافه أصلًا، وده بيضخّم net_rate بالغلط."""
    r = client.post(f"/api/day-status/{DAY}/close", json={})
    assert r.status_code == 201, r.get_json()

    d = _stats(client, DAY, DAY)
    assert d["days_count"] == 0
    assert d["by_officer_load"] == []
    assert d["net_rate"] == []


def test_range_defaults_to_the_requested_days_only(client):
    _add(client, day=DAY, officer_ids=["OFF-001"])
    d = _stats(client, DAY, DAY)
    assert d["date_from"] == DAY and d["date_to"] == DAY
    assert d["days_count"] == 1


def test_officer_load_counts_services_by_kind(client):
    _add(client, day=DAY, officer_ids=["OFF-001"], kind="خارجية", shift="صباحية")
    _add(client, day=DAY2, officer_ids=["OFF-001"], kind="حراسات", section="الأهداف",
         name="سوميد", shift="")

    d = _stats(client)
    row = next(r for r in d["by_officer_load"] if r["id"] == "OFF-001")
    assert row["total"] == 2
    assert row["by_kind"] == {"خارجية": 1, "حراسات": 1}


def test_net_rate_is_100_percent_for_an_officer_with_no_service_that_day(client):
    """يوم فيه يومية فعلًا (تكليف لـOFF-002) — OFF-001 اللي مالوش أي
    تكليف فيه لازم يتصنّف «صافي» مش «بدون سجل»."""
    _add(client, day=DAY, officer_ids=["OFF-002"])

    d = _stats(client, DAY, DAY)
    off1 = next(r for r in d["net_rate"] if r["id"] == "OFF-001")
    assert off1["net_days"] == off1["total_days"] == 1
    assert off1["rate"] == 100.0


def test_shift_balance_counts_morning_and_night_separately(client):
    _add(client, day=DAY, officer_ids=["OFF-001"], shift="صباحية")
    _add(client, day=DAY2, officer_ids=["OFF-001"], shift="ليلية")

    d = _stats(client)
    row = next(r for r in d["shift_balance"] if r["id"] == "OFF-001")
    assert row["morning"] == 1 and row["night"] == 1


def test_taqseera_count_only_lists_officers_with_at_least_one(client):
    r = client.put(f"/api/duty/{DAY}/OFF-001", json={"taqseera": True})
    assert r.status_code == 200, r.get_json()

    d = _stats(client)
    ids = {r["id"] for r in d["taqseera_count"]}
    assert ids == {"OFF-001"}
    assert d["taqseera_count"][0]["count"] == 1


def test_target_gap_detects_a_target_covered_by_someone_other_than_its_commander(client):
    """هدف «سوميد» قائده الرسمي OFF-001 (من منصبه)، بس المعيّن فعليًا
    النهاردة OFF-002 — ده بالظبط سيناريو «الفجوة» اللي الكارت بيقيسه."""
    r = client.patch("/api/person/OFF-001",
                     json={"post": "قائد هدف سوميد", "effective_from": "2020-01-01"})
    assert r.status_code == 200, r.get_json()

    r = client.put(f"/api/board/{DAY}/target/سوميد", json={"officer_ids": ["OFF-002"]})
    assert r.status_code == 200, r.get_json()

    d = _stats(client, DAY, DAY)
    gap = next(g for g in d["target_gap"] if g["name"] == "سوميد")
    assert gap == {"name": "سوميد", "assigned_days": 1, "commander_known_days": 1,
                   "mismatch_days": 1, "mismatch_rate": 100.0}


def test_target_gap_is_not_a_mismatch_when_the_commander_covers_it_himself(client):
    r = client.patch("/api/person/OFF-001",
                     json={"post": "قائد هدف سوميد", "effective_from": "2020-01-01"})
    assert r.status_code == 200, r.get_json()

    r = client.put(f"/api/board/{DAY}/target/سوميد", json={"officer_ids": ["OFF-001"]})
    assert r.status_code == 200, r.get_json()

    d = _stats(client, DAY, DAY)
    gap = next(g for g in d["target_gap"] if g["name"] == "سوميد")
    assert gap["mismatch_days"] == 0
    assert gap["mismatch_rate"] == 0.0


def test_target_gap_has_no_rate_when_no_commander_is_registered_at_all(client):
    """هدف اتغطى بس مفيش قائد رسمي مسجّل أصلًا — النسبة None مش صفر،
    عشان صفر يعني «القائد نفسه بيغطي»، وده مختلف عن «مفيش قائد نقارن بيه»."""
    r = client.put(f"/api/board/{DAY}/target/سوميد", json={"officer_ids": ["OFF-002"]})
    assert r.status_code == 200, r.get_json()

    d = _stats(client, DAY, DAY)
    gap = next(g for g in d["target_gap"] if g["name"] == "سوميد")
    assert gap["assigned_days"] == 1
    assert gap["commander_known_days"] == 0
    assert gap["mismatch_rate"] is None


def test_by_weekday_bucket_matches_the_real_calendar(client):
    """DAY = 2026-04-10 جمعة، DAY2 = 2026-04-11 سبت."""
    _add(client, day=DAY, officer_ids=["OFF-001"])
    _add(client, day=DAY2, officer_ids=["OFF-002"])

    d = _stats(client)
    by_weekday = {w["weekday"]: w for w in d["by_weekday"]}
    assert by_weekday["الجمعة"]["services"] == 1
    assert by_weekday["السبت"]["services"] == 1


def test_invalid_supplied_dates_return_a_structured_400(client):
    """تاريخ موجود ومش صالح كان بيتجاهل بصمت ويعرض المدى الافتراضي —
    المستخدم يشوف أرقام لمدى غير اللي طلبه."""
    for query in ("date_from=2026-13-01&date_to=2026-04-11",
                  "date_from=2026-04-10&date_to=nope",
                  "date_from=garbage"):
        r = client.get(f"/api/duty/stats?{query}")
        assert r.status_code == 400, query
        assert r.get_json()["error"]


def test_historical_bounds_are_accepted_and_only_recorded_days_count(client):
    _add(client, day=DAY, officer_ids=["OFF-001"])
    d = _stats(client, "2000-01-01", "2030-12-31")
    assert d["date_from"] == "2000-01-01" and d["date_to"] == "2030-12-31"
    assert d["days_count"] == 1


def test_extreme_range_never_walks_the_calendar(client, monkeypatch):
    """0001-01-01..9999-12-31 = ٣.٦ مليون يوم — لازم الشغل يبقى على قد
    الأيام المسجّلة بس، مش على قد طول المدى."""
    import time
    from backend import utils

    def boom(*_a, **_k):
        raise AssertionError("days_between اتنده على مدى التقرير")
    monkeypatch.setattr(utils, "days_between", boom)

    _add(client, day=DAY, officer_ids=["OFF-001"])
    _add(client, day=DAY2, officer_ids=["OFF-001"], shift="ليلية")
    started = time.perf_counter()
    d = _stats(client, "0001-01-01", "9999-12-31")
    assert time.perf_counter() - started < 2
    assert d["days_count"] == 2


def test_reversed_bounds_still_select_the_recorded_days(client):
    _add(client, day=DAY, officer_ids=["OFF-001"])
    d = _stats(client, DAY2, DAY)
    assert (d["date_from"], d["date_to"]) == (DAY, DAY2)
    assert d["days_count"] == 1
