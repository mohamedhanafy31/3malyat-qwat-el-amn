"""القراءة بنطاق، فهرس الأيام، وكاش الملفات (backend/store.py).

كل مسار بيعلن الأيام اللي محتاجها؛ الأرشيف الكامل للتصدير الصريح بس.
"""
import json
import os
import re
from pathlib import Path

import pytest

from backend import store
from backend.utils import recorded_range_scope

DAYS = ["2026-03-01", "2026-03-02", "2026-03-03", "2026-03-10"]
ROUTES_DIR = Path(store.ROOT) / "backend" / "routes"


def _add(client, day, name, section="الخدمات الأساسية", **extra):
    payload = {"name": name, "kind": "خارجية", "section": section, "shift": "صباحية"}
    payload.update(extra)
    response = client.post(f"/api/assignments/{day}", json=payload)
    assert response.status_code == 201, response.get_json()
    return response.get_json()


@pytest.fixture
def archive(client):
    """أرشيف صغير متعدد الأيام مبني من الـAPI نفسه."""
    for i, day in enumerate(DAYS):
        _add(client, day, f"خدمة {i}", officer_ids=["OFF-001"] if i % 2 == 0 else [])
    _add(client, DAYS[1], "فرعي", section="المعسكر الفرعي")
    return client


def _write_day(day, blob):
    path = store.day_path(day)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob, ensure_ascii=False), encoding="utf-8")
    return path


def _loaded_days(data):
    return sorted(k for k in data["_fp"]["fingerprints"] if k != "core")


# ---------- النطاق ----------

def test_scoped_read_loads_only_named_days(archive):
    data = store.load_data([DAYS[1]])
    assert _loaded_days(data) == [DAYS[1]]
    assert list(dict.keys(data["day_assignments"])) == [DAYS[1]]
    assert data["_fp"]["scope"] == frozenset([DAYS[1]])
    # يوم من غير ملف في النطاق مش بيوقع
    assert _loaded_days(store.load_data([DAYS[0], "2030-01-01"])) == [DAYS[0]]
    assert _loaded_days(store.load_data(())) == []


def test_default_and_explicit_all_days_load_everything(archive):
    assert _loaded_days(store.load_data()) == DAYS
    full = store.load_data(store.ALL_DAYS)
    assert _loaded_days(full) == DAYS
    assert full["_fp"]["scope"] is None
    assert type(full["day_assignments"]) is dict


@pytest.mark.parametrize("bad", [None, "2026-03-01", 5])
def test_invalid_scope_is_rejected(archive, bad):
    with pytest.raises(TypeError):
        store.load_data(bad)


def test_callable_scope_sees_core_and_index(archive):
    seen = {}

    def scope(view):
        seen["officers"] = [o["id"] for o in view.data["officers"]]
        seen["recorded"] = view.index.recorded()
        return view.index.days_with("day_assignments", start=DAYS[2])

    data = store.load_data(scope)
    assert seen == {"officers": ["OFF-001", "OFF-002"], "recorded": DAYS}
    assert _loaded_days(data) == DAYS[2:]


def test_out_of_scope_read_raises_instead_of_looking_empty(archive):
    data = store.load_data([DAYS[1]])
    section = data["day_assignments"]
    for access in (lambda: section[DAYS[0]], lambda: section.get(DAYS[0]),
                   lambda: DAYS[0] in section, lambda: section.setdefault(DAYS[0], [])):
        with pytest.raises(store.OutOfScope):
            access()
    # يوم مالوش بيانات على القرص — فاضي عادي
    assert section.get("2030-01-01") is None
    assert "2030-01-01" not in section
    # قسم مش موجود في ملف اليوم ده برضه فاضي عادي
    assert data["day_status"].get(DAYS[0]) is None
    # الوصول العادي للقاموس جوّه النطاق شغّال
    assert section[DAYS[1]] == section.get(DAYS[1])
    assert dict(section) == {DAYS[1]: section[DAYS[1]]}
    assert bool(data["day_status"]) is True


def test_out_of_scope_write_raises_and_touches_nothing(archive):
    before = {d: store.day_path(d).read_bytes() for d in DAYS}
    core_before = store.core_file().read_bytes()
    data = store.load_data([DAYS[1]])
    dict.__setitem__(data["day_assignments"], DAYS[0], [{"id": "AS-9", "name": "فوق الملف"}])
    data["day_assignments"][DAYS[1]][0]["name"] = "متعدّل"
    with pytest.raises(store.OutOfScope):
        store.save_data(data)
    assert {d: store.day_path(d).read_bytes() for d in DAYS} == before
    assert store.core_file().read_bytes() == core_before


def test_scoped_transaction_writes_only_its_day(archive):
    before = {d: store.day_path(d).read_bytes() for d in DAYS}

    def mutate(data):
        data["day_assignments"][DAYS[2]][0]["name"] = "متعدّل"
        return "ok"

    assert store.with_data(mutate, [DAYS[2]]) == "ok"
    after = {d: store.day_path(d).read_bytes() for d in DAYS}
    assert [d for d in DAYS if after[d] != before[d]] == [DAYS[2]]
    full = store.load_data()
    assert full["day_assignments"][DAYS[2]][0]["name"] == "متعدّل"
    assert set(full["day_assignments"]) == set(DAYS)


def test_aborted_scoped_transaction_saves_nothing(archive):
    before = store.day_path(DAYS[0]).read_bytes()

    def mutate(data):
        data["day_assignments"][DAYS[0]].clear()
        raise store.AbortRequest(("no", 400))

    assert store.with_data(mutate, [DAYS[0]]) == ("no", 400)
    assert store.day_path(DAYS[0]).read_bytes() == before


def test_routes_declare_scope_in_source():
    bare = re.compile(r"\bload_data\(\s*\)|\bwith_data\(\s*\w+\s*\)")
    offenders = [f"{p.name}:{i}" for p in sorted(ROUTES_DIR.glob("*.py"))
                 for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                 if bare.search(line)]
    assert offenders == []


def test_only_explicit_export_reads_the_whole_archive(archive, monkeypatch):
    calls = []
    real = store._read

    def recording(days=store.ALL_DAYS):
        calls.append(days)
        return real(days)

    monkeypatch.setattr(store, "_read", recording)
    gets = [f"/api/board/{DAYS[1]}", f"/api/assignments/{DAYS[1]}",
            f"/api/board/{DAYS[1]}/confirm", f"/api/duty/{DAYS[1]}",
            f"/api/counts/{DAYS[1]}", "/api/counts/template", f"/api/afraad/{DAYS[1]}",
            f"/api/day-status/{DAYS[1]}", "/api/register/2026/3",
            "/api/register/officer/OFF-001", "/api/duty/stats", "/api/officer-log/OFF-001",
            "/api/leaves/stats", "/api/courses", "/api/missions", "/api/changes",
            "/api/rest-suspensions", "/api/service-catalog", "/api/inspection-schedule",
            "/api/bootstrap/dashboard", "/api/bootstrap/officers", "/api/bootstrap/board"]
    for url in gets:
        calls.clear()
        assert archive.get(url).status_code == 200, url
        assert calls and all(c is not store.ALL_DAYS for c in calls), url

    calls.clear()
    assert archive.get(f"/api/board/{DAYS[1]}/section-history",
                       query_string={"section": "المعسكر الفرعي"}).status_code == 200
    assert calls and store.ALL_DAYS not in calls

    calls.clear()
    assert archive.get("/api/data").status_code == 200
    assert calls == [store.ALL_DAYS]


def test_scoped_responses_match_full_reads(archive, monkeypatch):
    urls = [f"/api/board/{DAYS[2]}", f"/api/assignments/{DAYS[1]}",
            f"/api/duty/{DAYS[2]}", f"/api/counts/{DAYS[1]}", f"/api/afraad/{DAYS[1]}",
            "/api/register/2026/3", "/api/register/officer/OFF-001",
            "/api/duty/stats", "/api/officer-log/OFF-001",
            f"/api/board/{DAYS[3]}/section-history?section=المعسكر الفرعي",
            "/api/bootstrap/board"]
    scoped = {url: archive.get(url).get_json() for url in urls}
    monkeypatch.setattr(store, "_resolve_scope", lambda days, view: None)
    full = {url: archive.get(url).get_json() for url in urls}
    assert scoped == full


def test_recorded_range_scope_loads_recorded_days_in_range(archive):
    data = store.load_data(recorded_range_scope({"date_from": DAYS[1], "date_to": DAYS[2]}))
    assert _loaded_days(data) == DAYS[1:3]
    # من غير مدى: آخر 30 يوم لحد آخر يوم مسجّل
    assert _loaded_days(store.load_data(recorded_range_scope({}))) == DAYS


# ---------- الفهرس ----------

def test_index_tracks_recorded_days_and_board_sections(archive):
    index = store.day_index()
    assert index.days() == DAYS
    assert index.recorded() == DAYS
    assert index.recorded_between(DAYS[2], DAYS[0]) == DAYS[:3]
    assert index.person_days("OFF-001") == [DAYS[0], DAYS[2]]
    assert dict(index.board_sections())[DAYS[1]] == ("الخدمات الأساسية", "المعسكر الفرعي")
    assert store.day_names() == DAYS


def test_index_updates_transactionally_without_rebuild(archive):
    store.day_index()
    stats = dict(store.INDEX_STATS)
    _add(archive, "2026-04-01", "جديدة", section="المعسكر الفرعي")
    index = store.day_index()
    assert "2026-04-01" in index.recorded()
    assert dict(index.board_sections())["2026-04-01"] == ("المعسكر الفرعي",)

    def clear(data):
        for key in store.DAY_SECTIONS:
            data[key].pop("2026-04-01", None)
    store.with_data(clear, ["2026-04-01"])
    assert "2026-04-01" not in store.day_index()
    assert not store.day_path("2026-04-01").exists()
    assert store.INDEX_STATS == stats


def test_index_rebuilds_when_missing_or_data_dir_changes(archive, tmp_path, monkeypatch):
    expected = store.day_index().days()
    rebuilds = store.INDEX_STATS["rebuilds"]
    store._cache.clear()                       # زي عملية جديدة
    assert store.day_index().days() == expected
    assert store.INDEX_STATS["rebuilds"] == rebuilds + 1

    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "other")
    store.explode({"officers": [], "personnel": [], "schema": store.SCHEMA_VERSION})
    assert store.day_index().days() == []
    assert store.INDEX_STATS["rebuilds"] == rebuilds + 2


def test_index_repairs_stale_entries_after_external_edits(archive):
    store.day_index()
    repairs = store.INDEX_STATS["repairs"]
    rebuilds = store.INDEX_STATS["rebuilds"]

    _write_day("2026-05-01", {"assignments": [{"id": "AS-1", "name": "x", "section": "برا"}]})
    index = store.day_index()
    assert "2026-05-01" in index.recorded()
    assert store.INDEX_STATS["repairs"] == repairs + 1

    path = store.day_path(DAYS[3])
    _write_day(DAYS[3], {"status": {"closed": True}})
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    index = store.day_index()
    assert DAYS[3] not in index.recorded()
    assert index.has(DAYS[3], "day_status")

    store.day_path(DAYS[0]).unlink()
    assert DAYS[0] not in store.day_index()
    assert store.INDEX_STATS["repairs"] == repairs + 3
    assert store.INDEX_STATS["rebuilds"] == rebuilds
    # والقراءة بنطاق بتشوف الحالة الجديدة
    assert _loaded_days(store.load_data([DAYS[0], "2026-05-01"])) == ["2026-05-01"]


def test_corrupt_day_fails_loudly_through_scoped_load(archive):
    store.day_path(DAYS[0]).write_text("{bad", encoding="utf-8")
    store._cache.clear()
    with pytest.raises(store.DataUnreadable):
        store.load_data([DAYS[1]])


# ---------- الكاش ----------

def test_lru_keeps_128_days_and_core_separately(client):
    days = [f"2025-{m:02d}-{d:02d}" for m in range(1, 6) for d in range(1, 29)][:130]
    for day in days:
        _write_day(day, {"assignments": [{"id": "AS-1", "name": day}]})
    store._cache.clear()
    evictions = store._cache.evictions

    store.day_index()
    store.assemble()
    assert len(store._cache.days) == 0, "بناء الفهرس والتجميع مايملوش الكاش"

    data = store.load_data(days)
    assert _loaded_days(data) == days
    assert len(store._cache.days) == store.DAY_CACHE_SIZE == 128
    assert store._cache.evictions == evictions + 2
    assert str(store.day_path(days[0])) not in store._cache.days
    assert str(store.day_path(days[-1])) in store._cache.days
    assert store._cache.core is not None
    assert store._cache.core[0] == str(store.core_file())
    assert str(store.core_file()) not in store._cache.days

    # القراءة من الكاش بتحرّك اليوم لآخر الطابور
    store.load_data([days[2]])
    assert next(reversed(store._cache.days)) == str(store.day_path(days[2]))


def test_cache_holds_bytes_and_reads_never_alias(archive):
    first = store.load_data([DAYS[0]])
    assert all(isinstance(e.packed, bytes) for e in store._cache.days.values())
    assert isinstance(store._cache.core[1].packed, bytes)
    assert all(isinstance(v, bytes) for v in first["_fp"]["originals"].values())

    first["day_assignments"][DAYS[0]][0]["name"] = "متغيّر برّه معاملة"
    first["officers"][0]["name"] = "متغيّر"
    second = store.load_data([DAYS[0]])
    assert second["day_assignments"][DAYS[0]][0]["name"] == "خدمة 0"
    assert second["officers"][0]["name"] == "أحمد محمد"
    assert second["day_assignments"][DAYS[0]] is not first["day_assignments"][DAYS[0]]
