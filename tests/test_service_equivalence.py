import pytest

from backend.service_equivalence import compare_service_names, services_equivalent


@pytest.mark.parametrize("left,right", [
    ("حملة الأمن الوطني", "حملة امن وطنى 12ظ"),
    ("القول المكبر", "قول مكبر"),
    ("ميك", "مايك"),
    ("المحور + المحكمة", "الإفطار + المحور + المحكمة"),
])
def test_owner_equivalent_service_examples(left, right):
    assert services_equivalent(left, right)


def test_known_superset_is_reported_and_unknown_superset_is_not_equated():
    assert compare_service_names("المحور + المحكمة", "الإفطار + المحور + المحكمة").relation == "known-superset"
    result = compare_service_names("المحور", "المحور + المحكمة")
    assert not result.equivalent and result.relation == "uncertain-superset"


def test_unrelated_services_do_not_match():
    assert not services_equivalent("تفتيش فيصل", "ارتكاز قسم فيصل")

