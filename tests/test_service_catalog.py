"""دليل الخدمات — التوليد من قالب اعداد الخدمات، وبعدها CRUD حر."""
import io

import pytest

# أصغر PNG صحيح (2×2 بكسل أحمر) — كفاية لاختبار رفع الصور من غير ملف حقيقي
_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000002000000020802000000fdd49a73"
    "0000001649444154789c63fccfc0c0c0c0c0c4c0c0c0c0c000000d1d01036ac29be"
    "90000000049454e44ae426082"
)


def _add_template(client, **over):
    body = {"name": "خدمة", "block": "صباحية", "count": 1, "party": ""}
    body.update(over)
    r = client.post("/api/counts/template/entries", json=body)
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def _seed(client):
    r = client.post("/api/service-catalog/seed")
    assert r.status_code == 201, r.get_json()
    return r.get_json()["entries"]


def test_catalog_starts_empty_and_unseeded(client):
    d = client.get("/api/service-catalog").get_json()
    assert d["entries"] == [] and d["seeded"] is False


def test_seeding_marks_a_service_in_both_blocks_as_both_periods(client):
    _add_template(client, name="نقطة تفتيش", block="صباحية", count=3, weapon="آلي")
    _add_template(client, name="نقطة تفتيش", block="ليلية", count=3, weapon="آلي")

    entries = _seed(client)
    row = next(e for e in entries if e["name"] == "نقطة تفتيش")
    assert row["period"] == "صباحية وليلية"
    assert row["count"] == 3
    assert row["weapon"] == "آلي"


def test_seeding_marks_a_morning_only_service_correctly(client):
    _add_template(client, name="كنيسة العذراء", block="صباحية", count=1)

    entries = _seed(client)
    row = next(e for e in entries if e["name"] == "كنيسة العذراء")
    assert row["period"] == "صباحية بس"


def test_seeding_marks_a_night_only_service_correctly(client):
    _add_template(client, name="ارتكاز المحافظة", block="ليلية", count=1)

    entries = _seed(client)
    row = next(e for e in entries if e["name"] == "ارتكاز المحافظة")
    assert row["period"] == "ليلية بس"


def test_seeding_prefers_the_morning_count_when_the_two_blocks_disagree(client):
    """«قول السلام» حالة حقيقية من الأرشيف — قوامها مختلف بين الصباحية
    والليلية، والدليل بياخد قيمة الصباحية والمشغّل يظبطها بعد كده."""
    _add_template(client, name="قول السلام", block="صباحية", count=2)
    _add_template(client, name="قول السلام", block="ليلية", count=4)

    entries = _seed(client)
    row = next(e for e in entries if e["name"] == "قول السلام")
    assert row["count"] == 2


def test_seeding_ignores_the_recurring_emergency_block(client):
    """بلوك «طوارئ» مالوش قوام هنا — مصدره اليومية التفصيلية مش الدليل."""
    _add_template(client, name="حملة أمن وطني", block="طوارئ", count=4)

    entries = _seed(client)
    assert not any(e["name"] == "حملة أمن وطني" for e in entries)


def test_seeding_twice_is_rejected(client):
    _add_template(client)
    _seed(client)
    r = client.post("/api/service-catalog/seed")
    assert r.status_code == 409


def test_add_edit_and_delete_a_manual_entry(client):
    r = client.post("/api/service-catalog/entries", json={
        "name": "خدمة جديدة", "period": "صباحية بس", "kind": "داخلية",
        "count": 2, "weapon": "خرطوش", "instructions": "تعليمات تجريبية",
    })
    assert r.status_code == 201, r.get_json()
    entry = r.get_json()
    assert entry["period"] == "صباحية بس" and entry["kind"] == "داخلية"

    r = client.patch(f"/api/service-catalog/entries/{entry['id']}", json={"count": 5})
    assert r.status_code == 200 and r.get_json()["count"] == 5

    r = client.delete(f"/api/service-catalog/entries/{entry['id']}")
    assert r.status_code == 200

    remaining = client.get("/api/service-catalog").get_json()["entries"]
    assert not any(e["id"] == entry["id"] for e in remaining)


def test_seeded_entries_default_to_no_command(client):
    """قالب اعداد الخدمات مالوش مفهوم «برئاسة» أصلًا — الدليل بيبدأ من
    غير رئاسة والمشغّل بيحدد بنفسه لكل خدمة بعد كده."""
    _add_template(client, name="نقطة تفتيش")
    entries = _seed(client)
    row = next(e for e in entries if e["name"] == "نقطة تفتيش")
    assert row["has_command"] is False
    assert row["command_officers"] == 0 and row["command_individuals"] == 0


def test_a_service_can_be_commanded_by_officers_and_individuals_together(client):
    """برئاسة مش يعني ضابط أو فرد على حدة — ممكن يبقى فيها الاتنين
    مع بعض في نفس الوقت (كام ضابط وكام فرد)."""
    r = client.post("/api/service-catalog/entries", json={
        "name": "دورية", "has_command": True,
        "command_officers": 1, "command_individuals": 2, "count": 3,
    })
    assert r.status_code == 201, r.get_json()
    entry = r.get_json()
    assert entry["has_command"] is True
    assert entry["command_officers"] == 1
    assert entry["command_individuals"] == 2
    assert entry["count"] == 3

    r = client.post("/api/service-catalog/entries", json={
        "name": "خدمة", "command_officers": "غير رقم",
    })
    assert r.status_code == 400


def test_turning_off_command_resets_officer_and_individual_counts(client):
    """حتى لو الطلب بعت أعداد في نفس اللحظة، لازم ترجع صفر لو الخدمة
    اتحطت «من غير رئاسة» — مفيش قائم رئاسة من غير رئاسة أصلًا."""
    r = client.post("/api/service-catalog/entries", json={
        "name": "دورية", "has_command": True,
        "command_officers": 1, "command_individuals": 1,
    })
    entry_id = r.get_json()["id"]

    r = client.patch(f"/api/service-catalog/entries/{entry_id}",
                     json={"has_command": False, "command_officers": 5, "command_individuals": 5})
    assert r.status_code == 200, r.get_json()
    entry = r.get_json()
    assert entry["has_command"] is False
    assert entry["command_officers"] == 0 and entry["command_individuals"] == 0


def test_tags_are_saved_on_the_entry_and_added_to_the_global_tag_list(client):
    r = client.post("/api/service-catalog/entries", json={
        "name": "دورية", "tags": ["الخدمات الداخلية", " المحور ", ""],
    })
    assert r.status_code == 201, r.get_json()
    entry = r.get_json()
    assert entry["tags"] == ["الخدمات الداخلية", "المحور"]

    d = client.get("/api/service-catalog").get_json()
    assert "الخدمات الداخلية" in d["service_tags"]
    assert "المحور" in d["service_tags"]


def test_a_tag_added_once_is_not_duplicated_in_the_global_list(client):
    client.post("/api/service-catalog/entries", json={"name": "أ", "tags": ["خدمات فيصل"]})
    client.post("/api/service-catalog/entries", json={"name": "ب", "tags": ["خدمات فيصل"]})
    d = client.get("/api/service-catalog").get_json()
    assert d["service_tags"].count("خدمات فيصل") == 1


def test_seeding_guesses_post_type_from_the_name_prefix(client):
    _add_template(client, name="ارتكاز الحي الحكومي")
    _add_template(client, name="قول السلام")
    _add_template(client, name="كنيسة العذراء مريم")

    entries = _seed(client)
    by_name = {e["name"]: e for e in entries}
    assert by_name["ارتكاز الحي الحكومي"]["post_type"] == "ارتكاز"
    assert by_name["قول السلام"]["post_type"] == "قول"
    assert by_name["كنيسة العذراء مريم"]["post_type"] == ""


def test_post_type_can_be_set_manually_and_is_validated(client):
    r = client.post("/api/service-catalog/entries", json={"name": "خدمة", "post_type": "ارتكاز"})
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["post_type"] == "ارتكاز"

    r = client.post("/api/service-catalog/entries", json={"name": "خدمة", "post_type": "غير صحيح"})
    assert r.status_code == 400


def test_adding_without_a_name_is_rejected(client):
    r = client.post("/api/service-catalog/entries", json={"name": ""})
    assert r.status_code == 400


def test_invalid_period_and_kind_are_rejected(client):
    r = client.post("/api/service-catalog/entries", json={"name": "خدمة", "period": "غير صحيح"})
    assert r.status_code == 400

    r = client.post("/api/service-catalog/entries", json={"name": "خدمة", "kind": "غير صحيح"})
    assert r.status_code == 400


def test_a_seeded_entry_has_empty_location_fields_by_default(client):
    _add_template(client, name="نقطة تفتيش")
    entries = _seed(client)
    row = next(e for e in entries if e["name"] == "نقطة تفتيش")
    assert row["location_text"] == "" and row["location_images"] == []


def test_location_text_can_be_set_and_is_capped_in_length(client):
    r = client.post("/api/service-catalog/entries", json={"name": "خدمة"})
    entry_id = r.get_json()["id"]

    r = client.patch(f"/api/service-catalog/entries/{entry_id}",
                     json={"location_text": "جنب المدرسة الابتدائية"})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["location_text"] == "جنب المدرسة الابتدائية"

    r = client.patch(f"/api/service-catalog/entries/{entry_id}",
                     json={"location_text": "x" * 501})
    assert r.status_code == 400


def test_uploading_an_image_attaches_it_and_it_is_downloadable(client):
    r = client.post("/api/service-catalog/entries", json={"name": "خدمة"})
    entry_id = r.get_json()["id"]

    r = client.post(f"/api/service-catalog/entries/{entry_id}/images",
                    data={"image": (io.BytesIO(_TINY_PNG), "map.png")},
                    content_type="multipart/form-data")
    assert r.status_code == 201, r.get_json()
    entry = r.get_json()
    assert len(entry["location_images"]) == 1
    filename = entry["location_images"][0]
    assert filename.startswith(entry_id)

    r = client.get(f"/uploads/service-catalog/{filename}")
    assert r.status_code == 200
    assert r.data == _TINY_PNG


def test_uploading_without_a_file_is_rejected(client):
    r = client.post("/api/service-catalog/entries", json={"name": "خدمة"})
    entry_id = r.get_json()["id"]
    r = client.post(f"/api/service-catalog/entries/{entry_id}/images",
                    data={}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_uploading_a_disallowed_extension_is_rejected(client):
    r = client.post("/api/service-catalog/entries", json={"name": "خدمة"})
    entry_id = r.get_json()["id"]
    r = client.post(f"/api/service-catalog/entries/{entry_id}/images",
                    data={"image": (io.BytesIO(b"not really a pdf"), "map.pdf")},
                    content_type="multipart/form-data")
    assert r.status_code == 400


def test_deleting_an_image_removes_it_from_the_entry_and_disk(client):
    r = client.post("/api/service-catalog/entries", json={"name": "خدمة"})
    entry_id = r.get_json()["id"]
    r = client.post(f"/api/service-catalog/entries/{entry_id}/images",
                    data={"image": (io.BytesIO(_TINY_PNG), "map.png")},
                    content_type="multipart/form-data")
    filename = r.get_json()["location_images"][0]

    r = client.delete(f"/api/service-catalog/entries/{entry_id}/images/{filename}")
    assert r.status_code == 200
    assert r.get_json()["location_images"] == []

    r = client.get(f"/uploads/service-catalog/{filename}")
    assert r.status_code == 404


def test_deleting_a_nonexistent_image_404s(client):
    r = client.post("/api/service-catalog/entries", json={"name": "خدمة"})
    entry_id = r.get_json()["id"]
    r = client.delete(f"/api/service-catalog/entries/{entry_id}/images/nope.png")
    assert r.status_code == 404


def test_uploading_to_a_missing_entry_leaves_no_orphan_file(client):
    """404 (الخدمة غير موجودة) بعد ما الملف اتكتب على القرص فعلًا —
    مالوش داعي يفضل ملف يتيم من غير أي مرجع ليه."""
    from backend import service_catalog as catalog_lib

    before = set(catalog_lib.images_dir().glob("*")) if catalog_lib.images_dir().exists() else set()
    r = client.post("/api/service-catalog/entries/CAT-999/images",
                    data={"image": (io.BytesIO(_TINY_PNG), "map.png")},
                    content_type="multipart/form-data")
    assert r.status_code == 404
    after = set(catalog_lib.images_dir().glob("*")) if catalog_lib.images_dir().exists() else set()
    assert after == before


def test_a_failed_save_removes_the_just_uploaded_file(client, monkeypatch):
    """أي استثنا غير متوقع وقت الحفظ (قرص ممتلئ مثلًا) بيمسح الملف اللي
    اتكتب لحظة قبل كده، مش يسيبه يتيم."""
    from backend import service_catalog as catalog_lib
    from backend.routes import service_catalog as routes_catalog

    r = client.post("/api/service-catalog/entries", json={"name": "خدمة"})
    entry_id = r.get_json()["id"]

    def boom(fn, *_scope):
        raise RuntimeError("قرص ممتلئ (محاكاة)")

    monkeypatch.setattr(routes_catalog, "with_data", boom)
    with pytest.raises(RuntimeError):
        client.post(f"/api/service-catalog/entries/{entry_id}/images",
                   data={"image": (io.BytesIO(_TINY_PNG), "map.png")},
                   content_type="multipart/form-data")

    left_over = list(catalog_lib.images_dir().glob(f"{entry_id}-*"))
    assert left_over == []


def test_deleting_an_entry_also_deletes_its_images_from_disk(client):
    r = client.post("/api/service-catalog/entries", json={"name": "خدمة"})
    entry_id = r.get_json()["id"]
    r = client.post(f"/api/service-catalog/entries/{entry_id}/images",
                    data={"image": (io.BytesIO(_TINY_PNG), "map.png")},
                    content_type="multipart/form-data")
    filename = r.get_json()["location_images"][0]

    r = client.delete(f"/api/service-catalog/entries/{entry_id}")
    assert r.status_code == 200

    r = client.get(f"/uploads/service-catalog/{filename}")
    assert r.status_code == 404
