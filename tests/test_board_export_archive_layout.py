"""Archive-specific service labels and bottom-aligned special blocks."""

import pytest

from backend.board_export import _emergency_name, _latest_content
from backend.constants import SECTION_BASIC


DAY = "2026-10-11"


def _service(name, *, time="", party="", section="الخدمات الطارئة"):
    return {
        "id": f"S-{section}-{name}-{time}",
        "name": name,
        "label": name,
        "time": time,
        "party": party,
        "section": section,
        "officers": [],
        "personnel": [],
        "conscripts": [],
        "conscript_count": 1,
    }


def _texts(rows):
    return [" | ".join(cell["text"] for cell in row["cells"]) for row in rows]


def _tail_index(rows):
    return next(i for i, row in enumerate(rows)
                if row["kind"] == "tailhead" and "الخوارج" in _texts([row])[0])


@pytest.mark.parametrize(("row", "expected"), [
    (_service("طلبة امداد", time="07:00", party="المديرية"),
     'طلبة امداد 7ص "المديرية"'),
    (_service("مباراة ملعب السلام", time="13:30"), "مباراة ملعب السلام 1.30م"),
    (_service("حملة امن وطنى", time="12:00"), "حملة امن وطنى 12ظ"),
    (_service("حملة أمن وطني", time="00:00"), "حملة أمن وطني 12 ليل"),
    (_service('طلبة امداد 7ص "المديرية"', time="07:00", party='"المديرية"'),
     'طلبة امداد 7ص "المديرية"'),
    (_service("اسم فقط"), "اسم فقط"),
    (_service("", time="09:00"), "9ص"),
    (_service("", party="الاربعين"), '"الاربعين"'),
])
def test_emergency_name_uses_archive_time_place_and_skips_duplicates(row, expected):
    assert _emergency_name(row) == expected


def test_special_and_prison_rows_do_not_gain_time_or_place_suffixes():
    special = _service("مدرجات", time="13:30", party="استاد السويس",
                       section="مباراة استاد السويس")
    prison = _service("تأمين السجن العسكري فترة صباحية", time="08:00", party="السجن",
                      section="خدمات سجن قوات الأمن")
    rows = _latest_content({"date": DAY, "sections": [
        {"name": "مباراة استاد السويس", "type": "services", "rows": [special]},
        {"name": "خدمات سجن قوات الأمن", "type": "services", "rows": [prison]},
    ]})
    text = "\n".join(_texts(rows))
    assert "مدرجات" in text and "مدرجات 1.30م" not in text and '"استاد السويس"' not in text
    assert "تأمين السجن العسكري فترة صباحية" in text
    assert "تأمين السجن العسكري فترة صباحية 8ص" not in text and '"السجن"' not in text


@pytest.mark.parametrize("with_targets", [False, True])
def test_last_special_row_is_immediately_above_outsiders(with_targets):
    sections = [
        {"name": SECTION_BASIC, "type": "services",
         "rows": [_service(f"أساسية {i}") for i in range(5)]},
        {"name": "الخدمات الطارئة", "type": "services",
         "rows": [_service("طارئة", time="08:00")]},
        {"name": "مباراة استاد السويس", "type": "services", "rows": [
            _service("مدرجات الدرجة الأولى", section="مباراة استاد السويس"),
            _service("ارتكاز الحرفيين", section="مباراة استاد السويس"),
        ]},
    ]
    if with_targets:
        sections.append({"name": "الأهداف", "type": "targets", "rows": [
            {"name": "مشرف", "officers": []},
            {"name": "سوميد", "officers": []},
            {"name": "السخنة", "officers": []},
        ]})
    rows = _latest_content({"date": DAY, "sections": sections})
    texts = _texts(rows)
    tail = _tail_index(rows)
    assert "ارتكاز الحرفيين" in texts[tail - 1]
    assert next(i for i, text in enumerate(texts) if "خدمات مباراة استاد السويس" in text) < tail - 1
    assert texts.count(next(text for text in texts if "طارئة 8ص" in text)) == 1
    if with_targets:
        assert any("سوميد" in text for text in texts)


def test_special_block_collision_with_prison_grows_rows_without_overwriting():
    prison = [
        _service("تأمين السجن صباحا", section="خدمات سجن قوات الأمن"),
        _service("تأمين السجن ليلا", section="خدمات سجن قوات الأمن"),
    ]
    base_sections = [
        {"name": "الأهداف", "type": "targets", "rows": [
            {"name": "مشرف", "officers": []}, {"name": "سوميد", "officers": []},
        ]},
        {"name": "خدمات سجن قوات الأمن", "type": "services", "rows": prison},
    ]
    base_rows = _latest_content({"date": DAY, "sections": base_sections})
    special = {"name": "مباراة استاد السويس", "type": "services", "rows": [
        _service("مدرجات", section="مباراة استاد السويس"),
        _service("ارتكاز", section="مباراة استاد السويس"),
    ]}
    rows = _latest_content({"date": DAY, "sections": base_sections + [special]})
    text = "\n".join(_texts(rows))
    assert len(rows) == len(base_rows) + 3  # عنوان الكتلة + صفاها، بلا كتابة فوق السجن
    for value in ("تأمين السجن صباحا", "تأمين السجن ليلا", "مدرجات", "ارتكاز", "سوميد"):
        assert value in text
    assert "ارتكاز" in _texts(rows)[_tail_index(rows) - 1]


def _special(count, name="مباراة استاد السويس"):
    return {"name": name, "type": "services", "rows": [
        _service(f"موقع {i}", section=name) for i in range(count)]}


def test_special_block_shares_rows_with_right_side_instead_of_following_emergency():
    sections = [
        {"name": SECTION_BASIC, "type": "services",
         "rows": [_service(f"أساسية {i}", section=SECTION_BASIC) for i in range(6)]},
        {"name": "الخدمات الطارئة", "type": "services", "rows": [_service("طارئة")]},
        _special(2),
    ]
    rows = _latest_content({"date": DAY, "sections": sections})
    texts = _texts(rows)
    tail = _tail_index(rows)
    assert "موقع 1" in texts[tail - 1] and "موقع 0" in texts[tail - 2]
    # الكتلة بجانب خدمات أساسية وليست بعد آخرها
    assert "أساسية 5" in texts[tail - 1] or "أساسية 5" in texts[tail - 2] \
        or "أساسية 5" in texts[tail - 3]
    base = _latest_content({"date": DAY, "sections": sections[:2]})
    assert len(rows) == len(base)  # لا نمو: الكتلة تشارك صفوف اليمين


def test_collision_with_many_emergency_and_borrowed_targets_row_grows_rows():
    emergency = [_service(f"طارئة {i}") for i in range(6)]
    sections = [
        {"name": "الخدمات الطارئة", "type": "services", "rows": emergency},
        {"name": "الأهداف", "type": "targets",
         "rows": [{"name": "مشرف", "officers": []}, {"name": "سوميد", "officers": []}]},
    ]
    base = _latest_content({"date": DAY, "sections": sections})
    rows = _latest_content({"date": DAY, "sections": sections + [_special(3)]})
    text = "\n".join(_texts(rows))
    assert len(rows) > len(base)
    for i in range(6):
        assert f"طارئة {i}" in text
    for i in range(3):
        assert f"موقع {i}" in text
    texts = _texts(rows)
    assert "موقع 2" in texts[_tail_index(rows) - 1]
    assert sum("خدمات مباراة استاد السويس" in t for t in texts) == 1
