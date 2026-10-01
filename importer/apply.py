"""تطبيق ناتج TRANSFORM على نسخة بيانات — مشترك بين VERIFY (في الذاكرة) وSTORE (على القرص).

قواعد عدم الكتابة فوق الموجود:
- الشخص الموجود في النظام: تاريخ انضمامه بيتمد لورا بس، وبتتضاف له سجلات
  تاريخ أقدم من أول سجل عنده. قيمه الحالية وسجلاته ما بتتلمسش.
- الشخص الجديد بيتسجل في الأرشيف (status=archived) وتاريخ خروجه = آخر ظهور،
  عشان الاستيراد ما يغيّرش القوة الحالية. اللي ظهر في فترة النظام وهو مش فيه
  بيطلع عنصر مراجعة.
- القيادة والقوائم المرجعية: النسخ المستوردة بتتضاف قبل أول يوم في النظام بس،
  ونسخة بقيم النظام الحالية بتتثبت عند أول يوم فيه.
- المعرّفات المؤقتة (NEW-OFF-/NEW-IND-) بتاخد معرّفات حقيقية بـreserve_id وبتتحفظ
  في id_map بمفتاح طبيعي، فإعادة التشغيل بتدي نفس المعرّف.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from backend.afraad import BASIC_SERVICES
from backend.constants import TARGETS_FIRST, TARGET_NAMES
from backend.models.leave import Leave
from backend.models.person import Individual, Officer
from backend.store import reserve_id
from backend.text import norm

# نفس اصطلاح الاستيراد اللي اتبنى بيه النظام (import_archive/build.py: GRADE_FAMILY).
# «م.ش» = معاون شرطة اختيار موروث ومُعلَّم في التقرير كنقطة تحتاج تأكيد.
GRADE_FAMILY = [
    (r"^م\s*ش\b", "معاون شرطة"),
    (r"^ا\s*ش\b|^اش\b", "أمين شرطة"),
    (r"^امين", "أمين شرطة"),
    (r"^معاون", "معاون شرطة"), (r"^مساعد", "مساعد شرطة"),
    (r"^رقيب", "رقيب شرطة"), (r"^مراقب", "مراقب شرطة"),
    (r"^مندوب", "مندوب شرطة"), (r"^عريف", "عريف شرطة"), (r"^شرطي", "شرطي"),
]
NEW_PREFIX = "NEW-"
LEAVE_REASON = "استيراد الأرشيف: آخر ظهور في اليوميات"


def grade_family(raw: str) -> str:
    flat = norm(raw or "")
    return next((family for pattern, family in GRADE_FAMILY if re.search(pattern, flat)), "")


def natural_key(category: str, entry: dict[str, Any]) -> str:
    """مفتاح ثابت بين التشغيلات (ترقيم NEW-* ممكن يتغير). الاسم لوحده ممكن يتكرر لشخصين مختلفين
    (اتنين «محمد مصطفي» بتليفونين)، فبيتضاف أول ظهور وأول تليفون."""
    if category == "officers" and entry.get("code"):
        return f"code:{entry['code']}"
    phones = entry.get("phones") or []
    return f"name:{norm(entry.get('name') or '')}|from:{entry.get('first_seen', '')}|phone:{phones[0] if phones else ''}"


def assign_ids(data: dict[str, Any], delta: dict[str, Any], id_map: dict[str, Any]) -> dict[str, str]:
    """NEW-* → معرّف حقيقي، بترتيب ثابت (أول ظهور ثم المعرّف المؤقت). بيعدّل id_map."""
    assigned: dict[str, str] = {}
    for category, prefix in (("officers", "OFF"), ("personnel", "IND")):
        known = id_map.setdefault(category, {})
        existing = data.setdefault(category, [])
        for entry in sorted(delta.get(category) or [], key=lambda e: (e.get("first_seen") or "", e["id"])):
            if not entry["id"].startswith(NEW_PREFIX):
                continue
            key = natural_key(category, entry)
            real = known.get(key) or reserve_id(data, prefix, existing)
            known[key] = real
            assigned[entry["id"]] = real
    return assigned


def remap(value: Any, assigned: dict[str, str]) -> Any:
    if isinstance(value, str):
        return assigned.get(value, value)
    if isinstance(value, list):
        return [remap(item, assigned) for item in value]
    if isinstance(value, dict):
        return {remap(key, assigned): remap(item, assigned) for key, item in value.items()}
    return value


def remap_day(day: dict[str, Any], assigned: dict[str, str]) -> dict[str, Any]:
    """ملف اليوم بالمعرّفات الحقيقية. الحقول النصية (اسم/ملاحظة) ما بتتلمسش."""
    out = copy.deepcopy(day)
    for row in out.get("assignments") or []:
        row["officer_ids"] = remap(row.get("officer_ids") or [], assigned)
        row["personnel_ids"] = remap(row.get("personnel_ids") or [], assigned)
    if out.get("officer_states"):
        out["officer_states"] = {assigned.get(key, key): value for key, value in out["officer_states"].items()}
    for entry in (out.get("afraad_basic") or {}).values():
        for field in ("morning_person_id", "night_person_id"):
            if entry.get(field):
                entry[field] = assigned.get(entry[field], entry[field])
    return out


def unlink_off_force(day: dict[str, Any], date: str, on_force: dict[str, set[str]],
                     names: dict[str, str]) -> list[dict[str, Any]]:
    """النظام بيرفض تكليف شخص مش على القوة يومها. الربط بيتفك والاسم بيتحفظ في ملاحظة الصف
    (أو اسم الفرد في يومية الأفراد بيفضل نص)، وكل حالة بتطلع عنصر مراجعة."""
    review = []
    for row in day.get("assignments") or []:
        for field, category in (("officer_ids", "officers"), ("personnel_ids", "personnel")):
            outside = [pid for pid in row.get(field) or [] if pid not in on_force[category]]
            if not outside:
                continue
            row[field] = [pid for pid in row[field] if pid not in outside]
            text = " + ".join(names.get(pid) or pid for pid in outside)
            if text not in (row.get("note") or ""):
                row["note"] = f"{row.get('note') or ''} {text}".strip()
            review.append({"type": "ref_outside_force", "date": date, "row": row.get("id"), "name": row.get("name"),
                           "ids": outside})
    for entry_id, entry in (day.get("afraad_basic") or {}).items():
        for field in ("morning_person_id", "night_person_id"):
            if entry.get(field) and entry[field] not in on_force["personnel"]:
                review.append({"type": "ref_outside_force", "date": date, "afraad": entry_id, "ids": [entry[field]]})
                entry.pop(field)
    return review


def cut_leaves_on_duty(data: dict[str, Any], days: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """قاعدة المستخدم: الضابط اللي عليه خدمة في يوم مستورد ماكانش في راحة يومها — الراحة بتتقص/تتقسم
    حوالين أيام الخدمة (حتى راحات النظام الموجودة)، والراحة اللي كل أيامها شغل بتتشال. كل تعديل له عنصر مراجعة."""
    busy: dict[str, set[str]] = {}
    for date, blob in days.items():
        for row in blob.get("assignments") or []:
            for pid in row.get("officer_ids") or []:
                busy.setdefault(pid, set()).add(date)
    if not busy:
        return []
    review = []
    leaves = data.setdefault("leaves", [])
    for leave in list(leaves):
        dates = busy.get(leave.get("person_id"))
        if not dates or not leave.get("start") or not leave.get("end"):
            continue
        hits = sorted(day for day in dates if leave["start"] <= day <= leave["end"])
        if not hits:
            continue
        runs, current, day = [], None, leave["start"]
        while day <= leave["end"]:
            if day in dates:
                current = None
            elif current is None:
                current = [day, day]
                runs.append(current)
            else:
                current[1] = day
            day = _next(day)
        before = copy.deepcopy(leave)
        if not runs:
            leaves.remove(leave)
        else:
            leave["start"], leave["end"], leave["return_date"] = runs[0][0], runs[0][1], _next(runs[0][1])
            for start, end in runs[1:]:
                leaves.append({**{k: v for k, v in before.items() if k != "id"}, "start": start, "end": end,
                               "return_date": _next(end), "id": reserve_id(data, "LV", leaves)})
        review.append({"type": "leave_cut_by_service", "person_id": before.get("person_id"), "before": before,
                       "service_days": hits, "after": [list(run) for run in runs]})
    return review


def _next_code(people: list[dict[str, Any]], prefix: str) -> str:
    numbers = [int(match.group(1)) for person in people
               if (match := re.fullmatch(rf"{prefix}-(\d+)", str(person.get("code") or "")))]
    return f"{prefix}-{(max(numbers) if numbers else 0) + 1:03d}"


def _officer_history(entry: dict[str, Any]) -> dict[str, Any]:
    return {"from": entry["from"], "role": entry.get("role") or "", "post": entry.get("post") or "",
            "section": entry.get("section") or "", "search_attached": bool(entry.get("search_attached")),
            "rest_system": entry.get("rest_system") or "", "rest_day": entry.get("rest_day") or ""}


def _prepend_history(person: dict[str, Any], older: list[dict[str, Any]], fields: tuple[str, ...]) -> int:
    """سجلات أقدم من أول سجل عند الشخص. لو مالوش تاريخ، قيمه الحالية بتبقى سجل من تاريخ انضمامه الأصلي
    — من غيرها أقدم سجل مستورد كان هيسري على أيام النظام كمان."""
    history = person.setdefault("history", [])
    if not history:
        history.append({"from": person.get("join_date") or "",
                        **{field: person.get(field, False if field == "search_attached" else "") for field in fields}})
    first = min(entry.get("from") or "" for entry in history)
    added = [entry for entry in older if entry["from"] < first]
    history[:0] = added
    history.sort(key=lambda entry: entry.get("from") or "")
    return len(added)


def apply_core(data: dict[str, Any], delta: dict[str, Any], assigned: dict[str, str], *,
               system_start: str, imported: set[str] | None = None, kept: set[str] | None = None) -> dict[str, Any]:
    """بيطبق core_delta على data في مكانها. بيرجع إحصائيات وعناصر مراجعة."""
    stats: dict[str, Any] = {"officers_created": 0, "officers_extended": 0, "personnel_created": 0,
                             "personnel_extended": 0, "history_added": 0, "leaves_added": 0,
                             "leaves_skipped": 0, "command_versions": 0, "reference_versions": 0}
    review: list[dict[str, Any]] = []
    officers = data.setdefault("officers", [])
    personnel = data.setdefault("personnel", [])
    by_id = {person["id"]: person for person in officers + personnel}

    for entry in delta.get("officers") or []:
        person_id = assigned.get(entry["id"], entry["id"])
        history = [_officer_history(item) for item in entry.get("history") or []]
        person = by_id.get(person_id)
        if person is None:
            latest = history[-1] if history else _officer_history({"from": entry["first_seen"]})
            code = entry.get("code") or _next_code(officers, "ض")
            if not entry.get("code"):
                review.append({"type": "officer_code_unknown", "id": person_id, "name": entry.get("name"), "code": code})
            person = {"id": person_id, "name": entry.get("name") or "", "role": latest["role"], "code": code,
                      "phone": "", "join_date": entry["first_seen"], "post": latest["post"],
                      "section": latest["section"], "rest_system": latest["rest_system"],
                      "rest_day": latest["rest_day"], "search_attached": latest["search_attached"],
                      "status": "archived", "leave_date": entry["last_seen"], "leave_reason": LEAVE_REASON,
                      "history": history}
            officers.append(person)
            by_id[person_id] = person
            stats["officers_created"] += 1
            if entry["last_seen"] >= system_start:
                review.append({"type": "new_officer_in_system_era", "id": person_id, "name": person["name"],
                               "last_seen": entry["last_seen"]})
            continue
        stats["officers_extended"] += 1
        if entry["first_seen"] < (person.get("join_date") or "9999"):
            original = person.get("join_date") or entry["first_seen"]
            stats["history_added"] += _prepend_history(
                person, [item for item in history if item["from"] < original],
                ("role", "post", "section", "search_attached", "rest_system", "rest_day"))
            person["join_date"] = entry["first_seen"]
        if person.get("leave_date") and entry["last_seen"] > person["leave_date"]:
            review.append({"type": "seen_after_leave_date", "id": person_id, "leave_date": person["leave_date"],
                           "last_seen": entry["last_seen"]})

    for entry in delta.get("personnel") or []:
        person_id = assigned.get(entry["id"], entry["id"])
        person = by_id.get(person_id)
        grades = []
        for item in entry.get("history") or []:
            family = grade_family(item.get("role") or "")
            if family and (not grades or grades[-1]["role"] != family):
                grades.append({"from": item["from"], "role": family, "post": ""})
        phones = [phone for phone in entry.get("phones") or [] if re.fullmatch(r"01\d{9}", phone)]
        if person is None:
            role = grades[-1]["role"] if grades else ""
            if not role:
                review.append({"type": "personnel_grade_unknown", "id": person_id, "name": entry.get("name")})
            person = {"id": person_id, "name": entry.get("name") or "", "role": role,
                      "code": _next_code(personnel, "ف"), "phone": phones[0] if phones else "",
                      "other_phones": phones[1:], "join_date": entry["first_seen"], "post": "", "address": "",
                      "status": "archived", "leave_date": entry["last_seen"], "leave_reason": LEAVE_REASON}
            if len(grades) > 1:
                person["history"] = grades
            personnel.append(person)
            by_id[person_id] = person
            stats["personnel_created"] += 1
            if entry["last_seen"] >= system_start:
                review.append({"type": "new_personnel_in_system_era", "id": person_id, "name": person["name"],
                               "last_seen": entry["last_seen"]})
            continue
        stats["personnel_extended"] += 1
        if entry["first_seen"] < (person.get("join_date") or "9999"):
            person["join_date"] = entry["first_seen"]
        current_family = grade_family(person.get("role") or "")
        if grades and current_family and any(item["role"] != current_family for item in grades):
            # الدرجة في الأرشيف بعائلة مختلفة عن النظام — ما بنكتبش، بنسأل
            review.append({"type": "personnel_grade_differs", "id": person_id, "system": person.get("role"),
                           "archive": [item["role"] for item in grades]})
        if person.get("leave_date") and entry["last_seen"] > person["leave_date"]:
            review.append({"type": "seen_after_leave_date", "id": person_id, "leave_date": person["leave_date"],
                           "last_seen": entry["last_seen"]})

    leaves = data.setdefault("leaves", [])
    taken = {(leave.get("person_id"), leave.get("type"), leave.get("start")) for leave in leaves}
    spans: dict[str, list[tuple[str, str]]] = {}
    for leave in leaves:
        spans.setdefault(leave.get("person_id"), []).append((leave.get("start") or "", leave.get("end") or ""))
    for op in delta.get("leaves") or []:
        if op.get("op") != "add":
            stats["leaves_skipped"] += 1
            continue
        person_id = assigned.get(op["person_id"], op["person_id"])
        key = (person_id, op["type"], op["start"])
        if key in taken:
            continue
        record = {"person_id": person_id, "type": op["type"], "start": op["start"], "end": op["end"],
                  "return_date": op["return_date"], "note": "", "source": op.get("source") or ""}
        person = by_id.get(person_id)
        if person is not None:
            # «أصل القوة» في الوورد بيعد اللي في اليومية بس، فمدى الخدمة ما بيتمدش عشان راحة؛ الراحة
            # بتتقص على المدى ونصها الأصلي بيفضل في source (اليومية الأولى/الأخيرة ممكن تبدأ في نص راحة)
            join, left = person.get("join_date") or "", person.get("leave_date") or ""
            clipped = False
            if join and record["start"] < join <= record["end"]:
                record["start"], clipped = join, True
            if left and record["start"] <= left < record["end"]:
                record["end"], record["return_date"], clipped = left, _next(left), True
            if clipped:
                record["note"] = "مقصوصة على مدى الخدمة في الأرشيف"
                review.append({"type": "leave_clipped", "person_id": person_id, "leave": dict(record),
                               "original": [op["start"], op["end"]]})
        # نفس قواعد النظام عند إضافة راحة: النموذج، مدى الخدمة، وعدم التداخل
        model = Leave.from_dict(record)
        problems = model.validate()
        if person is not None:
            outside = model.within_service((Officer if person_id.startswith("OFF-") else Individual).from_dict(person))
            if outside:
                problems.append(outside)
        if any(not (end < op["start"] or start > op["end"]) for start, end in spans.get(person_id, [])):
            problems.append("تداخل مع راحة أخرى لنفس الشخص")
        if problems:
            review.append({"type": "leave_not_added", "person_id": person_id, "leave": record, "problems": problems})
            stats["leaves_skipped"] += 1
            continue
        record["id"] = reserve_id(data, "LV", leaves)
        leaves.append(record)
        spans.setdefault(person_id, []).append((op["start"], op["end"]))
        taken.add(key)
        stats["leaves_added"] += 1

    # نفس ترتيب القراءة في store._read — من غيره إعادة التحميل بتعيد ترتيب القايمة والكتابة التانية ما تبقاش صفر
    from backend.utils import sort_active
    sort_active(data, "officers")
    sort_active(data, "personnel")
    stats["command_versions"] = _apply_command(data, remap(delta.get("command_history") or [], assigned), system_start)
    stats["reference_versions"] = _apply_references(data, delta.get("reference_lists") or {}, system_start,
                                                    set(imported or ()), set(kept or ()))
    return {"stats": stats, "review": review}


def _apply_command(data: dict[str, Any], versions: list[dict[str, Any]], system_start: str) -> int:
    if not versions:
        return 0
    history = data.setdefault("command_history", [])
    if not history:
        # قيم النظام الحالية سارية من أول يوم فيه — قبل ما يتحط قدامها أي نسخة أقدم
        history.append({"from": system_start, "command": copy.deepcopy(data.get("command") or {}),
                        "groups": copy.deepcopy(data.get("command_groups") or {})})
    first = min(entry.get("from") or "" for entry in history)
    added = [version for version in versions if version["from"] < first]
    history.extend(copy.deepcopy(added))
    history.sort(key=lambda entry: entry.get("from") or "")
    return len(added)


def _apply_references(data: dict[str, Any], lists: dict[str, Any], system_start: str,
                      imported: set[str], kept: set[str]) -> int:
    """القوائم المؤرخة على خط زمني: اليوم المستورد بياخد قائمة وثيقته، وأي يوم متساب (اليومين
    المرجعيين وأيام النظام اللي مش بتتستبدل) بيفضل على قائمته الفعلية الحالية، والقائمة الحالية
    بتفضل آخر نسخة — فالاستيراد ما يغيّرش إعدادات النهاردة."""
    from backend.dated import _entry_on
    reference = data.get("reference_lists") or {}
    defaults = {"targets": ("names", [TARGETS_FIRST, *TARGET_NAMES]),
                "afraad_basic": ("items", copy.deepcopy(BASIC_SERVICES))}
    changed = 0
    for key, (field, default) in defaults.items():
        if not (lists.get(key) or reference.get(key)):
            continue  # لا نسخ مستوردة ولا نسخ في النظام — القائمة الافتراضية بتفضل زي ما هي
        existing = sorted((entry for entry in reference.get(key) or [] if isinstance(entry, dict)),
                          key=lambda entry: entry.get("from") or "")
        if not existing:
            existing = [{"from": system_start, field: default}]
        imported_versions = sorted(lists.get(key) or [], key=lambda entry: entry["from"])

        def current(day: str) -> Any:
            entry = _entry_on(existing, day) if (existing[0].get("from") or "") <= day else None
            return copy.deepcopy(entry[field]) if entry else None

        timeline = sorted(imported | {day for day in kept if day >= min(imported, default="9999")})
        # نسخ النظام اللي قبل أول يوم مستورد بتفضل زي ما هي
        versions: list[dict[str, Any]] = [copy.deepcopy(entry) for entry in existing
                                          if timeline and (entry.get("from") or "") < timeline[0]]
        for day in timeline:
            if day in imported:
                entry = _entry_on(imported_versions, day) if imported_versions else None
                value = copy.deepcopy(entry[field]) if entry and entry["from"] <= day else current(day)
            else:
                value = current(day)
            if value is None:
                continue
            if not versions or versions[-1][field] != value:
                versions.append({"from": day, field: value})
        if timeline:
            after = _next(timeline[-1])
            tail = [copy.deepcopy(entry) for entry in existing if (entry.get("from") or "") > timeline[-1]]
            now = current(after)
            if now is not None and (not tail or tail[0]["from"] != after) and (not versions or versions[-1][field] != now):
                versions.append({"from": after, field: now})
            versions.extend(tail)
        else:
            versions = existing
        if versions != (reference.get(key) or []):
            changed += len(versions)
        data.setdefault("reference_lists", reference)[key] = versions
    return changed


def _days_between(start: str, end: str) -> int:
    import datetime as dt
    return (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days


def _next(day: str) -> str:
    import datetime as dt
    return (dt.date.fromisoformat(day) + dt.timedelta(days=1)).isoformat()


def system_start_of(days: dict[str, dict[str, Any]]) -> str:
    """أول يوم اتعمل جوه النظام (من غير علامة استيراد)."""
    own = [date for date, blob in days.items() if not blob.get("import")]
    return min(own) if own else "9999-12-31"


__all__ = ["GRADE_FAMILY", "apply_core", "assign_ids", "grade_family", "natural_key", "remap_day", "system_start_of",
           "unlink_off_force", "cut_leaves_on_duty"]
