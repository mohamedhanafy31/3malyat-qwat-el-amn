"""دليل الخدمات — مرجع ثابت لكل خدمة أساسية عندنا (اسمها، فترتها، قوامها
المطلوب، وتعليماتها) — عكس قالب اعداد الخدمات اللي بيتابع عدد المجندين
يوم بيوم، الدليل هنا مرجعي بحت ومستقل بعد أول توليد.

بيتوّلد أول مرة من `counts.counts_template` (بلوكي «صباحية»/«ليلية» بس —
الطوارئ مصدرها اليومية التفصيلية مش هنا)، وبعدها بيتعدّل بإيد المشغّل
لوحده — تعديل قالب الاعداد بعد كده ما بيأثّرش على الدليل والعكس.
"""
from .store import reserve_id
from .text import norm
from .utils import MAX_LEN

PERIODS = ["صباحية وليلية", "صباحية بس", "ليلية بس"]
KINDS = ["داخلية", "خارجية"]
POST_TYPES = ["ارتكاز", "قول"]

MAX_INSTRUCTIONS = 500
MAX_LOCATION_TEXT = 500


def catalog(data):
    entries = data.setdefault("service_catalog", [])
    # صفوف اتسجّلت قبل ما حقلي الموقع يتضافوا — بيترجّعوا افتراضي بدل
    # ما يختفوا من الـJSON، عشان الفرونت إند ما يحتاجش يعرف الفرق.
    for e in entries:
        e.setdefault("location_text", "")
        e.setdefault("location_images", [])
        e.setdefault("post_type", "")
        e.setdefault("command_officers", 0)
        e.setdefault("command_individuals", 0)
        e.setdefault("tags", [])
        e.pop("officers_count", None)
        e.pop("command_by", None)
    return entries


def new_id(data):
    return reserve_id(data, "SVC", catalog(data))


def is_seeded(data):
    return bool(catalog(data))


def blank_entry(entry_id, name):
    return {"id": entry_id, "name": name, "period": "", "kind": "", "post_type": "",
            "has_command": False, "command_officers": 0, "command_individuals": 0,
            "count": 0, "weapon": "", "instructions": "", "location_text": "",
            "location_images": [], "tags": [], "order": 0}


def guess_post_type(name):
    """«ارتكاز» أو «قول» لو اسم الخدمة بادئ بيها فعلًا (زي «ارتكاز الحي
    الحكومي» و«قول السلام») — تلميح بس، مش إجباري، والمشغّل يقدر يغيّره."""
    name = (name or "").strip()
    for post_type in POST_TYPES:
        if name.startswith(post_type + " "):
            return post_type
    return ""


def apply_entry(data, entry, payload):
    """بيطبّق حقول الطلب على صف الدليل. بترجع (entry, error)."""
    if "name" in payload:
        name = str(payload["name"]).strip()
        if not name:
            return None, "اسم الخدمة مطلوب."
        if len(name) > MAX_LEN["name"]:
            return None, f"اسم الخدمة أطول من الحد المسموح ({MAX_LEN['name']} حرف)."
        entry["name"] = name
    if "period" in payload:
        period = str(payload["period"]).strip()
        if period and period not in PERIODS:
            return None, "فترة الخدمة غير صحيحة."
        entry["period"] = period
    if "kind" in payload:
        kind = str(payload["kind"]).strip()
        if kind and kind not in KINDS:
            return None, "تصنيف الخدمة غير صحيح."
        entry["kind"] = kind
    if "post_type" in payload:
        post_type = str(payload["post_type"]).strip()
        if post_type and post_type not in POST_TYPES:
            return None, "نوع النقطة غير صحيح."
        entry["post_type"] = post_type
    if "count" in payload:
        try:
            entry["count"] = max(0, int(payload["count"]))
        except (TypeError, ValueError):
            return None, "عدد المجندين لازم يكون رقم."
    if "weapon" in payload:
        entry["weapon"] = str(payload["weapon"]).strip()
    if "instructions" in payload:
        instructions = str(payload["instructions"]).strip()
        if len(instructions) > MAX_INSTRUCTIONS:
            return None, f"التعليمات أطول من الحد المسموح ({MAX_INSTRUCTIONS} حرف)."
        entry["instructions"] = instructions
    if "location_text" in payload:
        location_text = str(payload["location_text"]).strip()
        if len(location_text) > MAX_LOCATION_TEXT:
            return None, f"وصف الموقع أطول من الحد المسموح ({MAX_LOCATION_TEXT} حرف)."
        entry["location_text"] = location_text
    if "command_officers" in payload:
        try:
            entry["command_officers"] = max(0, int(payload["command_officers"]))
        except (TypeError, ValueError):
            return None, "عدد ضباط الرئاسة لازم يكون رقم."
    if "command_individuals" in payload:
        try:
            entry["command_individuals"] = max(0, int(payload["command_individuals"]))
        except (TypeError, ValueError):
            return None, "عدد أفراد الرئاسة لازم يكون رقم."
    # لازم بعد command_officers/command_individuals عشان لو الخدمة
    # اتحولت لـ«من غير رئاسة» العددين يترجعوا صفر مهما كانت القيم اللي
    # اتبعتت معاهم في نفس الطلب — مفيش قائم رئاسة من غير رئاسة أصلًا.
    if "has_command" in payload:
        entry["has_command"] = bool(payload["has_command"])
        if not entry["has_command"]:
            entry["command_officers"] = 0
            entry["command_individuals"] = 0
    if "tags" in payload:
        tags = [str(t).strip() for t in payload["tags"] if str(t).strip()]
        entry["tags"] = tags
        from .repo import Repos
        Repos(data).config.add_tags(tags)
    return entry, None


def seed_from_counts_template(data):
    """بيولّد الدليل مرة واحدة من قالب اعداد الخدمات — بلوكي «صباحية»/
    «ليلية» بس. نفس اسم الخدمة اللي متسجّل في البلوكين بيتلمّ في صف
    واحد؛ لو قوامه مختلف بين الصباحية والليلية (بيحصل، «قول السلام»
    مثال حقيقي) بياخد قيمة الصباحية والمشغّل يظبطها بعد كده لو محتاجة."""
    from .counts import peek_template

    entries = catalog(data)
    groups = {}
    for e in peek_template(data):
        if e.get("block") not in ("صباحية", "ليلية"):
            continue
        key = norm(e.get("name", ""))
        if not key:
            continue
        g = groups.setdefault(key, {"صباحية": None, "ليلية": None, "display_name": e["name"]})
        g[e["block"]] = e

    for g in groups.values():
        am, pm = g["صباحية"], g["ليلية"]
        period = "صباحية وليلية" if am and pm else ("صباحية بس" if am else "ليلية بس")
        source = am or pm
        entry = blank_entry(new_id(data), g["display_name"])
        entry.update({
            "period": period,
            "post_type": guess_post_type(g["display_name"]),
            "count": int(source.get("count") or 0),
            "weapon": source.get("weapon", ""),
            "order": len(entries),
        })
        entries.append(entry)
    return entries


# ---------- صور الموقع ----------
# مخزّنة كملفات على القرص جنب data/ (مش base64 جوّه الـJSON) — نفس مبدأ
# باقي السيستم: JSON للبيانات، ملفات للمحتوى التقيل. الاسم اللي بيتسجّل
# في location_images هو اسم الملف بس، والمسار الفعلي بيتحسب من هنا.
ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "webp"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 ميجا للصورة — كفاية لصفحة PDF بجودة عالية


def images_dir():
    from .store import DATA_DIR
    return DATA_DIR / "uploads" / "service_catalog"


def add_image(entry, filename):
    entry.setdefault("location_images", []).append(filename)


def remove_image(entry, filename):
    """بيشيل اسم الملف من الصف ويمسح الملف نفسه من القرص. بيرجع True لو
    الاسم كان موجود فعلًا."""
    images = entry.get("location_images") or []
    if filename not in images:
        return False
    images.remove(filename)
    entry["location_images"] = images
    (images_dir() / filename).unlink(missing_ok=True)
    return True
