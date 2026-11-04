import json
from io import BytesIO
from urllib.parse import quote, unquote

from docx import Document

from backend import special_formation
from backend.special_formation_export import (BREAK_HEIGHT, PAGE_ROOM, SPACER_HEIGHT, build_docx,
                                               is_oversized, page_starts, table_height)

DAY = "2026-10-20"
MATCH = "مباراة المصري * البنك الاهلي"


def _data():
    return {
        "officers": [{"id": "OFF-001", "name": "أحمد محمد علي", "role": "مقدم", "status": "active"}],
        "personnel": [{"id": "IND-001", "name": "هاني محمد ابراهيم سالم", "role": "امين شرطة", "status": "active"}],
        "day_assignments": {DAY: [
            {"id": "A1", "name": "مدرجات الدرجة الاولي", "section": MATCH, "officer_ids": ["OFF-001"],
             "conscript_count": 3, "weapon": "رياضي", "time": "2م", "party": "استاد السويس"},
            {"id": "A2", "name": "ملاحظة الحالة", "section": MATCH, "personnel_ids": ["IND-001"],
             "conscript_count": 2, "weapon": "الي + خرطوش"},
            {"id": "A3", "name": "مرافقة الجماهير", "section": MATCH, "conscript_count": 0},
            {"id": "A4", "name": "طارئة", "section": "الخدمات الطارئة", "conscript_count": 4},
            {"id": "A5", "name": "تفتيش", "section": "تفتيشات", "conscript_count": 1},
            {"id": "A6", "name": "قديم", "section": "فرد + مج (خارجي)", "conscript_count": 1},
            {"id": "A7", "name": "قول", "section": "خطة الانتشار", "conscript_count": 5, "weapon": "فض"},
        ]},
    }


def test_sections_are_only_the_custom_events_of_the_day():
    found = special_formation.sections(_data(), DAY)
    assert [item["name"] for item in found] == [MATCH, "خطة الانتشار"]
    assert found[0] == {"name": MATCH, "posts": 3, "conscripts": 6}


def test_build_gives_head_labels_slot_weapons_and_warnings():
    payload = special_formation.build(_data(), DAY, MATCH)
    third, second, first = payload["posts"]   # من الأقل عددًا للأكبر
    assert first["head"] == "مقدم/ أحمد محمد" and first["weapons"] == ["رياضي"] * 3
    assert second["head"].endswith("هاني محمد ابراهيم") and second["weapons"] == ["آلي", "خرطوش"]
    assert third["count"] == 1   # مفيش عدد ولا قوام: خانة مجند فاضية
    assert any("مرافقة الجماهير" in warning for warning in payload["warnings"])
    assert payload["totals"] == {"posts": 3, "conscripts": 6}


def test_unknown_or_excluded_section_raises():
    for section in ("مش موجودة", "تفتيشات", "الخدمات الطارئة"):
        try:
            special_formation.build(_data(), DAY, section)
        except LookupError:
            continue
        raise AssertionError(section)


def test_slots_come_only_from_the_count_field():
    data = _data()
    # القوام مش بيتحسب: العدد من خانة «عدد المجندين» بس، وخانة فاضية لو مش مكتوب.
    data["day_assignments"][DAY][2]["conscripts"] = [{"class": "مج", "count": 2}]
    posts = special_formation.build(data, DAY, MATCH)["posts"]
    assert next(post for post in posts if post["name"] == "مرافقة الجماهير")["count"] == 1
    data["day_assignments"][DAY][2]["conscript_count"] = 4
    posts = special_formation.build(data, DAY, MATCH)["posts"]
    assert next(post for post in posts if post["name"] == "مرافقة الجماهير")["count"] == 4


def test_docx_is_a4_portrait_rtl_tables_with_numbered_slots():
    document = Document(build_docx(special_formation.build(_data(), DAY, MATCH)))
    section = document.sections[0]
    assert section.page_width < section.page_height
    tables = document.tables
    # كل خدمة في جدول لوحدها: م | الخدمة | التسليح، وخانة لكل مجند.
    assert [len(table.columns) for table in tables] == [3, 3, 3]
    assert [len(table.rows) for table in tables] == [2, 3, 4]
    header = [cell.text for cell in tables[2].rows[0].cells]
    assert header[0] == "م" and header[2] == "التسليح"
    assert "مدرجات الدرجة الاولي" in header[1] and "مقدم/ أحمد محمد" in header[1]
    assert [tables[2].rows[i].cells[0].text for i in (1, 2, 3)] == ["1.", "2.", "3."]
    assert tables[2].rows[1].cells[2].text == "رياضي"
    assert tables[0]._tbl.tblPr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}bidiVisual") is not None


def test_route_downloads_one_file_per_event_and_ops_lists_events(client, data_file):
    stored = json.loads(data_file.read_text())
    stored.setdefault("day_assignments", {})[DAY] = _data()["day_assignments"][DAY]
    data_file.write_text(json.dumps(stored, ensure_ascii=False))
    listed = client.get(f"/api/ops/{DAY}").get_json()["special_formations"]
    assert [item["name"] for item in listed] == [MATCH, "خطة الانتشار"]
    response = client.get(f"/api/ops/{DAY}/special-formation.docx?section={quote(MATCH)}")
    assert response.status_code == 200
    name = unquote(response.headers["Content-Disposition"].split("filename*=")[-1].removeprefix("UTF-8''"))
    assert name == "خط تشكيل مباراة المصري   البنك الاهلي.docx".replace("   ", " ")
    assert Document(BytesIO(response.data)).tables
    assert client.get(f"/api/ops/{DAY}/special-formation.docx?section=x").status_code == 404


def test_special_regularity_is_landscape_and_filtered_to_one_group(client, data_file):
    stored = json.loads(data_file.read_text())
    stored.setdefault("day_assignments", {})[DAY] = _data()["day_assignments"][DAY]
    data_file.write_text(json.dumps(stored, ensure_ascii=False))
    response = client.get(f"/api/ops/{DAY}/special-regularity.docx?section={quote(MATCH)}")
    assert response.status_code == 200
    name = unquote(response.headers["Content-Disposition"].split("filename*=")[-1].removeprefix("UTF-8''"))
    assert name == "يومية انتظام مباراة المصري البنك الاهلي.docx"
    document = Document(BytesIO(response.data))
    section = document.sections[0]
    assert section.page_width > section.page_height
    assert len(document.tables) == 1          # جدول الخدمات بس، من غير جدول الضباط
    services = [row.cells[1].text for row in document.tables[0].rows[1:]]
    assert sorted(services) == sorted(["مدرجات الدرجة الاولي", "ملاحظة الحالة", "مرافقة الجماهير"])
    header = " ".join(p.text for p in section.header.paragraphs)
    assert "يومية انتظام خدمات " + MATCH in header
    other = client.get(f"/api/ops/{DAY}/special-regularity.docx?section={quote('خطة الانتشار')}")
    assert [row.cells[1].text for row in Document(BytesIO(other.data)).tables[0].rows[1:]] == ["قول"]
    for bad in ("x", "الخدمات الطارئة", "تفتيشات"):
        assert client.get(f"/api/ops/{DAY}/special-regularity.docx?section={quote(bad)}").status_code == 404



W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _post(name, count, head="", weapons=None):
    return {"name": name, "head": head, "count": count, "weapons": weapons or [], "time": "", "party": ""}


def _payload(*counts):
    return {"posts": [_post(f"خدمة {i}", count) for i, count in enumerate(counts)]}


def _pages(posts):
    starts, pages = page_starts(posts), [[]]
    for index, post in enumerate(posts):
        if index in starts:
            pages.append([])
        pages[-1].append(post["count"])
    return pages


def test_posts_go_from_smallest_to_largest_and_ties_keep_board_order():
    data = _data()
    data["day_assignments"][DAY] = [
        {"id": f"A{i}", "name": name, "section": MATCH, "conscript_count": count}
        for i, (name, count) in enumerate([("ج", 5), ("أ", 1), ("د", 2), ("ب", 1)])]
    posts = special_formation.build(data, DAY, MATCH)["posts"]
    assert [post["name"] for post in posts] == ["أ", "ب", "د", "ج"]


def test_pages_keep_strict_order_and_never_overflow():
    posts = [_post(str(i), count) for i, count in enumerate([1, 1, 2, 2, 3, 3, 4, 5, 6, 8, 10, 12, 15, 20])]
    assert _pages(posts) == [[1, 1, 2, 2, 3, 3], [4, 5, 6, 8], [10, 12], [15], [20]]
    starts, used = page_starts(posts), 0
    for index, post in enumerate(posts):
        used = (BREAK_HEIGHT if index in starts else used + SPACER_HEIGHT if index else 0) + table_height(post)
        assert used <= PAGE_ROOM


def test_docx_keeps_each_table_whole_with_exact_rows_and_breaks_between_tables():
    document = Document(build_docx(_payload(15, 16, 17)))
    breaks = [p for p in document.element.body.iter(f"{W}p") if p.find(f"{W}pPr/{W}pageBreakBefore") is not None]
    assert len(breaks) == 2 and all(p.getparent() is document.element.body for p in breaks)
    for table in document.tables:
        rows = table._tbl.findall(f"{W}tr")
        for index, row in enumerate(rows):
            assert row.find(f"{W}trPr/{W}cantSplit") is not None
            assert row.find(f"{W}trPr/{W}trHeight").get(f"{W}hRule") == "exact"
            keep = [p.find(f"{W}pPr/{W}keepNext") is not None for p in row.iter(f"{W}p")]
            assert all(keep) if index < len(rows) - 1 else not any(keep)
    assert document.element.body[-2].tag == f"{W}p"     # فقرة بعد آخر جدول، مش جدول فوق sectPr


def test_a_post_bigger_than_a_page_starts_fresh_and_repeats_its_header():
    posts = [_post("صغير", 2), _post("كبير", 45), _post("بعده", 1)]
    assert is_oversized(posts[1])
    assert page_starts(posts) == {1, 2}
    big = Document(build_docx({"posts": posts})).tables[1]._tbl.findall(f"{W}tr")
    assert big[0].find(f"{W}trPr/{W}tblHeader") is not None
    assert not any(p.find(f"{W}pPr/{W}keepNext") is not None for row in big[1:] for p in row.iter(f"{W}p"))
    data = _data()
    data["day_assignments"][DAY][0]["conscript_count"] = 45
    assert any("أكبر من صفحة" in w for w in special_formation.build(data, DAY, MATCH)["warnings"])


def test_a_long_head_grows_the_row_instead_of_being_clipped():
    short = _post("خدمة", 1, head="مقدم/ أحمد")
    long = _post("خدمة باسم طويل جدا جدا جدا جدا جدا جدا جدا جدا جدا", 1,
                 head=" + ".join(["مقدم/ أحمد محمد"] * 5))
    assert table_height(long) > table_height(short)
    heights = Document(build_docx({"posts": [long]})).tables[0]._tbl.findall(f"{W}tr")[0]
    assert int(heights.find(f"{W}trPr/{W}trHeight").get(f"{W}val")) > 1000
