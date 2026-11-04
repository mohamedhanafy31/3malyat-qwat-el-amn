"""مجموعات طباعة اليوميات: كل مجموعة اسم حر (ضابط أو جهة) ويومياتها.

المجموعات السبعة الأساسية بتتقري من DEFAULTS طول ما مفتاح `print_collections`
مش موجود في core.json. أول تعديل بيكتب القايمة كلها، فبعد كده المحذوف مايرجعش
حتى لو القايمة فضيت.
"""
from copy import deepcopy
from uuid import uuid4

from .text import norm

# الترتيب هنا هو ترتيب الطباعة جوه المجموعة.
PRINT_KINDS = {
    "service_order": "أمر الخدمة",
    "board": "التفصيلية",
    "regularity": "الانتظامات",
    "duty": "الضباط",
    "afraad": "الأفراد",
    "campaign": "الحملة",
    "formation_morning": "خط تشكيل صبح",
    "formation_night": "خط تشكيل ليل",
}
_MAX_LABEL = 60
_SET = ["board", "regularity", "duty", "afraad"]

DEFAULTS = [
    {"id": "pc-ahmed-samir", "label": "احمد بيه سمير", "kinds": ["board"]},
    {"id": "pc-mohamed-fouad", "label": "محمد بيه فؤاد", "kinds": _SET},
    {"id": "pc-mohamed-neama", "label": "محمد بيه نعامة", "kinds": _SET[1:] + ["campaign"]},
    {"id": "pc-hamdy-elnaggar", "label": "حمدي بيه النجار", "kinds": _SET[1:]},
    {"id": "pc-senior-officer", "label": "ضابط عظيم", "kinds": _SET},
    {"id": "pc-service-order", "label": "امر الخدمة", "kinds": ["service_order"] + _SET[1:]},
    {"id": "pc-hakamdar", "label": "الحكمدار", "kinds": _SET},
]


class CollectionError(ValueError):
    """بيانات مجموعة غير صالحة، والرسالة بتتعرض للمستخدم."""


def listing(data):
    if "print_collections" in data:
        return data["print_collections"]
    return deepcopy(DEFAULTS)


def _clean(payload, others):
    label = " ".join(str(payload.get("label") or "").split())
    if not label:
        raise CollectionError("اكتب اسم المجموعة.")
    if len(label) > _MAX_LABEL:
        raise CollectionError(f"اسم المجموعة أطول من {_MAX_LABEL} حرف.")
    if any(norm(item["label"]) == norm(label) for item in others):
        raise CollectionError("فيه مجموعة بنفس الاسم.")
    kinds = payload.get("kinds")
    if not isinstance(kinds, list) or any(kind not in PRINT_KINDS for kind in kinds):
        raise CollectionError("نوع يومية غير معروف.")
    if not kinds:
        raise CollectionError("اختار يومية واحدة على الأقل.")
    return {"label": label, "kinds": [kind for kind in PRINT_KINDS if kind in kinds]}


def create(data, payload):
    items = listing(data)
    item = {"id": f"pc-{uuid4().hex[:10]}", **_clean(payload, items)}
    data["print_collections"] = [*items, item]
    return item


def update(data, collection_id, payload):
    items = listing(data)
    item = next((row for row in items if row["id"] == collection_id), None)
    if item is None:
        raise KeyError(collection_id)
    item.update(_clean(payload, [row for row in items if row is not item]))
    data["print_collections"] = items
    return item


def delete(data, collection_id):
    items = listing(data)
    kept = [row for row in items if row["id"] != collection_id]
    if len(kept) == len(items):
        raise KeyError(collection_id)
    data["print_collections"] = kept
