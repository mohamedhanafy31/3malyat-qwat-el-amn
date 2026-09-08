"""الربط بين لوحة التشغيل المختصرة ويومية التشغيل.

قبل كده كان فيه سجلّين منفصلين لنفس الحقيقة («الضابط ده شايل الخدمة دي
النهاردة»): `duties` اللي بيغذّي جدول الإجمالي، و`day_services` اللي بيغذّي
اللوحة — ومحدش بيكتب للتاني. فلما تحط ضابط على خدمة من اللوحة كان يفضل
ظاهر في «عمل بالإدارة (الصافي)» وكأنه فاضي.

الملف ده بيوفّق بين الاتنين في الاتجاهين. الربط بيتم **بالاسم**: اسم الخدمة
على اللوحة بيتدوّر عليه في كتالوج الخدمات، والتصنيف بتاع الكتالوج
(خارجية/داخلية/حراسات/...) هو اللي بيحدد الضابط يتحسب في أنهي خانة.

الأسماء اللي مش في الكتالوج (زي «مدير الإدارة» أو «قائد المعسكر الفرعي»)
مقصود إنها ما تتربطش — دي مناصب إدارية والضابط المفروض يفضل في الصافي.
"""
from .board import board_shift, category_for_service, get_day_services
from .constants import SERVICE_TAGS
from .people import find_person


def _by_name(data):
    return {s["name"]: s for s in data["services"]}


def _by_id(data):
    return {s["id"]: s for s in data["services"]}


def _slot(name, shift, svc):
    """مفتاح المقارنة بين الجهتين — الحراسات مالهاش فترة فبتتقارن بالاسم بس."""
    return (name, board_shift(shift, svc))


def sync_duty_from_board(data, day, officer_id):
    """يعيد بناء تكليفات الضابط في يومية التشغيل من خاناته على اللوحة.

    التقصيرة والحالة (انتداب/غياب) ونص الملاحظة بتفضل زي ما هي — دي حالة
    الضابط نفسه مش تكليف بخدمة.
    """
    if not officer_id:
        return
    by_name = _by_name(data)
    items = []
    for e in data["day_services"].get(day, []):
        if e.get("officer_id") != officer_id:
            continue
        svc = by_name.get(e.get("service"))
        if not svc:
            continue                     # منصب إداري مش خدمة — يفضل صافي
        items.append({"service_id": svc["id"], "shift": e.get("shift") or "صباحية"})

    day_duties = data["duties"].setdefault(day, {})
    entry = day_duties.get(officer_id) or {"items": [], "taqseera": False, "note": ""}
    entry["items"] = items
    day_duties[officer_id] = entry

    # مفيش تكليف ولا حالة خاصة = صافي، فمالوش لزوم يفضل مسجّل
    if not items and not entry.get("taqseera") and not entry.get("status") and not entry.get("note"):
        day_duties.pop(officer_id, None)
    if not day_duties:
        data["duties"].pop(day, None)


def sync_board_from_duty(data, day, officer_id):
    """يعيد توفيق خانات اللوحة مع تكليفات الضابط في يومية التشغيل.

    - خدمة اتشالت من التكليف → خانتها على اللوحة بتفضل موجودة بس بتبقى
      **شاغرة** (من غير ضابط)، لأن الخدمة نفسها لسه مطلوبة ومحتاجة بديل.
    - خدمة اتضافت → بتتحط في أول خانة شاغرة ليها، وإلا بتتعمل خانة جديدة.
    - المناصب الإدارية على اللوحة مش بتتلمس خالص.
    """
    if not officer_id:
        return
    person, _, _ = find_person(data, officer_id)
    if not person:
        return
    by_name, by_id = _by_name(data), _by_id(data)
    entries = get_day_services(data, day)

    wanted = []
    for it in data["duties"].get(day, {}).get(officer_id, {}).get("items", []):
        svc = by_id.get(it.get("service_id"))
        if svc:
            wanted.append(_slot(svc["name"], it.get("shift"), svc))

    # 1) فضّي أي خانة خدمة الضابط مبقاش مكلّف بيها
    for e in entries:
        if e.get("officer_id") != officer_id:
            continue
        svc = by_name.get(e.get("service"))
        if not svc:
            continue                     # منصب إداري — سيبه زي ما هو
        key = _slot(e["service"], e.get("shift"), svc)
        if key in wanted:
            wanted.remove(key)
        else:
            e["officer_id"] = None

    # 2) الخدمات الجديدة: املا خانة شاغرة، وإلا اعمل خانة
    for name, shift in wanted:
        svc = by_name.get(name)
        vacant = next((e for e in entries
                       if e.get("service") == name and not e.get("officer_id")
                       and _slot(e["service"], e.get("shift"), svc) == (name, shift)), None)
        if vacant:
            vacant["officer_id"] = officer_id
            vacant["officer_name"] = person.get("name", "")
            continue
        from .store import next_id          # محلي لتفادي دورة استيراد
        entries.append({
            "id": next_id(entries, "DS", width=4),
            "category": category_for_service(name, svc),
            "service": name, "shift": shift,
            "officer_id": officer_id, "officer_name": person.get("name", ""),
            "requirements": [],
            "tags": [SERVICE_TAGS[name]] if name in SERVICE_TAGS else [],
            "note": "",
        })
