"""يومية تشغيل الضباط + جدول الإجمالي — **عرض محسوب** على تكليفات اليوم.

مفيش أي تخزين هنا: الجدول كله بيتبني من `day_assignments` و`day_officers`
والراحات، فمستحيل يختلف عن اللوحة لأن الاتنين بيقروا من نفس المكان.

جدول الإجمالي في الوورد (موجود في يوميات 17/8 وطالع، 22 يوم):

    أصل القوة | خارجية (صباحية|ليلية|+N بحث) | داخلية (صباحية|ليلية)
    | طبية (موجود|راحة) | خوارج (تقصيرة|راحة|طارئة|غياب|مرضي|فرقة|انتداب)
    | الحراسات المشددة | الصافي (N) + الأسماء

**كل ضابط في خانة واحدة بس** — مجموع الخانات لازم يساوي أصل القوة، وده
مثبت في الوورد (34 في كل الأيام المفحوصة). عشان كده الترتيب اللي تحت
مهم: الضابط بياخد أول خانة تنطبق عليه.
"""
from .assignments import assignments_of, officer_state, services_by_id
from .constants import LEAVE_BUCKET, MEDICAL_POSTS, SHIFTS
from .leaves import leave_on
from .people import effective, officers_on
from .text import norm


def is_medical_post(post):
    """منصب ضابط عيادة/منتدب من القطاع الطبي — بيتقارن بعد التطبيع."""
    flat = norm(post)
    return any(key in flat for key in MEDICAL_POSTS)

# ترتيب الأولوية — أول قاعدة تنطبق هي اللي بتاخد الضابط.
# الترتيب ده مقيس على الـ22 يوم اللي فيهم جدول إجمالي في الوورد؛ أي تغيير
# فيه لازم يعدّي على tools/calibrate_summary.py الأول.
PRIORITY = ("حالة مكتوبة (خوارج)", "طبية", "راحة (خوارج)", "تقصيرة",
            "حراسات", "داخلية/خارجية", "صافي")

# لما الضابط يكون على أكتر من خدمة في نفس الخانة (صباحية وليلية مثلًا)،
# دي الفترة اللي بتتحسب. مجموع الجدول لازم يفضل = أصل القوة، فمينفعش
# يتحسب مرتين. الوورد نفسه مش قاطع هنا، فالقرار متجمّع في مكان واحد.
PREFERRED_SHIFT = "صباحية"


def _shift_of(items):
    """الفترة المعتمدة من بين تكليفات الضابط في نفس الخانة."""
    shifts = [sh for _, sh in items if sh in SHIFTS]
    if not shifts:
        return PREFERRED_SHIFT
    return PREFERRED_SHIFT if PREFERRED_SHIFT in shifts else shifts[0]


def _empty_summary(force):
    return {
        "أصل القوة": force,
        "خارجية": {"صباحية": 0, "ليلية": 0, "بحث": 0},
        "داخلية": {"صباحية": 0, "ليلية": 0},
        "طبية": {"موجود": 0, "راحة": 0},
        "خوارج": {k: 0 for k in ("تقصيرة", "راحة", "طارئة", "غياب",
                                  "مرضي", "فرقة", "انتداب")},
        "حراسات": 0,
        "صافي": 0,
    }


def _bucket(kinds, leave, state, medical, search_attached):
    """-> (المجموعة، الخانة الفرعية) لضابط واحد. القواعد بترتيب PRIORITY."""
    # حالة مكتوبة بالإيد لليوم ده بالذات بتغلب أي افتراض
    status = state.get("status") or ""
    if status:
        # انتداب/غياب/مرضي/فرقة/طارئة — كلها خانات موجودة في جدول الوورد
        return ("خوارج", status)

    # ضابط العيادة بيفضل في عمود «الطبية» حتى وهو في راحة — الوورد بيكتب
    # «راحة» في خانة الطبية مش في خانة الخوارج (يومية 31/8: محمود عبد الله
    # تشغيله «عمل» → طبية/موجود، ومحمد وليد «راحة» → طبية/راحة).
    if medical:
        return ("طبية", "راحة" if leave else "موجود")

    if leave:
        return ("خوارج", LEAVE_BUCKET.get(leave["type"], "راحة"))
    if state.get("taqseera"):
        return ("خوارج", "تقصيرة")

    if any(kind == "حراسات" for kind, _ in kinds):
        return ("حراسات", None)

    internal = [(k, sh) for k, sh in kinds if k == "داخلية"]
    external = [(k, sh) for k, sh in kinds if k == "خارجية"]
    # وسم «+N بحث» تابع لجهة تشغيل الضابط مش لنوع الخدمة: الوورد كتبه في
    # 14 يوم كان فيهم رئيس مباحث الإدارة على خدمات خارجية عادية، ومكتبوش
    # في اليوم الوحيد اللي كان فيه على «ضابط مباحث السجن العسكري».
    if search_attached and external:
        return ("خارجية", "بحث")
    if internal:
        return ("داخلية", _shift_of(internal))
    if external:
        return ("خارجية", _shift_of(external))
    return ("صافي", None)


def summarise(data, day):
    """يومية الضباط كاملة: صف لكل ضابط كان على القوة + جدول الإجمالي."""
    services = services_by_id(data)
    officers = officers_on(data, day)
    medical_ids = set(data.get("medical_officers") or [])

    s = _empty_summary(len(officers))
    net_names, rows = [], []

    for o in officers:
        eff = effective(o, day)
        state = officer_state(data, day, o["id"])
        leave = leave_on(data, o["id"], day)

        items = []
        for a in assignments_of(data, day, o["id"]):
            svc = services.get(a.get("service_id"))
            if not svc:
                continue
            items.append({"assignment_id": a["id"], "id": svc["id"], "name": svc["name"],
                          "kind": svc.get("kind", "خارجية"), "shift": a.get("shift", ""),
                          "section": a.get("section", "")})
        kinds = [(it["kind"], it["shift"]) for it in items]
        medical = (o["id"] in medical_ids
                   or is_medical_post(eff["post"])
                   or any(k == "طبية" for k, _ in kinds))

        group, sub = _bucket(kinds, leave, state, medical, eff["search_attached"])
        if sub is None:
            s[group] += 1
            if group == "صافي":
                net_names.append(f'{eff["role"]}/ {o.get("name", "")}')
        else:
            s[group][sub] += 1

        rows.append({
            "id": o["id"], "name": o.get("name", ""),
            "role": eff["role"], "post": eff["post"], "section": eff["section"],
            "search_attached": eff["search_attached"],
            "group": group, "bucket": sub,
            "services": items,
            "taqseera": bool(state.get("taqseera")),
            "status": state.get("status", ""),
            "leave": ({"type": leave["type"], "start": leave["start"], "end": leave["end"],
                       "return_date": leave["return_date"]} if leave else None),
            "note": state.get("note", ""),
            # كان بالقوة يومها لكنه خرج بعد كده — للتوضيح في اليوميات القديمة
            "later_left": o.get("leave_date", "") or None,
        })

    counted = (sum(s["خارجية"].values()) + sum(s["داخلية"].values())
               + sum(s["طبية"].values()) + sum(s["خوارج"].values())
               + s["حراسات"] + s["صافي"])
    s["net_names"] = net_names
    s["counted"] = counted
    s["balanced"] = counted == s["أصل القوة"]
    return {"date": day, "summary": s, "rows": rows}
