"""النص المستورد من الأرشيف (`source_manning`) ما يغلبش الداتا المربوطة بالسيستم."""
from backend.board_export import _compact_manning
from tools.link_imported_names import apply, name_words, plan


def test_name_words_drop_rank_time_and_phone():
    assert name_words("م.اول / أحمد فوزي حتى الساعة 3م") == ["احمد", "فوزي"]
    assert name_words('ا.ش/ محمد السيد 01012345678') == ["محمد", "السيد"]


def test_imported_strength_is_used_while_it_matches_the_linked_data():
    row = {"source_manning": "2فرد + 2 مج", "personnel": [{"name": "أ"}, {"name": "ب"}],
           "conscript_count": 2}
    assert _compact_manning(row) == "2فرد + 2 مج"


def test_edited_conscripts_replace_the_stale_imported_strength():
    row = {"source_manning": "2فرد + 2 مج", "personnel": [{"name": "أ"}, {"name": "ب"}],
           "conscripts": [{"class": "دونك", "count": 5}]}
    text = _compact_manning(row)
    assert "5دونك" in text and "2 مج" not in text


def test_imported_strength_is_kept_when_nothing_is_linked():
    assert _compact_manning({"source_manning": "2فرد + 2 مج"}) == "2فرد + 2 مج"


def _data():
    return {
        "officers": [{"id": "OFF-1", "name": "احمد فوزي احمد السيد", "role": "ملازم أول"}],
        "personnel": [{"id": "IND-1", "name": "محمد الشبراخيتي", "role": "معاون"},
                      {"id": "IND-2", "name": "علي جمال صابر", "role": "أمين شرطة"},
                      {"id": "IND-3", "name": "علي جمال ناصف", "role": "أمين شرطة"}],
        "day_afraad": {"2026-09-07": {"AFB-01": {"morning_name": "م.ش/ محمد الشبراخيتي",
                                                  "night_name": "معاون/ علي جمال"}}},
        "day_assignments": {"2026-09-26": [{"id": "AS-1", "name": "قول",
                                            "source_manning": "م.اول / أحمد فوزي حتى الساعة 3م"}]},
    }


def test_linker_links_unique_names_and_reports_ambiguous_ones():
    data = _data()
    changes, unresolved = plan(data)
    assert {(c["field"], c["id"]) for c in changes} == {
        ("morning_person_id", "IND-1"), ("officer_ids", "OFF-1")}
    assert "معاون/ علي جمال" in unresolved["multi"]
    apply(data, changes)
    assert data["day_afraad"]["2026-09-07"]["AFB-01"]["morning_person_id"] == "IND-1"
    assert "night_person_id" not in data["day_afraad"]["2026-09-07"]["AFB-01"]
    assert data["day_assignments"]["2026-09-26"][0]["officer_ids"] == ["OFF-1"]
