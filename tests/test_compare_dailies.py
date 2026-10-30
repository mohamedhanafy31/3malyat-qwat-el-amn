from io import BytesIO

from docx import Document
from openpyxl import Workbook

from tools.compare_dailies import (
    compare_board,
    compare_counts,
    match_rows,
    normalize_arabic,
)


def _board_doc(rows):
    document = Document()
    table = document.add_table(rows=1, cols=4)
    for index, value in enumerate(("الخدمات الاساسية", "", "الخدمات الطارئة", "")):
        table.rows[0].cells[index].text = value
    for values in rows:
        cells = table.add_row().cells
        for index, value in enumerate(values):
            cells[index].text = value
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _counts_book(entries):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "اعداد الخدمات"
    for cell, value in entries.items():
        sheet[cell] = value
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_normalize_arabic_covers_letters_digits_punctuation_and_placeholders():
    assert normalize_arabic("ألفـى، ١٢") == normalize_arabic("الفي 12")
    assert normalize_arabic("ــــــــ") == ""
    assert normalize_arabic("مدرسة") == normalize_arabic("مدرسه")


def test_match_rows_pairs_duplicate_keys_by_content_not_occurrence():
    archive = [{"service": "راحة", "value": "أحمد"}, {"service": "راحة", "value": "محمد"}]
    system = [{"service": "راحة", "value": "محمد"}, {"service": "راحة", "value": "أحمد"}]
    pairs = match_rows(archive, system, ("service",), value_fields=("value",))
    assert [(a["value"], s["value"]) for a, s in pairs] == [("أحمد", "أحمد"), ("محمد", "محمد")]


def test_match_rows_treats_two_word_name_as_same_identity_as_full_name():
    archive = [{"person": "خالد خلف", "value": "فرقة"}]
    system = [{"person": "خالد خلف الله", "value": "فرقة"}]
    pairs = match_rows(archive, system, ("person",), value_fields=("value",))
    assert pairs == [(archive[0], system[0])]


def test_match_rows_does_not_swap_people_with_same_words_in_different_order():
    archive = [
        {"person": "محمد احمد مصطفي", "work": "أ"},
        {"person": "محمد مصطفي احمد", "work": "ب"},
    ]
    system = list(reversed(archive))
    pairs = match_rows(archive, system, ("person",), value_fields=("work",))
    assert [(left["person"], right["person"]) for left, right in pairs] == [
        (archive[0]["person"], archive[0]["person"]),
        (archive[1]["person"], archive[1]["person"]),
    ]


def test_exact_person_identity_wins_over_similar_shorter_name():
    archive = [
        {"person": "محمد احمد مصطفي عبدالرازق", "work": "عمل بالادارة"},
        {"person": "محمد مصطفي محمد احمد", "work": "احتياطي"},
    ]
    system = [
        {"person": archive[0]["person"], "work": "احتياطي"},
        {"person": archive[1]["person"], "work": "عمل بالادارة"},
    ]
    pairs = match_rows(archive, system, ("person",), value_fields=("work",))
    assert [(left["person"], right["person"]) for left, right in pairs] == [
        (archive[0]["person"], archive[0]["person"]),
        (archive[1]["person"], archive[1]["person"]),
    ]


def test_board_comparator_matches_reordered_service_rows():
    archive = _board_doc([("\u062a\u062f\u062e\u0644 \u0633\u0631\u064a\u0639", "\u0631\u0627\u0626\u062f/ \u0623\u062d\u0645\u062f", "\u0645\u0623\u0645\u0648\u0631\u064a\u0629", "3 \u0645\u062c\u0646\u062f")])
    system = _board_doc([("\u062a\u062f\u062e\u0644 \u0633\u0631\u064a\u0639", "\u0631\u0627\u0626\u062f / \u0627\u062d\u0645\u062f", "\u0645\u0627\u0645\u0648\u0631\u064a\u0647", "\u0663 \u0645\u062c\u0646\u062f")])
    result = compare_board("2026-08-01", BytesIO(archive), system)
    assert result["mismatches"] == []


def test_board_comparator_separates_five_column_packing_from_data():
    archive = _board_doc([
        ("تدخل سريع", "رائد/ أحمد", "نيابة عسكرية 8ص", "فرد + مج"),
        ("الاهداف", "", "مستشفى 9ص", "فرد + مج"),
    ])
    system = _board_doc([
        ("تدخل سريع", "رائد/ أحمد", "مستشفى 9ص", "فرد + مج"),
        ("الاهداف", "", "نيابة عسكرية 8ص", "فرد + مج"),
    ])
    result = compare_board("2026-10-20", BytesIO(archive), system)
    assert result["mismatches"] == []
    assert [item["section"] for item in result["layout_differences"]] == ["five_column_packing"]


def test_counts_comparator_matches_rows_by_service_not_cell_position(tmp_path):
    archive_bytes = _counts_book({"B4": "خدمة أ", "C4": 2, "D4": "خدمة ب", "E4": 3})
    system = _counts_book({"B4": "خدمة ب", "C4": 3, "D4": "خدمة أ", "E4": 2})
    archive = tmp_path / "counts.xlsx"
    archive.write_bytes(archive_bytes)
    result = compare_counts("2026-08-01", archive, system)
    assert result["mismatches"] == []
