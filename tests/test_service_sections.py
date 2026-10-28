from backend.afraad import _time_key
from backend.board import canonical_section_name
from backend.service_sections import block_title, is_special, split_custom_sections


def test_special_classification_normalises_staffing_labels_and_prison_aliases():
    for name in ("فرد + مج", "فرد+مج", "فرد + مج ( داخلي )", "مج + فرد (خارجي)",
                 "فرد", "مج", "تفتيشات", "سجن قوات الأمن", "سجن قوات الامن"):
        assert not is_special(name)
    for name in ("مباراة المصري", "خدمات انتشار الجمعة", "الحدائق والمنتزهات", "خطة الانتشار"):
        assert is_special(name)
    assert canonical_section_name("سجن قوات الامن") == "خدمات سجن قوات الأمن"


def test_block_title_does_not_duplicate_services_prefix():
    assert block_title("مباراة المصري") == "خدمات مباراة المصري"
    assert block_title("خدمات انتشار الجمعة") == "خدمات انتشار الجمعة"
    assert block_title("الخدمات الخاصة") == "الخدمات الخاصة"


def test_service_blocks_keep_ordinary_first_and_special_first_occurrence_order():
    sections = [
        {"name": "مباراة", "rows": [{"name": "م2", "time": "2م"}, {"name": "م8", "time": "8ص"}]},
        {"name": "فرد + مج", "rows": [{"name": "ع", "time": "9ص"}]},
        {"name": "انتشار", "rows": [{"name": "ا", "time": "12ظ"}]},
    ]
    ordinary, special = split_custom_sections(sections, _time_key)
    assert [row["name"] for row in ordinary] == ["ع"]
    assert [section["name"] for section in special] == ["مباراة", "انتشار"]
    assert [row["name"] for row in special[0]["rows"]] == ["م8", "م2"]
