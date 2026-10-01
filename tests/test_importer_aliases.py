import json

from importer.aliases import VocabularyItem, collect_phrases, detect_events, propose_alias, service_key


def _vocabulary():
    return [
        VocabularyItem("كهرباء السخنة", "حراسات", "الأهداف", True, "target"),
        VocabularyItem("تدخل سريع", "خارجية", "الخدمات أساسية"),
        VocabularyItem("نوبتجي المعسكر الفرعي", "داخلية", "ضابط عظيم وأمن المعسكر الفرعي", False, "role_slot"),
    ]


def test_service_key_strips_shift_party_article_and_repairs_unique_typo():
    vocabulary = _vocabulary()
    assert service_key('التدخل السريع صبح 8ص "عتاقة"', vocabulary) == "تدخل سريع"
    assert service_key("عمل بهدف السخئة", vocabulary).endswith("سخنه")


def test_alias_matching_and_categories_are_derived_from_vocabulary():
    vocabulary = _vocabulary()
    exact = propose_alias("تدخل سريع ليل", vocabulary)
    assert (exact["canonical"], exact["confidence"], exact["section"]) == (
        "تدخل سريع", "high", "الخدمات أساسية")
    target = propose_alias("عمل بهدف السخئة", vocabulary)
    assert (target["canonical"], target["category"], target["kind"]) == (
        "كهرباء السخنة", "target", "حراسات")
    admin = propose_alias("متابعة أعمال العمليات", vocabulary)
    assert (admin["category"], admin["section"], admin["kind"]) == ("admin_work", "عمل بالإدارة", "")
    slot = propose_alias("نوبجي المعسكر الفرعي", vocabulary)
    assert slot["category"] == "role_slot"
    assert slot["counts_in_summary"] is False


def test_instruction_row_is_note_not_service_phrase():
    records = [{
        "date": "2026-01-01", "role": "afraad", "record_type": "afraad_emergency_row",
        "raw_cells": ["10 مجند حفظ نظام لتأمين المحكمة"], "fields": {"service": ""},
    }]
    phrases, notes = collect_phrases(records, _vocabulary())
    assert not phrases
    assert notes[0]["classification"] == "note"


def test_event_detection_uses_headings_and_only_current_nonstale_documents():
    records = [{
        "date": "2026-09-02", "role": "board", "record_type": "board_label", "path": "board.docx",
        "label": "مباراة قرية عامر 2:30م", "raw_cells": [],
    }, {
        "date": "2025-11-20", "role": "deployment", "record_type": "deployment_header", "path": "plan.docx",
        "raw_cells": ["خطة انتشار يوم 20/11/2025"],
    }, {
        "date": "2025-11-20", "role": "deployment", "record_type": "deployment_row", "path": "plan.docx",
        "raw_cells": ["ارتكاز تجريبي", "فرد"],
    }, {
        "date": "2025-11-21", "role": "match", "record_type": "match_header", "path": "stale.docx",
        "raw_cells": ["مباراة 20/11/2025"],
    }]
    validations = [{"date": "2025-11-21", "role": "match", "path": "stale.docx", "verdict": "quarantine"}]
    events = detect_events(records, validations, {"مباراة ش قرية عامر"})
    assert {row["event title"] for row in events} == {"مباراة ش قرية عامر", "خطة الانتشار"}
    assert next(row for row in events if row["date"] == "2025-11-20")["member rows"] == 1



def test_people_statuses_totals_and_instructions_are_not_services():
    from importer.aliases import _instruction_phrase, _non_service_phrase
    from importer.textnorm import norm
    for value in ("العقيد / احمد سمير", "عقيد", "الرائد", "فرقة", "تدريب دوري", "اجازة عيد", "اجمالي خدمات الطوارئ"):
        assert _non_service_phrase(norm(value)), value
    for value in ("تدخل سريع صبح", "مأمورية امداد", "منطقة حرة", "مجموعة قتالية"):
        assert not _non_service_phrase(norm(value)) and not _instruction_phrase(norm(value)), value
    for value in ("عدد 10 مجند حفظ نظام", "مجند دنك علي ممشي بور توفيق", "1مجند دنك علي ممشي"):
        assert _instruction_phrase(norm(value)), value


def test_event_titles_are_normalized_to_one_spelling():
    from importer.aliases import _tidy_event_title
    assert _tidy_event_title("خدمات خطة الانتشار ليوم الجمعة 6/12/2024") == "خطة الانتشار"
    assert _tidy_event_title("خطه الانتشار") == "خطة الانتشار"
    assert _tidy_event_title('خدمات الماتش "الساعة 12"') == "مباراة"
    assert _tidy_event_title('مباراه منتخب السويس باستاد الجيش "1م "') == "مباراة منتخب السويس باستاد الجيش"
    assert _tidy_event_title("التراحيل") == "التراحيل"


def test_generic_event_title_is_not_snapped_to_a_specific_known_section():
    from importer.aliases import _event_title
    assert _event_title("خدمات المباراه", {"مباراة ش قرية عامر"}) == "مباراة"
    assert _event_title("مباراة قرية عامر", {"مباراة ش قرية عامر"}) == "مباراة ش قرية عامر"


def test_event_decision_is_rebound_when_its_generated_title_changes():
    from importer.aliases import _rebind_event_decisions
    events = [{"date": "2026-09-02", "event title": "مباراة قرية عامر و الرباط"}]
    decisions = {("2026-09-02", "مباراة قرية عامر"): {"date": "2026-09-02", "event title": "مباراة قرية عامر",
                                                       "action": "", "override title": "مباراة ش قرية عامر", "note": ""}}
    _rebind_event_decisions(events, decisions)
    row = decisions[("2026-09-02", "مباراة قرية عامر و الرباط")]
    assert row["override title"] == "مباراة ش قرية عامر" and "أعيد ربطه" in row["note"]


def test_role_blocks_come_from_the_phrase_words():
    from backend.constants import SECTION_GREAT, SECTION_SECURITY, SECTION_SUBCAMP
    from backend.text import norm
    from importer.aliases import role_sections
    cases = {
        "منوب امن فترة ليلية": [SECTION_SECURITY],
        "ضابط عظيم الإدارة فترة صباحية من 9ص وحتي 9م": [SECTION_GREAT],
        "ضابط عظيم وامن الادارة فترة ليلية": [SECTION_GREAT, SECTION_SECURITY],
        "نوبتجى المعسكر الفرعى صبح": [SECTION_SUBCAMP],
        "عمل بالمعسكر الفرعي": [], "إدارة البحث": [], "حملة امن وطني": [],
    }
    assert {text: role_sections(norm(text)) for text in cases} == cases
