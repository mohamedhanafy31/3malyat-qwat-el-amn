"""الأساس المشترك للمستودعات.

المستودع بياخد نفس الـ`data` المحمّلة وبيشتغل عليها **في مكانها** — مش
طبقة تخزين تانية. `store.with_data()` بيفضل هو اللي ماسك القفل والقراءة
والحفظ؛ المستودع بيشتغل **جوّاه** مش بدله:

    def mutate(data):
        repo = LeaveRepo(data)
        repo.add(leave)
        return jsonify(...)
    return with_data(mutate, retro.status_scope)   # نطاق الأيام صريح دايمًا

## العقد: النموذج نسخة منفصلة

`find()` بترجّع نموذج مبني من السجل المخزّن — **نسخة**، مش إشارة عليه.
تعديل النموذج مابيأثرش على الملف لحد ما تنادي `save()`. ده مقصود: بيخلي
«اقرا، عدّل، تحقق، اكتب» خطوات واضحة بدل التعديل في المكان اللي بيخلي
السجل نص-متعدّل لو التحقق وقع في النص.

## الفهارس

`find_person` القديمة كانت بتمسح أربع قوايم سجل بسجل، وبتتنده جوّه حلقات
(بناء لوحة يوم بينده عليها مرة لكل شخص في كل صف). الفهرس هنا بيتبني مرة
واحدة وبيتخزّن على `data` تحت مفتاح بيبدأ بـ`_` — و`store._write()`
بيشيل المفاتيح دي قبل الحفظ، فما بتخشش الملف.
"""


class Repo:
    """مستودع فوق قايمة سجلات في المستوى الأعلى من `data`."""

    KEY = None            # المفتاح في data
    MODEL = None          # النموذج المقابل
    ID_PREFIX = None      # بادئة المعرّف (من النموذج لو مش محدد)
    ID_WIDTH = 3

    def __init__(self, data):
        self.data = data

    # ---------- الوصول الخام ----------

    def rows(self):
        """القايمة المخزّنة نفسها — للكود اللي لسه ما اتحوّلش."""
        return self.data.setdefault(self.KEY, [])

    def _index(self):
        """{id: سجل خام} — بيتبني مرة ويتعاد بناؤه لو العدد اتغيّر."""
        cache = self.data.get(f"_idx_{self.KEY}")
        rows = self.rows()
        if cache is None or cache.get("_size") != len(rows):
            cache = {"_size": len(rows)}
            for row in rows:
                cache[row.get("id")] = row
            self.data[f"_idx_{self.KEY}"] = cache
        return cache

    def _invalidate(self):
        self.data.pop(f"_idx_{self.KEY}", None)

    # ---------- قراءة ----------

    def all(self):
        return [self.MODEL.from_dict(r) for r in self.rows()]

    def find(self, entity_id):
        raw = self._index().get(entity_id)
        return self.MODEL.from_dict(raw) if raw is not None else None

    def exists(self, entity_id):
        return entity_id in self._index()

    def where(self, **criteria):
        """كل السجلات اللي حقولها بتطابق — مطابقة مساواة بسيطة."""
        return [m for m in self.all()
                if all(getattr(m, k, None) == v for k, v in criteria.items())]

    def count(self):
        return len(self.rows())

    # ---------- كتابة ----------

    def new_id(self):
        """معرّف جديد مايتكررش أبدًا، حتى بعد مسح اللي قبله — العدّاد
        متخزّن في `id_seq` وبيزيد بس."""
        from ..store import reserve_id
        prefix = self.ID_PREFIX or self.MODEL.ID_PREFIX
        width = getattr(self.MODEL, "ID_WIDTH", self.ID_WIDTH)
        return reserve_id(self.data, prefix, self.rows(), width=width)

    def add(self, model):
        """بيضيف السجل ويرجّعه. بيدّي معرّف جديد لو مالوش واحد."""
        if not model.id:
            model.id = self.new_id()
        self.rows().append(model.as_dict())
        self._invalidate()
        return model

    def save(self, model):
        """بيكتب النموذج فوق السجل اللي بنفس المعرّف. بيرجّع False لو
        مالقاش السجل — عشان المستدعي مايفتكرش إنه اتحفظ."""
        raw = self._index().get(model.id)
        if raw is None:
            return False
        raw.clear()
        raw.update(model.as_dict())
        return True

    def remove(self, entity_id):
        rows = self.rows()
        before = len(rows)
        self.data[self.KEY] = [r for r in rows if r.get("id") != entity_id]
        self._invalidate()
        return len(self.data[self.KEY]) != before


class DictRepo(Repo):
    """مستودع فوق قاموس مفهرس بالتاريخ — `{يوم: قيمة}`."""

    def rows(self):
        return self.data.setdefault(self.KEY, {})

    def days(self):
        return sorted(self.rows())

    def peek(self, day):
        """قيمة اليوم من غير ما تعمل مدخل جديد — للقراءة المجردة."""
        return (self.data.get(self.KEY) or {}).get(day)
