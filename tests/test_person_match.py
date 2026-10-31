from importer.person_match import resolve_person


DAY = "2026-08-10"


def _person(ident, name, role="ا.ش", phone="", short_name=""):
    return {"id": ident, "name": name, "role": role, "phone": phone, "short_name": short_name,
            "join_date": "2020-01-01", "leave_date": "", "status": "active"}


def _data(*people, officers=()):
    return {"personnel": list(people), "officers": list(officers), "conscripts": []}


def test_phone_is_decisive_even_when_name_points_elsewhere():
    data = _data(_person("IND-1", "أحمد سعيد", phone="01012345678"),
                 _person("IND-2", "محمود كامل", phone="01112345678"))
    found = resolve_person(data, "محمود كامل 01012345678", DAY)
    assert found.person_id == "IND-1" and found.confidence == "high" and "تليفون" in found.reason


def test_ordered_whole_tokens_with_first_name_link_unique_candidate():
    data = _data(_person("IND-1", "محمد مصطفى أحمد"), _person("IND-2", "طارق حسين علي"))
    found = resolve_person(data, "م.ش/ محمد أحمد", DAY)
    assert found.person_id == "IND-1" and found.confidence == "high"


def test_abd_split_and_letter_variants_are_matched():
    data = _data(_person("IND-1", "عبدالرحمن محمد زكي"), _person("IND-2", "طارق حسين علي"))
    assert resolve_person(data, "عبد الرحمن محمد زكى", DAY).person_id == "IND-1"


def test_typo_or_partial_token_stays_empty():
    data = _data(_person("IND-1", "عبدالرحمن محمد زكي"), _person("IND-2", "طارق حسين علي"))
    assert resolve_person(data, "طارق حسيين", DAY).person_id is None      # كلمة مش كاملة/غلطة
    assert resolve_person(data, "طارق حس", DAY).person_id is None


def test_first_token_must_be_first_name():
    data = _data(_person("IND-1", "أحمد محمد علي"))
    assert resolve_person(data, "محمد علي", DAY).person_id is None


def test_true_tie_stays_empty_and_continuity_does_not_break_it():
    data = _data(_person("IND-1", "أحمد محمد علي"), _person("IND-2", "أحمد محمد حسن"))
    found = resolve_person(data, "أحمد محمد", DAY, neighbouring_ids={"IND-1"})
    assert found.person_id is None and found.reason.startswith("تعادل")


def test_not_on_force_is_excluded():
    gone = _person("IND-1", "أحمد محمد علي")
    gone["leave_date"] = "2026-01-01"
    assert resolve_person(_data(gone), "أحمد محمد", DAY).person_id is None


def test_manual_owner_alias_applies_with_high_confidence():
    data = _data(_person("IND-087", "فارس حماده محمد السيد"), _person("IND-2", "محمد فرنسا"))
    found = resolve_person(data, "محمد فرنسا", DAY)
    assert found.person_id == "IND-087" and found.confidence == "high" and "المالك" in found.reason


def test_nickname_and_fuzzy_are_not_used():
    data = _data(_person("IND-1", "يوسف محمد بكر مصطفي علي"))
    assert resolve_person(data, "مصطفي ابو بكر", DAY).person_id is None
    assert resolve_person(data, "مصطفي بكر", DAY).person_id is None
