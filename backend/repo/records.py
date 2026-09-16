"""مستودعات سجلات الفترة والكيانات البسيطة.

الراحات والفرق والالتحاقات والمأموريات — كلها قوايم في المستوى الأعلى
بنفس الشكل، فبتاخد نفس الأساس (`Repo`) وبتضيف استعلاماتها بس.
"""
from ..models import Course, CourseTerm, Leave, Mission
from .base import Repo


class LeaveRepo(Repo):
    KEY = "leaves"
    MODEL = Leave

    def _by_person(self):
        """{person_id: [سجلات]} — الفهرس ده بيوفّر مسح كامل لكل ضابط.

        من غيره بناء يومية واحدة بيلف على كل سجلات الراحة لكل ضابط
        (34 × 280 = 9,520 مقارنة للوحة الواحدة).
        """
        cache = self.data.get("_idx_leaves_by_person")
        rows = self.rows()
        if cache is None or cache.get("_size") != len(rows):
            cache = {"_size": len(rows)}
            for raw in rows:
                cache.setdefault(raw.get("person_id"), []).append(raw)
            self.data["_idx_leaves_by_person"] = cache
        return cache

    def _invalidate(self):
        super()._invalidate()
        self.data.pop("_idx_leaves_by_person", None)

    def of_person(self, person_id):
        return [Leave.from_dict(r) for r in self._by_person().get(person_id, [])]

    def on_day(self, person_id, day):
        """راحة الشخص في اليوم ده — أو None."""
        return next((lv for lv in self.of_person(person_id) if lv.covers(day)), None)

    def overlapping(self, leave, ignore_id=None):
        """راحة تانية لنفس الشخص بتتقاطع مع المدى ده."""
        return [lv for lv in self.of_person(leave.person_id)
                if lv.id != ignore_id and lv.start <= leave.end and leave.start <= lv.end]

    def in_range(self, start, end):
        return [lv for lv in self.all() if lv.start <= end and start <= lv.end]

    # ---------- حلّ الاسم ----------

    def names(self):
        """{person_id: الاسم} — من سجل القوة، مش من سجل الراحة.

        الاسم كان متخزّن **جوّه** كل سجل راحة (`leaves[].name`)، فأي تعديل
        اسم في صفحة القوة كان بيسيب الراحات القديمة بالاسم القديم. كان فيه
        كود بيمشي على كل راحات الشخص ويحدّثها بعد كل تعديل — حل لمشكلة
        أصلها إن نفس الحقيقة متخزّنة في مكانين.

        دلوقتي الاسم بيتحلّ هنا وقت القراءة، فهو صحيح دايمًا بالتعريف.
        """
        from .people import PeopleRepo
        cache = self.data.get("_idx_person_names")
        if cache is None:
            people = PeopleRepo(self.data)
            cache = {p.id: p.name for cat in ("officers", "personnel")
                     for p in people.all(cat)}
            self.data["_idx_person_names"] = cache
        return cache

    def named(self, leave):
        """سجل الراحة كـdict مع اسم صاحبه — الشكل اللي الواجهة بتستقبله."""
        out = leave.as_dict()
        out["name"] = self.names().get(leave.person_id, "")
        return out

    def rows_with_names(self):
        return [self.named(lv) for lv in self.all()]

    def name_of(self, person_id):
        return self.names().get(person_id, "")

    # ---------- كتابة ----------

    def sort(self):
        """ترتيب ثابت: بتاريخ البداية ثم باسم صاحب الراحة.

        الاسم بيتحلّ من سجل القوة وقت الترتيب بدل ما يتقرا من حقل مخزّن —
        نفس الترتيب الظاهر، من غير الحقل المكرّر.
        """
        names = self.names()
        self.rows().sort(key=lambda l: (l.get("start", ""),
                                        names.get(l.get("person_id"), "")))
        self._invalidate()

    def add(self, leave):
        added = super().add(leave)
        self.sort()
        return added

    def replace(self, leave):
        """بيكتب السجل فوق اللي بنفس المعرّف ويعيد الترتيب."""
        if not self.save(leave):
            return False
        self.sort()
        return True


class CourseRepo(Repo):
    KEY = "courses"
    MODEL = Course

    def by_id(self):
        return {c.id: c for c in self.all()}


class CourseTermRepo(Repo):
    KEY = "course_terms"
    MODEL = CourseTerm
    ID_WIDTH = 4

    def of_officer(self, officer_id):
        """كل التحاقات ضابط، الأحدث الأول."""
        return sorted((t for t in self.all() if t.officer_id == officer_id),
                      key=lambda t: t.start or "", reverse=True)

    def on_day(self, officer_id, day):
        """التحاق الضابط بفرقة في اليوم ده — أو None."""
        return next((t for t in self.of_officer(officer_id) if t.covers(day)), None)

    def of_course(self, course_id):
        return [t for t in self.all() if t.course_id == course_id]

    def overlapping(self, term, ignore_id=None):
        return [t for t in self.of_officer(term.officer_id)
                if t.id != ignore_id and t.start and t.end
                and t.start <= term.end and term.start <= t.end]


class MissionRepo(Repo):
    KEY = "missions"
    MODEL = Mission

    def open(self):
        return [m for m in self.all() if m.open]

    def of_officer(self, officer_id):
        return [m for m in self.all() if officer_id in (m.member_ids or [])]
