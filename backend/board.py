"""لوحة التشغيل المختصرة — الاشتقاق الأولي من نص التشغيل، وبناء اللوحة القابلة للتعديل الحر."""
from .constants import (
    CATEGORY_ADMIN_ROLES, CATEGORY_BASIC, CATEGORY_OCCASIONAL,
    CATEGORY_SUBCAMP, CATEGORY_TARGETS, BOARD_ROTATIONS, COMMAND_ROLES,
    PLAIN_ADMIN_DUTY, SERVICE_TAGS, SUBCAMP_SERVICES,
)
from .duty import summarise
from .leaves import leave_on
from .people import officers_on
from .store import next_id


def _norm_admin(text):
    return (text or "").strip().replace("ة", "ه")


def _command_entries(data, day, entries):
    """قيادة الإدارة (المدير والوكيل) تشغيلهم ثابت كل يوم — بيتحطوا تلقائيًا
    في «أدوار بالإدارة» من غير ما تكلّفهم بإيدك كل يوم.

    بيتخطّوا في الحالات دي:
    - الضابط في راحة/إجازة اليوم ده.
    - مكانش على القوة يومها (انضم بعده أو خرج قبله).
    - ظاهر بالفعل في خانة تانية في نفس اليوم (اتكلّف باستثناء)، فمابنكررهوش.

    بترجّع الخانات الجديدة بس عشان اللي بيندهها يضيفها لقايمته.
    """
    assigned = {e.get("officer_id") for e in entries if e.get("officer_id")}
    on_force = {o["id"]: o for o in officers_on(data, day)}
    out = []
    for role in COMMAND_ROLES:
        officer_id = (data.get("command") or {}).get(role)
        if not officer_id or officer_id in assigned:
            continue
        officer = on_force.get(officer_id)
        if not officer or leave_on(data, officer_id, day):
            continue
        out.append({
            "id": next_id(entries + out, "DS", width=4),
            "category": CATEGORY_ADMIN_ROLES, "service": role, "shift": "",
            "officer_id": officer_id, "officer_name": officer.get("name", ""),
            "requirements": [], "tags": [], "note": "",
        })
    return out


def _derive_day_services(data, day):
    """أول ما يوم قديم (متسحوب من الأرشيف) يتفتح لأول مرة، بنشتق قائمة
    الخدمات المبدئية بتاعته من نص تشغيل الضباط — وبعد كده بقى قابل للتعديل
    الحر زي أي يوم جديد، من غير أي علاقة بالنص الأصلي تاني.

    - الخدمات الطبية بتتحسب أوتوماتيك في حالة الضابط اليومية، فمالهاش خانة هنا.
    - الأهداف (الحراسات المشددة) مالهاش صباحية/ليلية — هدف ثابت طول اليوم.
    - نوبتجي المعسكر الفرعي له تصنيف مستقل "المعسكر الفرعي".
    - ضابط تشغيله "عمل" أو "عمل بالإدارة" بس (بدون خدمة) بيتحط في "أدوار
      بالإدارة" باسم وظيفته الرسمية بدل ما يفضل ظاهر بس في قايمة "الصافي".
    """
    services = {s["id"]: s for s in data["services"]}
    officers = {o["id"]: o for b in ("active", "archive") for o in data["officers"][b]}
    full = summarise(data, day)

    slots = {}          # (service_name, shift) -> list[(row, item, is_taqseera)]
    for r in full["rows"]:
        for it in r["services"]:
            if it["kind"] == "طبية":
                continue
            shift = "" if it["kind"] == "حراسات" else it["shift"]
            slots.setdefault((it["name"], shift), []).append((r, it, bool(r["taqseera"])))

    def pick(name, shift):
        cands = slots[(name, shift)]
        clean = [c for c in cands if not c[2]]
        return (clean or cands)[0]

    entries = []
    for name, shift in slots:
        r, it, taq = pick(name, shift)
        svc = services.get(it["id"], {})
        if it["kind"] == "حراسات":
            cat = CATEGORY_TARGETS
        elif name in SUBCAMP_SERVICES:
            cat = CATEGORY_SUBCAMP
        elif name in BOARD_ROTATIONS:
            cat = CATEGORY_ADMIN_ROLES
        elif it["kind"] == "خارجية" and svc.get("standing"):
            cat = CATEGORY_BASIC
        else:
            cat = CATEGORY_OCCASIONAL
        tags = [SERVICE_TAGS[name]] if name in SERVICE_TAGS else []
        remember_tags(data, tags)
        entries.append({
            "id": next_id(entries, "DS", width=4), "category": cat, "service": name,
            "shift": shift, "officer_id": r["id"], "officer_name": r["name"],
            "requirements": [], "tags": tags,
            "note": r["note"] if taq else "",
        })

    # ضباط "صافي" (تشغيلهم عمل إداري عام بلا خدمة محددة) يتحطوا في أدوار بالإدارة
    for r in full["rows"]:
        if r["group"] != "صافي" or r["services"]:
            continue
        if _norm_admin(r["note"]) not in PLAIN_ADMIN_DUTY:
            continue
        officer = officers.get(r["id"], {})
        entries.append({
            "id": next_id(entries, "DS", width=4), "category": CATEGORY_ADMIN_ROLES,
            "service": officer.get("post") or "عمل بالإدارة", "shift": "",
            "officer_id": r["id"], "officer_name": r["name"],
            "requirements": [], "tags": [], "note": "",
        })
    return entries


def get_day_services(data, day):
    """بيرجّع خدمات اليوم من الذاكرة بس — من غير أي حفظ. أول ما يوم قديم
    يتفتح بيتشتق مبدئيًا هنا في نسخة data المحمّلة، لكن التثبيت (persist)
    بيحصل بس لو الراوت اللي نادى الدالة دي فعلاً بيعدّل حاجة ويحفظ بعدها —
    عشان القراءة المجردة (GET) تفضل من غير أي أثر جانبي على data.json.

    أول تجهيز لأي يوم بيضيف قيادة الإدارة تلقائيًا (تشغيلهم ثابت يوميًا).
    الأيام المحفوظة بالفعل مابتتلمسش — لو حذفت المدير من يوم معيّن مش
    هيرجع تاني، ولا الأيام القديمة في الأرشيف بتتغيّر بأثر رجعي."""
    if day not in data["day_services"]:
        entries = _derive_day_services(data, day) if day in data["duties"] else []
        entries += _command_entries(data, day, entries)
        data["day_services"][day] = entries
    return data["day_services"][day]


def build_board(data, day):
    """لوحة التشغيل المختصرة — قايمة خدمات حرة قابلة للتعديل الكامل، بالإضافة
    إلى الراحات/التقصيرات/الخوارج/الصافي المحسوبة من حالة الضباط زي ما هي.

    أي خانة عليها وسم (تاج) — زي "مباراة" أو "خطة انتشار" — بتتشال من كرت
    تصنيفها العادي وتتحط في مجموعة "الخدمات الخاصة" منفصلة بصريًا، لكنها
    تفضل منطقيًا تصنيفها الأصلي (غالبًا الخدمات الطارئة) زي ما هو مخزّن.
    """
    entries = get_day_services(data, day)
    tagged = [e for e in entries if e.get("tags")]
    untagged = [e for e in entries if not e.get("tags")]

    order = data["board_categories"]
    by_cat = {c: [] for c in order}
    for e in untagged:
        by_cat.setdefault(e["category"], []).append(e)
    # التصنيفات الأساسية بتظهر دايمًا حتى لو فاضية — عشان يفضل فيها زرار
    # «＋ إضافة» وتقدر تبدأ يوم جديد من الصفر. التصنيفات الإضافية اللي
    # اتكتبت بالإيد بتظهر بس لما يكون فيها خدمات فعلًا.
    categories = [{"name": c, "entries": by_cat[c]} for c in order]
    categories += [{"name": c, "entries": by_cat[c]} for c in by_cat if c not in order and by_cat[c]]

    by_tag = {}
    for e in tagged:
        for t in e["tags"]:
            by_tag.setdefault(t, []).append(e)
    special = [{"tag": t, "entries": es, "of_category": es[0]["category"]}
               for t, es in by_tag.items()]

    full = summarise(data, day)

    def officer(r):
        return {"id": r["id"], "name": r["name"], "role": r["role"]}

    rests, taqseeras, outsiders, net = [], [], [], []
    for r in full["rows"]:
        grp, bucket = r["group"], r["bucket"]
        if grp == "خوارج":
            label = (r["leave"] or {}).get("type", bucket)
            if bucket == "تقصيرة":
                taqseeras.append({**officer(r), "note": r["note"]})
            elif bucket == "راحة":
                lv = r["leave"] or {}
                rests.append({**officer(r), "type": label, "start": lv.get("start"),
                             "end": lv.get("end"), "return_date": lv.get("return_date"),
                             "source": r["note"]})
            else:                                    # طارئة / غياب / مرضي / فرقة / انتداب
                outsiders.append({**officer(r), "reason": label, "note": r["note"]})
        elif grp == "صافي":
            net.append({**officer(r), "post": r["note"] or ""})

    return {
        "date": day, "categories": categories, "special": special,
        "rests": rests, "taqseeras": taqseeras, "outsiders": outsiders, "net": net,
    }


def clean_requirements(raw):
    out = []
    for it in (raw or []):
        label = str(it.get("label", "")).strip()
        if not label:
            continue
        try:
            count = int(it.get("count", 0))
        except (TypeError, ValueError):
            count = 0
        out.append({"label": label, "count": max(count, 0), "note": str(it.get("note", "")).strip()})
    return out


def remember_tags(data, tags):
    for t in tags:
        if t and t not in data["service_tags"]:
            data["service_tags"].append(t)


def remember_category(data, cat):
    if cat and cat not in data["board_categories"]:
        data["board_categories"].append(cat)
