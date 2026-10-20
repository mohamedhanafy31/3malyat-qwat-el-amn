import pytest

from backend.constants import PERSONNEL_FAMILIES
from backend.labels import (first_words, officer_label, personnel_label,
                             personnel_rank_abbr, person_label)


@pytest.mark.parametrize("family", sorted(PERSONNEL_FAMILIES))
def test_every_personnel_family_has_the_archive_prefix(family):
    expected = "م.ش" if family == "معاون" else "ا.ش"
    assert personnel_rank_abbr(family + " شرطة") == expected


def test_personnel_label_uses_three_words_and_normalizes_spacing():
    assert personnel_label({"role": "معاون شرطة ثالث", "name": "  محمدـ   عطية منصور نصار "}) == "م.ش/ محمد عطية منصور"
    assert personnel_label({"role": "أمين شرطة", "name": "شريف صلاح"}) == "ا.ش/ شريف صلاح"


def test_missing_personnel_role_is_safe():
    assert personnel_label({"name": "اسم فرد"}) == "اسم فرد"
    assert first_words("  واحد   اثنان ثلاثة أربعة", 3) == "واحد اثنان ثلاثة"


def test_officer_short_name_and_fallback():
    assert officer_label({"role": "رائد", "name": "الاسم الكامل هنا", "short_name": "ابراهيم ابوالفرج"}) == "رائد/ ابراهيم ابوالفرج"
    assert officer_label({"role": "رائد", "name": "الاسم الكامل هنا", "short_name": ""}) == "رائد/ الاسم الكامل"
    assert officer_label({"role": "ملازم أول", "name": "فلان"}, full=True) == "م.اول/ فلان"


def test_dispatches_by_category():
    assert person_label({"role": "رقيب", "name": "فرد طويل الاسم"}, "personnel") == "ا.ش/ فرد طويل الاسم"
    assert person_label({"role": "نقيب", "name": "ضابط طويل الاسم", "short_name": "مختصر"}, "officers") == "نقيب/ مختصر"
