"""تأكيد اليومية التفصيلية — الحفظ بيكتب، والتأكيد بيعتمد ويسجّل.

قبل كده كل حفظ في خانة كان بيكتب سطر في سجل التغييرات فورًا. عمليًا
المشغّل بيفضل يلعب في اليومية طول اليوم — يكتب اسم غلط ويصلّحه، يحط ضابط
ويشيله، يجرّب توزيعة ويرجع فيها — فالسجل كان بيمتلئ بمسوّدات مالهاش أي
معنى تشغيلي، والتغيير الحقيقي بيضيع وسطها.

دلوقتي فيه خطوتين مفصولتين:

    حفظ   — بيكتب في `day_assignments` على طول، وبيظهر في كل اليوميات
            (اللوحة، يومية الضباط، دفتر ٤٣، اعداد الخدمات) لأنها كلها
            عروض محسوبة على نفس السجل. **ومابيسجّلش أي حاجة.**

    تأكيد — بيقارن اليومية الحالية باللقطة المعتمدة الأخيرة، وبيسجّل
            **الفرق** بينهم في سجل التغييرات بلحظة التأكيد، وبيحفظ
            اللقطة الجديدة كخط أساس للمرة الجاية.

فالسطر في السجل بيبقى «نقيب/ فلان: كان «تدخل سريع ليل» ← بقى «أمن المعسكر
ليل»» بوقت التأكيد — مش خمس سطور حفظ متتالية بأوقات متفرقة.

التأكيد ينفع يتعمل أكتر من مرة في اليوم عادي؛ كل مرة بتسجّل اللي اتغيّر
من آخر تأكيد بس، والتأكيد اللي مالوش أي فرق بيتسجّل كـ«إعادة تأكيد».

اللقطة المعتمدة بتتخزّن في `data["day_confirm"][day]`، ومحدودة بآخر
`MAX_SNAPSHOT_DAYS` يوم — من غير السقف ده هي بتضاعف حجم `day_assignments`
في الملف مع الوقت من غير فايدة، لأن اللقطة القديمة قيمتها الوحيدة إنها
خط أساس للتأكيد الجاي.

المبدأ ده (حفظ بلا تسجيل، تأكيد بيسجّل الفرق) خاص **بتكليفات الخدمة**
بس — الحقيقة الوحيدة اللي فيها «مسوّدات» فعلية بيرجع فيها المشغّل كتير
في نفس اليوم. باقي الكيانات (`backend/routes/leaves.py`،
`backend/routes/courses.py`، `backend/routes/missions.py`، حالة الضابط
في `backend/routes/duty.py`) بتفضل تتسجّل **فورًا** عند كل حفظ، لأنها
مالهاش «خط أساس» شبيه باللوحة تتقاس عليه، ومش بيتعدّل فيها بنفس كثافة
تكليفات اللوحة — تسجيلها فورًا مش ضوضاء.
"""
import copy
import json
from datetime import datetime

from .assignments import label, peek_day
from .people import effective, find_person

MAX_SNAPSHOT_DAYS = 60

# الحقول اللي التأكيد بيراقبها على الخدمة نفسها. الضباط والأفراد مش هنا —
# حركتهم بتتسجّل كصف لكل شخص (اللي المشغّل فعلًا بيدوّر عليه) مش كفرق في
# قايمة معرّفات.
TRACKED = {
    "name": "اسم الخدمة",
    "kind": "التصنيف",
    "section": "القسم على اللوحة",
    "shift": "الفترة",
    "weapon": "التسليح",
    "time": "الانتظام",
    "party": "الجهة",
    "note": "ملاحظات",
    "conscripts": "فئات المجندين",
    "conscript_count": "عدد المجندين",
    "counts_in_summary": "يُحتسب في الإجمالي",
}


# ---------- اللقطة المعتمدة ----------

def confirms(data):
    return data.setdefault("day_confirm", {})


def state_of(data, day):
    """حالة التأكيد لليوم: اتأكد إمتى ومين، وهل فيه تعديلات بعده."""
    entry = (data.get("day_confirm") or {}).get(day)
    rows = peek_day(data, day)
    if not entry:
        return {"confirmed": False, "at": None, "by": "", "pending": bool(rows),
                "count": len(rows)}
    pending = _fingerprint(rows) != _fingerprint(entry.get("rows") or [])
    return {"confirmed": True, "at": entry.get("at"), "by": entry.get("by", ""),
            "pending": pending, "count": len(rows)}


def _fingerprint(rows):
    """مقارنة سريعة «اتغيّر ولا لأ» من غير ما نحسب الفرق بالتفصيل."""
    return sorted(
        (r.get("id"), tuple(sorted(r.get("officer_ids") or [])),
         tuple(sorted(r.get("personnel_ids") or [])),
         tuple((k, _stable(r.get(k))) for k in sorted(TRACKED)))
        for r in rows)


def _stable(value):
    """قيمة قابلة للترتيب والمقارنة — القوايم والقواميس بتتحوّل نص."""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _save_snapshot(data, day, rows, at, by):
    store = confirms(data)
    store[day] = {"at": at, "by": by, "rows": copy.deepcopy(rows)}
    from .store import known_days
    for old in _trimmed(known_days(data, "day_confirm"), day):
        store.pop(old, None)


def _trimmed(confirmed_days, day):
    return sorted({*confirmed_days, day})[:-MAX_SNAPSHOT_DAYS]


def snapshot_scope(index, day):
    """الأيام اللي تأكيد `day` ممكن يلمسها في `day_confirm`: اليوم نفسه
    واللقطات الأقدم اللي هتتشال عشان يفضل آخر `MAX_SNAPSHOT_DAYS` بس."""
    return [day, *_trimmed(index.days_with("day_confirm"), day)]


# ---------- صياغة النصوص ----------

def _person_name(data, person_id, day):
    person, _cat, _bucket = find_person(data, person_id)
    if not person:
        return person_id
    role = effective(person, day)["role"]
    return f"{role}/ {person['name']}" if role else person.get("name", person_id)


def _service_label(row):
    return label(row, with_shift=True) or "(بدون اسم)"


def _show(value):
    if value is None or value == "" or value == []:
        return "—"
    if isinstance(value, bool):
        return "نعم" if value else "لا"
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(" ".join(str(v) for v in item.values() if v not in ("", None)))
            else:
                parts.append(str(item))
        return "، ".join(p for p in parts if p) or "—"
    return str(value)


def _services_by_person(rows):
    """{person_id: [أسماء الخدمات]} — الضباط والأفراد في نفس القايمة لأن
    السؤال واحد: الشخص ده كان على إيه النهاردة."""
    out = {}
    for row in rows:
        name = _service_label(row)
        for pid in (row.get("officer_ids") or []) + (row.get("personnel_ids") or []):
            out.setdefault(pid, []).append(name)
    return {pid: sorted(names) for pid, names in out.items()}


# ---------- الفرق ----------

def diff_events(data, day, before_rows, after_rows):
    """قايمة الأحداث اللي هتتسجّل — حركة الأشخاص الأول، وبعدين الخدمات."""
    events = []
    events += _person_events(data, day, before_rows, after_rows)
    events += _service_events(before_rows, after_rows)
    return events


def _person_events(data, day, before_rows, after_rows):
    before = _services_by_person(before_rows)
    after = _services_by_person(after_rows)
    events = []
    for pid in sorted(set(before) | set(after)):
        old, new = before.get(pid, []), after.get(pid, [])
        if old == new:
            continue
        who = _person_name(data, pid, day)
        old_txt, new_txt = "، ".join(old), "، ".join(new)
        if not old:
            action, text = "assign", f"{who}: كُلِّف بـ«{new_txt}»"
        elif not new:
            action, text = "unassign", f"{who}: أُزيل من «{old_txt}» — بلا خدمة"
        else:
            action, text = "update", f"{who}: كان «{old_txt}» ← أصبح «{new_txt}»"
        events.append({"entity": "duty_move", "entity_id": pid, "action": action,
                       "before": {"name": who, "services": old},
                       "after": {"name": who, "services": new}, "text": text})
    return events


def _service_events(before_rows, after_rows):
    before = {r["id"]: r for r in before_rows}
    after = {r["id"]: r for r in after_rows}
    events = []

    for rid in sorted(set(after) - set(before)):
        row = after[rid]
        events.append({"entity": "assignment", "entity_id": rid, "action": "create",
                       "before": None, "after": dict(row),
                       "text": f"خدمة جديدة: «{_service_label(row)}» في {row.get('section', '')}"})

    for rid in sorted(set(before) - set(after)):
        row = before[rid]
        events.append({"entity": "assignment", "entity_id": rid, "action": "delete",
                       "before": dict(row), "after": None,
                       "text": f"خدمة أُزيلت: «{_service_label(row)}»"})

    for rid in sorted(set(before) & set(after)):
        old, new = before[rid], after[rid]
        moved = [(TRACKED[k], old.get(k), new.get(k)) for k in TRACKED
                 if _stable(old.get(k)) != _stable(new.get(k))]
        if not moved:
            continue
        bits = "، ".join(f"{lbl}: «{_show(o)}» ← «{_show(n)}»" for lbl, o, n in moved)
        events.append({"entity": "assignment", "entity_id": rid, "action": "update",
                       "before": dict(old), "after": dict(new),
                       "text": f"«{_service_label(new)}» — {bits}"})
    return events


# ---------- التأكيد ----------

def confirm_day(data, day, by=""):
    """بيسجّل الفرق من آخر تأكيد وبيحفظ خط الأساس الجديد.

    بيرجّع (summary, events) — الأحداث بتتسجّل في سجل التغييرات من المسار
    عشان الوحدة دي تفضل حاسبة بس، من غير أي كتابة في السجل.
    """
    at = datetime.now().isoformat(timespec="seconds")
    rows = peek_day(data, day)
    entry = (data.get("day_confirm") or {}).get(day)

    if entry is None:
        # أول تأكيد لليوم: مفيش خط أساس نقارن بيه، فتسجيل كل خدمة موجودة
        # كـ«جديدة» هيبقى ضوضاء مش معلومة — سطر واحد بيقول اليومية اتعمدت.
        events = []
        summary = {"first": True, "changes": 0, "count": len(rows)}
    else:
        events = diff_events(data, day, entry.get("rows") or [], rows)
        summary = {"first": False, "changes": len(events), "count": len(rows)}

    _save_snapshot(data, day, rows, at, by)
    summary.update(at=at, by=by, day=day)
    return summary, events
