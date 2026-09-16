"""المستودعات — الطريق الوحيد للوصول للبيانات.

القاعدة بعد المرحلة ١: **مافيش مسار في `routes/` بيلمس `data["..."]`
مباشرة.** المسار بيبني المستودع اللي محتاجه من الـ`data` اللي
`with_data()` مدّهاله، وبيشتغل بالنماذج.

    def mutate(data):
        people = PeopleRepo(data)
        officer = people.find(person_id)
        if not officer:
            raise AbortRequest((jsonify({"error": "غير موجود."}), 404))
        officer.post = payload["post"]
        errors = officer.validate()
        if errors:
            raise AbortRequest((jsonify({"error": errors[0]}), 400))
        people.save(officer)
        return jsonify(officer.as_dict())

`Repos` تحت بتجمّعهم كلهم في كائن واحد للمسارات اللي محتاجة أكتر من
مستودع، عشان ما يبقاش فيه خمس سطور بناء في أول كل دالة.
"""
from .base import DictRepo, Repo
from .config import ChangeRepo, ConfigRepo
from .days import DayRepo
from .people import IndividualRepo, OfficerRepo, PeopleRepo
from .records import (
    CourseRepo, CourseTermRepo, LeaveRepo, MissionRepo, ServiceRepo,
)


class Repos:
    """كل المستودعات على نفس الـ`data` — بتتبني كسول عند أول استخدام."""

    _MAP = {
        "people": PeopleRepo, "officers": OfficerRepo, "individuals": IndividualRepo,
        "leaves": LeaveRepo, "services": ServiceRepo,
        "courses": CourseRepo, "terms": CourseTermRepo,
        "days": DayRepo, "missions": MissionRepo,
        "changes": ChangeRepo, "config": ConfigRepo,
    }

    def __init__(self, data):
        self.data = data
        self._cache = {}

    def __getattr__(self, name):
        if name not in self._MAP:
            raise AttributeError(name)
        if name not in self._cache:
            self._cache[name] = self._MAP[name](self.data)
        return self._cache[name]

    def snapshot(self, exclude=()):
        """كل البيانات المنشورة كـdict — للنداء الشامل `/api/data`.

        بيشيل المفاتيح اللي بتبدأ بـ`_` (فهارس المستودعات) بنفس منطق
        `store._write()` بالظبط. معرفة «أنهي مفاتيح داخلية» دي معرفة
        تخزين، فمكانها هنا مش في المسار.
        """
        skip = set(exclude)
        return {k: v for k, v in self.data.items()
                if not k.startswith("_") and k not in skip}


__all__ = [
    "Repo", "DictRepo", "Repos",
    "PeopleRepo", "OfficerRepo", "IndividualRepo",
    "LeaveRepo", "ServiceRepo", "CourseRepo", "CourseTermRepo", "MissionRepo",
    "DayRepo", "ConfigRepo", "ChangeRepo",
]
