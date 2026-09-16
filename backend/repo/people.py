"""مستودع القوة — الضباط والأفراد، على القوة وفي الأرشيف.

الشكل المخزّن: **قايمة واحدة لكل فئة** (`officers` و`personnel`)،
و`status` هو اللي بيفرّق بين اللي على القوة واللي في الأرشيف. القايمتين
القديمتين (`active`/`archive`) بقوا **عرض محسوب** — `bucket()`.

قبل هجرة 008 كانوا أربع قوايم فعليّة، وكل سجل شايل `status` كمان: نفس
الحقيقة متخزّنة مرتين من غير أي ضمان لاتفاقهم. النقل بين القوة والأرشيف
كان تلات خطوات (شيل من قايمة، ضيف في التانية، رتّب)، ودلوقتي بقى تغيير
حقل واحد.

الفهرس مش رفاهية: بناء لوحة يوم واحد بينده `locate` مرة لكل شخص في كل
صف، والنسخة القديمة (`people.find_person`) كانت بتمسح كل السجلات من
الأول في كل نداء — آلاف المقارنات للوحة الواحدة، بتتكرر في كل طلب.
"""
from ..models import ACTIVE, ARCHIVED, Individual, Officer, of_category
from ..utils import command_priority_map, rank_key

CATEGORIES = ("officers", "personnel")


class PeopleRepo:
    """الضباط والأفراد مع بعض — بديل `people.find_person`."""

    def __init__(self, data):
        self.data = data

    # ---------- الوصول الخام ----------

    def people(self, category):
        """القايمة المخزّنة للفئة — **قايمة واحدة**، و`status` هو اللي
        بيفرّق بين اللي على القوة واللي في الأرشيف.

        قبل كده كانوا قايمتين (`active` و`archive`) **و** كل سجل شايل
        `status` كمرآة ليهم: نفس الحقيقة متخزّنة مرتين، ومحدش يضمن
        اتفاقهم. سجل في `active` بـ`status: "archived"` كان سلوكه غير
        معرّف — بيظهر في صفحة القوة وبيتحسب متأرشف في مكان تاني.

        بيطبّع الشكل القديم لو لقاه. `store._read()` بيطبّع أصلًا، بس
        المستودع بيتبني على `data` جاية من أي حتة (سكربت، اختبار، هجرة)،
        فالتطبيع هنا بيخلي السلوك واحد مهما كان مدخل الوصول.
        """
        current = self.data.get(category)
        if not isinstance(current, list):
            current = as_roster(current)
            self.data[category] = current
        return current

    def bucket(self, category, bucket):
        """**عرض للقراءة فقط** — قايمة جديدة مفلترة بالحالة، مش المخزّنة.

        الإضافة والحذف والترتيب كلهم ليهم دوال صريحة (`add`، `add_raw`،
        `move`، `remove`، `sort`). الفرق ده مهم: قبل التوحيد كان
        `bucket(...).append(x)` بيكتب فعلًا، ودلوقتي هيضيع في الفراغ.
        """
        want = ACTIVE if bucket == "active" else ARCHIVED
        return [p for p in self.people(category) if _status_of(p) == want]

    def _index(self):
        """{id: (سجل خام, فئة, قايمة)} — بيتبني مرة لكل نسخة بيانات."""
        cache = self.data.get("_idx_people")
        size = sum(len(self.people(c)) for c in CATEGORIES)
        if cache is None or cache.get("_size") != size:
            cache = {"_size": size}
            for category in CATEGORIES:
                for raw in self.people(category):
                    bucket = "active" if _status_of(raw) == ACTIVE else "archive"
                    cache[raw.get("id")] = (raw, category, bucket)
            self.data["_idx_people"] = cache
        return cache

    def _invalidate(self):
        self.data.pop("_idx_people", None)
        # فهرس الأسماء اللي `LeaveRepo` بيحلّ بيه اسم صاحب الراحة. لازم
        # يقع مع أي تغيير في القوة، وإلا طلب بيعدّل اسم وبيقرا الراحات بعده
        # في نفس العملية بيرجّع الاسم القديم.
        self.data.pop("_idx_person_names", None)

    # ---------- قراءة ----------

    def locate(self, person_id):
        """-> (سجل خام, فئة, قايمة) أو (None, None, None).

        نفس توقيع `people.find_person` بالظبط عشان التحويل يبقى تدريجي.
        """
        found = self._index().get(person_id)
        return found if found else (None, None, None)

    def find(self, person_id):
        """-> نموذج Officer/Individual أو None."""
        raw, category, _ = self.locate(person_id)
        return of_category(category).from_dict(raw) if raw is not None else None

    def find_in(self, person_id, category):
        """زي `find` بس بترجّع None لو الشخص من الفئة التانية — بيمنع
        تكليف فرد في خانة ضابط والعكس."""
        raw, found, _ = self.locate(person_id)
        if raw is None or found != category:
            return None
        return of_category(category).from_dict(raw)

    def list(self, category, bucket):
        model = of_category(category)
        return [model.from_dict(r) for r in self.bucket(category, bucket)]

    def active(self, category):
        return self.list(category, "active")

    def archived(self, category):
        return self.list(category, "archive")

    def all(self, category):
        return self.active(category) + self.archived(category)

    # ---------- وصول خام (للكود اللي بيعدّل السجل في مكانه) ----------

    def raw_all(self, category):
        """السجلات المخزّنة نفسها — مش نسخ.

        `all()` بترجّع نماذج (نسخ منفصلة)، وده الصح لأغلب الاستخدامات. بس
        الكود القديم بيعدّل السجل اللي بيرجعله ويتوقّع إن التعديل يتكتب،
        فمحتاج الإشارة الأصلية. الدالتين موجودين عن قصد بأسماء مختلفة عشان
        الفرق يبان في موقع النداء.
        """
        return self.bucket(category, "active") + self.bucket(category, "archive")

    def raw_on_force(self, day, category="officers"):
        """زي `on_force` بس بترجّع السجلات الخام مرتبة بنفس الترتيب."""
        out = [p for p in self.raw_all(category)
               if not ((p.get("join_date") or "") > day
                       or ((p.get("leave_date") or "") and day > p["leave_date"]))]
        if category == "officers":
            priority = command_priority_map(self.data)
            out.sort(key=lambda p: rank_key(p, priority))
        return out

    def on_force(self, day, category="officers"):
        """اللي كانوا على القوة في اليوم ده — **مش** الحاليين.

        الضابط المتأرشف لازم يفضل ظاهر في الأيام اللي كان فيها بالقوة،
        عشان تعديل يوم قديم يشتغل وتتطبع بياناته زي ما كانت.
        """
        people = [p for p in self.all(category) if p.on_force(day)]
        if category == "officers":
            priority = command_priority_map(self.data)
            people.sort(key=lambda p: rank_key(p.as_dict(), priority))
        return people

    def ids_on_force(self, day, category="officers"):
        return {p.id for p in self.on_force(day, category)}

    # ---------- كتابة ----------

    def code_taken(self, category, code, ignore_id=None):
        """رقم الأقدمية مستخدم على القوة؟ — الأرشيف مستثنى عن قصد.

        الرقم بيترجع للاستخدام بعد ما صاحبه يخرج من القوة، وده السلوك
        التشغيلي الفعلي؛ التفرقة بين السجلين بتبقى بالـid مش بالرقم.
        """
        return any(str(p.get("code")) == str(code) and p.get("id") != ignore_id
                   for p in self.bucket(category, "active"))

    def new_id(self, category):
        """معرّف فريد على مستوى الفئة كلها (القوة + الأرشيف).

        الفحص كان على القوة بس، فضابط بيتشال للأرشيف وبديله بيتسجّل بنفس
        رقم الأقدمية في نفس اليوم كانوا بياخدوا **نفس الـid بالظبط**.
        """
        from ..store import reserve_id
        prefix = "OFF" if category == "officers" else "IND"
        return reserve_id(self.data, prefix, self.people(category))

    def add(self, person, category=None):
        category = category or person.CATEGORY
        if not person.id:
            person.id = self.new_id(category)
        person.status = ACTIVE
        return self.add_raw(category, person.as_dict()) and person

    def add_raw(self, category, raw):
        """بيضيف سجل خام على القوة — للكود اللي لسه بيبني dict بإيده."""
        raw.setdefault("status", ACTIVE)
        self.people(category).append(raw)
        self._invalidate()
        self.sort(category)
        return raw

    def save(self, person):
        raw, _, _ = self.locate(person.id)
        if raw is None:
            return False
        raw.clear()
        raw.update(person.as_dict())
        self._invalidate()      # الاسم أو الحالة ممكن يكونوا اتغيّروا
        return True

    def move(self, person_id, to_bucket):
        """ينقل السجل بين القوة والأرشيف. بيرجّع السجل الخام أو None.

        بقى **تغيير حالة** بس — مفيش نقل بين قايمتين. ده اللي كان بيخلي
        العملية دي محتاجة تلات خطوات (شيل من دي، حط في دي، رتّب دي).
        """
        raw, category, bucket = self.locate(person_id)
        if raw is None or bucket == to_bucket:
            return None
        raw["status"] = ACTIVE if to_bucket == "active" else ARCHIVED
        self._invalidate()
        self.sort(category)
        return raw

    def remove(self, person_id):
        """حذف نهائي. التنظيف المرجعي **مش** هنا — شوف
        `references.cascade_delete()`."""
        raw, category, _ = self.locate(person_id)
        if raw is None:
            return None
        self.data[category] = [r for r in self.people(category)
                               if r.get("id") != person_id]
        self._invalidate()
        return category

    def sort(self, category):
        """ترتيب القايمة الموحّدة: اللي على القوة الأول، بعدين الأرشيف.

        داخل كل جزء الترتيب زي ما كان بالظبط — الضباط بالرتبة (وقيادة
        الإدارة أولًا)، الأفراد بالاسم، والأرشيف بتاريخ الخروج من الأحدث.
        الترتيب متحفوظ في القايمة نفسها عشان `bucket()` ترجّع نفس الترتيب
        اللي القايمتين كانوا بيدّوه من غير ما تعيد ترتيب في كل نداء.
        """
        priority = command_priority_map(self.data) if category == "officers" else {}

        # العنصر الأول (0 للقوة / 1 للأرشيف) بيفصل المجموعتين، فالمقارنة
        # بينهم بتقف عنده ومابتوصلش لباقي العناصر — يعني كل مجموعة تقدر
        # يكون ليها مفتاح بشكل وأنواع مختلفة من غير أي تعارض.
        def key(p):
            if _status_of(p) == ARCHIVED:
                return (1, _descending(p.get("leave_date", "")),
                        _descending(p.get("name", "")))
            if category == "officers":
                return (0,) + tuple(rank_key(p, priority))
            return (0, p.get("name", ""), p.get("code", ""))

        self.people(category).sort(key=key)


def as_roster(value):
    """قايمة أشخاص واحدة، أيًا كان شكل المصدر.

    بتقبل الشكل القديم (`{"active": [...], "archive": [...]}`) والجديد
    (قايمة). في الشكل القديم الحالة بتتاخد من القايمة اللي السجل كان فيها،
    مش من حقل `status` — لأن القايمة هي اللي كانت بتتعرض فعلًا لو الاتنين
    اختلفوا، فده بيحافظ على السلوك الظاهر بالظبط.
    """
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return []
    out = []
    for bucket, status in (("active", ACTIVE), ("archive", ARCHIVED)):
        for person in value.get(bucket) or []:
            out.append({**person, "status": status})
    return out


def _status_of(raw):
    """حالة السجل — الافتراضي «على القوة» للسجلات اللي مالهاش حقل."""
    return raw.get("status") or ACTIVE


def _descending(value):
    """مفتاح ترتيب بيقلب اتجاه النص — عشان جزء يترتب تنازلي جوّه ترتيب
    تصاعدي عام من غير ما نقسّم القايمة."""
    return tuple(-ord(c) for c in str(value or ""))


class OfficerRepo(PeopleRepo):
    """اختصار للضباط — نفس المستودع بفئة مثبّتة."""
    CATEGORY = "officers"
    MODEL = Officer

    def all(self, category=None):
        return super().all(self.CATEGORY)

    def active(self, category=None):
        return super().active(self.CATEGORY)

    def find(self, person_id):
        return self.find_in(person_id, self.CATEGORY)

    def on_force(self, day, category=None):
        return super().on_force(day, self.CATEGORY)


class IndividualRepo(OfficerRepo):
    CATEGORY = "personnel"
    MODEL = Individual
