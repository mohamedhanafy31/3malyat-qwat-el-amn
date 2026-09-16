"""حدود الطبقات — المسارات ما بتلمسش التخزين مباشرة.

القاعدة دي هي كل قيمة المرحلة ١: طول ما المسار بيقرا `data["officers"]
["active"]` بإيده، أي تغيير في شكل التخزين بيلزمه تعديل في كل مسار
بيلمسه — وده اللي خلّى حذف سجل واحد ينسى مكانين. بعد ما كل وصول بقى من
المستودع، شكل التخزين بقى معروف في مكان واحد.

الاختبار ده بيقفل القاعدة عشان ما ترجعش تتكسر بالتدريج. لو مسار جديد
احتاج حاجة مش موجودة في المستودعات، الحل إضافة دالة للمستودع — مش فتح
`data` في المسار.
"""
import re
from pathlib import Path

import pytest

ROUTES = Path(__file__).resolve().parent.parent / "backend" / "routes"

# أي وصول مباشر لمفتاح تخزين على `data`: بالنص، أو بمتغيّر، أو بدوال
# القاموس. `data.get("...")` داخلة كمان — قراءة برضه وصول مباشر.
DIRECT_ACCESS = re.compile(
    r"""\bdata\s*(?:
          \[                      # data["..."] / data[category]
        | \.get\s*\(
        | \.setdefault\s*\(
        | \.pop\s*\(
        | \.items\s*\(
        | \.keys\s*\(
        )""", re.VERBOSE)


def route_files():
    return sorted(p for p in ROUTES.glob("*.py") if p.name != "__init__.py")


@pytest.mark.parametrize("path", route_files(), ids=lambda p: p.name)
def test_route_never_touches_storage_directly(path):
    offenders = [f"  {path.name}:{n}: {line.strip()}"
                 for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
                 if DIRECT_ACCESS.search(line)]
    assert not offenders, (
        "المسار بيلمس التخزين مباشرة بدل ما يعدّي من المستودع:\n"
        + "\n".join(offenders))


def test_the_rule_is_actually_enforceable():
    """يتأكد إن التعبير بيمسك الأنماط اللي المفروض يمسكها — من غير كده
    الاختبار فوق ممكن يعدّي وهو مش بيفحص حاجة."""
    caught = ['data["officers"]', 'data[category]["active"]',
              'data.get("leaves")', 'data.setdefault("missions", [])',
              'data.pop("day_officers", None)']
    assert all(DIRECT_ACCESS.search(line) for line in caught)

    allowed = ["def mutate(data):", "return with_data(mutate)",
               "data = load_data()", "payload.get('name')",
               "Repos(data).people.find(pid)"]
    assert not any(DIRECT_ACCESS.search(line) for line in allowed)
