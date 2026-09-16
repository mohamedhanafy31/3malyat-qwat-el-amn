"""مستودع اليوم — الوحدة اللي بتجمّع الخمس مفاتيح المفهرسة بالتاريخ.

    day_assignments[day]   day_officers[day]   day_status[day]
    service_counts[day]    day_confirm[day]

الخمسة دول 77% من حجم الملف وبيكبروا للأبد (~11 كيلو/يوم). المستودع ده
بيخليهم يتقروا ويتكتبوا كوحدة واحدة، وده اللي بيخلي تقسيم الملف لشهور في
المرحلة ٤ تغيير **جوّه الملف ده بس** — الباقي بينده `get(day)` /
`save(day)` وخلاص.

عشان كده الواجهة هنا مكتوبة على «اليوم» كوحدة، حتى لما ده بيبان زيادة عن
اللزوم دلوقتي: القراءة الجزئية (`assignments(day)`) موجودة للسرعة، بس
العمليات اللي بتعدّل بتمرّ من `get`/`save`.
"""
from ..models import Assignment, CountEntry, Day, DayStatus, OfficerDayState

ASSIGNMENTS = "day_assignments"
OFFICER_STATES = "day_officers"
STATUS = "day_status"
COUNTS = "service_counts"
CONFIRM = "day_confirm"


class DayRepo:
    def __init__(self, data):
        self.data = data

    # ---------- وصول خام لكل مفتاح ----------

    def _map(self, key):
        return self.data.setdefault(key, {})

    def _peek(self, key, day, default=None):
        return (self.data.get(key) or {}).get(day, default)

    def dates(self):
        """كل يوم فيه أي بيانات — من أي مفتاح من الخمسة."""
        seen = set()
        for key in (ASSIGNMENTS, OFFICER_STATES, STATUS, COUNTS, CONFIRM):
            seen |= set(self.data.get(key) or {})
        return sorted(seen)

    def assignment_dates(self):
        """الأيام اللي فيها تكليفات مسجّلة بس.

        مختلفة عن `dates()` عن قصد: الواجهة بتستخدم القايمة دي لتحديد آخر
        يوم فيه يومية، ويوم فيه حالة ضابط واحدة أو قفل من غير أي تكليف
        **مش** يوم شغل — ضمّه كان هيخلي «آخر يوم» يقع على يوم فاضي.
        """
        return sorted(self.data.get(ASSIGNMENTS) or {})

    # ---------- قراءة جزئية (للعرض السريع) ----------

    def assignments(self, day):
        return [Assignment.from_dict(r) for r in self._peek(ASSIGNMENTS, day, [])]

    def officer_states(self, day):
        return {oid: OfficerDayState.from_dict(s)
                for oid, s in (self._peek(OFFICER_STATES, day, {}) or {}).items()}

    def state_of(self, day, officer_id):
        raw = (self._peek(OFFICER_STATES, day, {}) or {}).get(officer_id)
        return OfficerDayState.from_dict(raw or {})

    def assignments_of(self, day, person_id):
        return [a for a in self.assignments(day) if a.has(person_id)]

    def status(self, day):
        return DayStatus.from_dict(self._peek(STATUS, day, {}) or {})

    # ---------- التجميعة الكاملة ----------

    def get(self, day):
        entry = self._peek(CONFIRM, day) or {}
        stored_counts = self._peek(COUNTS, day)
        return Day(
            date=day,
            assignments=self.assignments(day),
            officer_states=self.officer_states(day),
            status=self.status(day),
            # None معناه «لسه على القالب» — مختلف عن قايمة فاضية
            count_entries=([CountEntry.from_dict(e) for e in stored_counts["entries"]]
                           if stored_counts is not None else None),
            confirmed_at=entry.get("at", ""),
            confirmed_by=entry.get("by", ""),
        )

    def save(self, day_obj):
        """بيكتب التجميعة كلها. المفاتيح الفاضية بتتشال بدل ما تتخزّن
        مدخلات فاضية بتكبّر الملف من غير معنى."""
        day = day_obj.date
        self._write_list(ASSIGNMENTS, day, [a.as_dict() for a in day_obj.assignments])
        self._write_map(OFFICER_STATES, day, {
            oid: s.as_dict() for oid, s in day_obj.officer_states.items()
            if not s.empty})
        status = day_obj.status.as_dict()
        self._write_map(STATUS, day, status if status else {})
        if day_obj.count_entries is not None:
            self._map(COUNTS)[day] = {"entries": [e.as_dict() for e in day_obj.count_entries]}

    def _write_list(self, key, day, rows):
        store = self._map(key)
        if rows:
            store[day] = rows
        else:
            store.pop(day, None)

    _write_map = _write_list

    # ---------- تعديلات موضعية ----------

    def add_assignment(self, day, assignment):
        """بيضيف صف تكليف. المعرّف نطاقه اليوم بس (`next_id` مش
        `reserve_id`) — إعادة استخدام رقم اتمسح في نفس اليوم مالهاش أثر
        بره اليوم ده."""
        from ..store import next_id
        rows = self._map(ASSIGNMENTS).setdefault(day, [])
        if not assignment.id:
            assignment.id = next_id(rows, "AS", width=4)
        rows.append(assignment.as_dict())
        return assignment

    def save_assignment(self, day, assignment):
        for raw in self._map(ASSIGNMENTS).get(day, []):
            if raw.get("id") == assignment.id:
                raw.clear()
                raw.update(assignment.as_dict())
                return True
        return False

    def remove_assignment(self, day, assignment_id):
        store = self._map(ASSIGNMENTS)
        rows = store.get(day, [])
        kept = [r for r in rows if r.get("id") != assignment_id]
        if len(kept) == len(rows):
            return False
        if kept:
            store[day] = kept
        else:
            store.pop(day, None)
        return True

    def set_state(self, day, officer_id, state):
        """حالة الضابط. السجل بيتشال لما يفضّى، واليوم بيتشال لما يفضى
        من كل الحالات."""
        store = self._map(OFFICER_STATES).setdefault(day, {})
        if state.empty:
            store.pop(officer_id, None)
        else:
            store[officer_id] = state.as_dict()
        if not store:
            self._map(OFFICER_STATES).pop(day, None)
        return state

    def clear(self, day):
        """يمسح كل بيانات اليوم من الخمس مفاتيح."""
        for key in (ASSIGNMENTS, OFFICER_STATES, STATUS, COUNTS, CONFIRM):
            (self.data.get(key) or {}).pop(day, None)

    def reset_counts(self, day):
        """يشيل نسخة اليوم من ورقة اعداد الخدمات — اليوم بيرجع للقالب.

        بيلمس اليوم ده بس؛ القالب وباقي الأيام ما بيتغيّروش.
        """
        return (self.data.get(COUNTS) or {}).pop(day, None) is not None

    # ---------- تنظيف مرجعي ----------

    def detach_person(self, person_id, key):
        """يشيل شخص من كل التكليفات في كل الأيام. `key` إما
        `officer_ids` أو `personnel_ids`. بيرجّع عدد الصفوف المتأثرة."""
        touched = 0
        for rows in (self.data.get(ASSIGNMENTS) or {}).values():
            for raw in rows:
                ids = raw.get(key) or []
                if person_id in ids:
                    raw[key] = [i for i in ids if i != person_id]
                    touched += 1
        return touched

    def drop_officer_states(self, officer_id):
        """يشيل حالات ضابط من كل الأيام، وبيشيل اليوم لو فضي بعدها."""
        store = self.data.get(OFFICER_STATES) or {}
        touched = 0
        for day in list(store):
            if store[day].pop(officer_id, None) is not None:
                touched += 1
            if not store[day]:
                store.pop(day)
        return touched
