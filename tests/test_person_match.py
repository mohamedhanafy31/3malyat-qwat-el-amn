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


def test_rank_and_ordered_tokens_break_officer_tie():
    officers = (_person("OFF-1", "محمد مصطفى أحمد", "مقدم"),
                _person("OFF-2", "محمد مصطفى علي", "عقيد"))
    found = resolve_person(_data(officers=officers), "مقدم / محمد مصطفى", DAY, role="officer")
    assert found.person_id == "OFF-1"


def test_abd_split_and_typo_are_matched():
    data = _data(_person("IND-1", "عبدالرحمن محمد زكي"), _person("IND-2", "طارق حسين علي"))
    assert resolve_person(data, "عبد الرحمن محمد زكى", DAY).person_id == "IND-1"
    assert resolve_person(data, "طارق حسيين", DAY).person_id == "IND-2"


def test_true_tie_stays_empty():
    data = _data(_person("IND-1", "أحمد محمد علي"), _person("IND-2", "أحمد محمد حسن"))
    found = resolve_person(data, "أحمد محمد", DAY)
    assert found.person_id is None and found.reason.startswith("تعادل")

