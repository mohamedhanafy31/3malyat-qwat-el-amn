"""التكامل المرجعي — إعلان واحد لكل مرجع، ومحرّك واحد بينفّذه.

المشكلة اللي بيحلّها: الحذف كان مكتوب بالإيد في كل مسار لوحده — سطر لكل
مكان بيشاور على السجل المحذوف. النتيجة الحتمية إن مكان يتنسي، وده اللي
حصل فعلًا: حذف سجل أرشيف كان بينضّف ٦ أماكن ويسيب `course_terms.
officer_id` و`missions.member_ids` معلّقين. سجل دورة بيشاور على ضابط
متمسوح بيفضل في الملف للأبد — الصفحة بتعرضه بصف فاضي، و«القادم» بيحسبه
في التنبيهات، ومفيش من أي شاشة طريقة توصله عشان تمسحه.

الجدول تحت بيخلي الإجابة على «إيه اللي بيشاور على شخص؟» **معلومة مكتوبة
في مكان واحد** بدل ما تكون متفرّقة على المسارات. إضافة كيان جديد بيشاور
على شخص = سطر واحد هنا، وبعده الحذف والفحص الاتنين بيعرفوه تلقائيًا.

## السلوكيات

    CASCADE    السجل التابع نفسه بيتمسح (راحة بتخص شخص اتمسح)
    DETACH     المرجع بيتشال من قايمة والسجل بيفضل (عضو من مأمورية)
    SET_NULL   المرجع بيتفضّى والسجل بيفضل (منصب قيادي)

## اللي **مش** في الجدول

`change_log` و`day_confirm` لقطات تاريخية — بيفضلوا شايلين معرّفات سجلات
اتمسحت، وده مقصود. مسح الـid منهم بأثر رجعي بيحوّل سجل التدقيق لسجل
بيكدب عن اللي حصل. `tools/check_integrity.py` بيستثنيهم بنفس المنطق.
"""

CASCADE = "cascade"
DETACH = "detach"
SET_NULL = "set_null"


# ---------- الفحص: إيه اللي بيشاور على إيه ----------
#
# نفس الخريطة اللي الحذف بيمشي عليها، بس من ناحية القراءة: `tools/
# check_integrity.py` بيستخدمها عشان يلاقي المراجع المعلّقة. المصدر واحد،
# فمرجع جديد بيتضاف مرة وبيتعرف في الحذف والفحص مع بعض — مش نسختين ممكن
# يفرقوا من غير ما حد ياخد باله.

def person_references(data):
    """(المكان, نوع الهدف, المعرّف) لكل مرجع بيشاور على شخص أو خدمة.

    السجلات التاريخية (`change_log` و`day_confirm`) **مش** هنا عن قصد —
    شوف شرح الملف فوق.
    """
    for lv in data.get("leaves") or []:
        yield f"leaves[{lv.get('id')}].person_id", "person", lv.get("person_id")
        if lv.get("suspension_id"):
            yield (f"leaves[{lv.get('id')}].suspension_id", "rest_suspension",
                   lv["suspension_id"])

    for term in data.get("course_terms") or []:
        where = f"course_terms[{term.get('id')}]"
        yield f"{where}.officer_id", "officer", term.get("officer_id")
        yield f"{where}.course_id", "course", term.get("course_id")

    for mission in data.get("missions") or []:
        for pid in mission.get("member_ids") or []:
            yield f"missions[{mission.get('id')}].member_ids", "officer", pid

    for day, rows in (data.get("day_assignments") or {}).items():
        for row in rows:
            where = f"day_assignments[{day}][{row.get('id')}]"
            for pid in row.get("officer_ids") or []:
                yield f"{where}.officer_ids", "officer", pid
            for pid in row.get("personnel_ids") or []:
                yield f"{where}.personnel_ids", "individual", pid
            # اختياري — بيتملا في المرحلة ٣؛ فاضي دلوقتي معناه «خدمة طارئة
            # مالهاش هوية في الكتالوج»، مش مرجع معلّق
            if row.get("service_id"):
                yield f"{where}.service_id", "service", row["service_id"]

    for day, states in (data.get("day_officers") or {}).items():
        for pid in states:
            yield f"day_officers[{day}]", "officer", pid

    for day, entries in (data.get("day_afraad") or {}).items():
        for entry_id, entry in (entries or {}).items():
            for key in ("morning_person_id", "night_person_id"):
                if entry.get(key):
                    yield f"day_afraad[{day}][{entry_id}].{key}", "individual", entry[key]

    for role, pid in (data.get("command") or {}).items():
        if pid:
            yield f"command[{role}]", "officer", pid

    for order in data.get("rest_suspensions") or []:
        for snap in order.get("cancelled_leaves") or []:
            if snap.get("person_id"):
                yield (f"rest_suspensions[{order.get('id')}].cancelled_leaves",
                       "person", snap["person_id"])

    for role, ids in (data.get("command_groups") or {}).items():
        for pid in ids or []:
            yield f"command_groups[{role}]", "officer", pid

    for entry in data.get("command_history") or []:
        stamp = entry.get("from")
        for role, pid in (entry.get("command") or {}).items():
            if pid:
                yield f"command_history[{stamp}].command[{role}]", "officer", pid
        for role, ids in (entry.get("groups") or {}).items():
            for pid in ids or []:
                yield f"command_history[{stamp}].groups[{role}]", "officer", pid

    for entry in (data.get("counts_template") or {}).get("entries") or []:
        if entry.get("service_id"):
            yield (f"counts_template[{entry.get('id')}].service_id",
                   "service", entry["service_id"])

    for day, sheet in (data.get("service_counts") or {}).items():
        for entry in sheet.get("entries") or []:
            if entry.get("service_id"):
                yield (f"service_counts[{day}][{entry.get('id')}].service_id",
                       "service", entry["service_id"])


# (وصف, السلوك, الدالة المنفّذة) لكل مرجع بيشاور على شخص.
# الوصف بيتعرض في تقرير `check_integrity` وفي سبب الحذف.
PERSON_REFERENCES = [
    ("leaves.person_id", CASCADE,
     lambda repos, pid, cat: _drop_leaves(repos, pid)),

    ("course_terms.officer_id", CASCADE,
     lambda repos, pid, cat: _drop_terms(repos, pid)),

    ("missions.member_ids", DETACH,
     lambda repos, pid, cat: _detach_missions(repos, pid)),

    ("day_assignments.officer_ids / personnel_ids", DETACH,
     lambda repos, pid, cat: repos.days.detach_person(
         pid, "officer_ids" if cat == "officers" else "personnel_ids")),

    ("day_officers.<key>", CASCADE,
     lambda repos, pid, cat: repos.days.drop_officer_states(pid)),

    ("day_afraad.*.morning_person_id / night_person_id", SET_NULL,
     lambda repos, pid, cat: _detach_afraad_links(repos, pid)),

    ("command.<value>", SET_NULL,
     lambda repos, pid, cat: repos.config.clear_command(pid)),

    ("command_groups.<value>", DETACH,
     lambda repos, pid, cat: repos.config.remove_from_groups(pid)),

    ("rest_suspensions.cancelled_leaves", DETACH,
     lambda repos, pid, cat: _detach_suspension_snapshots(repos, pid)),
]


def cascade_delete(repos, person_id, category):
    """ينضّف كل مرجع بيشاور على الشخص ده. بيرجّع {الوصف: عدد المتأثر}.

    بيتنادى **بعد** ما السجل نفسه يتشال، عشان لو وقع في النص ما يسيبش
    السجل موجود وتوابعه متمسوحة.
    """
    report = {}
    for label, _behaviour, apply in PERSON_REFERENCES:
        touched = apply(repos, person_id, category)
        if touched:
            report[label] = touched
    return report


def _detach_suspension_snapshots(repos, person_id):
    """شخص اتمسح نهائيًا — لقطات راحاته الملغية تحت أوامر الوقف بتتشال."""
    touched = 0
    for order in repos.data.get("rest_suspensions") or []:
        snaps = order.get("cancelled_leaves") or []
        kept = [s for s in snaps if s.get("person_id") != person_id]
        if len(kept) != len(snaps):
            order["cancelled_leaves"] = kept
            touched += len(snaps) - len(kept)
    return touched


def _detach_afraad_links(repos, person_id):
    touched = 0
    for entries in (repos.data.get("day_afraad") or {}).values():
        for entry in (entries or {}).values():
            for key in ("morning_person_id", "night_person_id"):
                if entry.get(key) == person_id:
                    entry.pop(key, None)
                    touched += 1
    return touched


def _drop_leaves(repos, person_id):
    found = repos.leaves.of_person(person_id)
    for leave in found:
        repos.leaves.remove(leave.id)
    return len(found)


def _drop_terms(repos, person_id):
    found = repos.terms.of_officer(person_id)
    for term in found:
        repos.terms.remove(term.id)
    return len(found)


def _detach_missions(repos, person_id):
    touched = 0
    for mission in repos.missions.of_officer(person_id):
        mission.member_ids = [i for i in mission.member_ids if i != person_id]
        repos.missions.save(mission)
        touched += 1
    return touched
