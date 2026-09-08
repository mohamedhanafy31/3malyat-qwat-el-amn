"""كتالوج الخدمات — إضافة/تعديل/حذف.

الكتالوج هو المرجع الوحيد لأسماء الخدمات: التكليفات بتشاور عليه بالـid،
فإعادة تسمية خدمة بقت عملية عرض بحتة ومابتفصلش أي تكليف. قبل كده كانت
اللوحة بتخزّن اسم الخدمة كنص، فإعادة التسمية كانت بتمسح تكليف الضابط
من يومية التشغيل في صمت وتسيبه ظاهر على اللوحة بالاسم القديم.
"""
from flask import Blueprint, jsonify

from ..constants import (
    SERVICE_DOCUMENTS, SERVICE_KINDS, SERVICE_SECTIONS, SHIFTS,
)
from ..store import AbortRequest, next_id, with_data
from ..text import norm
from ..utils import json_payload

bp = Blueprint("services", __name__)

DEFAULT_NEEDS = {"officer": True, "individual": False, "unit": False, "vehicle": False}


def _clean_shifts(raw, fallback=None):
    if raw is None:
        return list(fallback if fallback is not None else SHIFTS)
    shifts = [s for s in SHIFTS if s in (raw or [])]      # بالترتيب الثابت
    return shifts or list(SHIFTS)


def _clean_docs(raw, fallback=None):
    if raw is None:
        return list(fallback if fallback is not None else ["board"])
    docs = [d for d in SERVICE_DOCUMENTS if d in (raw or [])]
    return docs or ["board"]


def _clean_needs(raw, fallback=None):
    base = dict(fallback or DEFAULT_NEEDS)
    for key in DEFAULT_NEEDS:
        if isinstance(raw, dict) and key in raw:
            base[key] = bool(raw[key])
    return base


def _clean_aliases(raw, name):
    """صور الاسم اللي بتتطابق عليها الخدمة عند الاستيراد — دايمًا فيها الاسم نفسه."""
    out = {norm(name)}
    for a in (raw or []):
        a = norm(a)
        if a:
            out.add(a)
    return sorted(out)


@bp.post("/api/services")
def add_service():
    payload = json_payload()
    name = str(payload.get("name", "")).strip()
    kind = str(payload.get("kind", "")).strip()
    if not name:
        return jsonify({"error": "اسم الخدمة مطلوب."}), 400
    if kind not in SERVICE_KINDS:
        return jsonify({"error": "تصنيف الخدمة غير صحيح."}), 400
    section = str(payload.get("section", "")).strip() or SERVICE_SECTIONS[1]
    if section not in SERVICE_SECTIONS:
        return jsonify({"error": "قسم اللوحة غير صحيح."}), 400

    def mutate(data):
        if any(norm(s["name"]) == norm(name) for s in data["services"]):
            raise AbortRequest((jsonify({"error": "الخدمة موجودة بالفعل."}), 409))
        svc = {
            "id": next_id(data["services"], "SVC"),
            "name": name,
            "board_label": str(payload.get("board_label", "")).strip() or name,
            "sub": str(payload.get("sub", "")).strip(),
            "kind": kind,
            "section": section,
            "standing": bool(payload.get("standing", False)),
            "shifts": _clean_shifts(payload.get("shifts")),
            "default_strength": str(payload.get("default_strength", "")).strip(),
            "default_weapon": str(payload.get("default_weapon", "")).strip(),
            "default_time": str(payload.get("default_time", "")).strip(),
            "party": str(payload.get("party", "")).strip(),
            "needs": _clean_needs(payload.get("needs")),
            "appears_in": _clean_docs(payload.get("appears_in")),
            "aliases": _clean_aliases(payload.get("aliases"), name),
        }
        data["services"].append(svc)
        return jsonify(svc), 201

    return with_data(mutate)


@bp.patch("/api/services/<service_id>")
def edit_service(service_id):
    """تعديل خدمة. تغيير التصنيف بيغيّر كل الإجماليات التاريخية على طول —
    وده مقصود، لأن التصنيف معرفة تشغيلية بتتصحّح بأثر رجعي."""
    payload = json_payload()

    def mutate(data):
        svc = next((s for s in data["services"] if s.get("id") == service_id), None)
        if not svc:
            raise AbortRequest((jsonify({"error": "الخدمة غير موجودة."}), 404))

        if "kind" in payload:
            if payload["kind"] not in SERVICE_KINDS:
                raise AbortRequest((jsonify({"error": "تصنيف الخدمة غير صحيح."}), 400))
            svc["kind"] = payload["kind"]
        if "section" in payload:
            if payload["section"] not in SERVICE_SECTIONS:
                raise AbortRequest((jsonify({"error": "قسم اللوحة غير صحيح."}), 400))
            svc["section"] = payload["section"]
        if "name" in payload:
            name = str(payload["name"]).strip()
            if not name:
                raise AbortRequest((jsonify({"error": "اسم الخدمة مطلوب."}), 400))
            clash = any(norm(s["name"]) == norm(name) and s["id"] != service_id
                        for s in data["services"])
            if clash:
                raise AbortRequest((jsonify({"error": "فيه خدمة تانية بنفس الاسم."}), 409))
            # الاسم القديم بيتحفظ كـalias عشان الاستيراد يفضل يتعرّف عليه
            svc["aliases"] = _clean_aliases(
                list(svc.get("aliases", [])) + [svc["name"]], name)
            # الاسم المطبوع على اللوحة بيمشي مع الاسم إلا لو اتخصّص بإيد
            # (زي «سوميد» لـ«هدف سوميد») — ساعتها بيفضل زي ما هو
            if not svc.get("board_label") or svc["board_label"] == svc["name"]:
                svc["board_label"] = name
            svc["name"] = name
        for key in ("board_label", "sub", "default_strength", "default_weapon",
                    "default_time", "party"):
            if key in payload:
                svc[key] = str(payload[key]).strip()
        if "standing" in payload:
            svc["standing"] = bool(payload["standing"])
        if "shifts" in payload:
            svc["shifts"] = _clean_shifts(payload["shifts"], svc.get("shifts"))
        if "appears_in" in payload:
            svc["appears_in"] = _clean_docs(payload["appears_in"], svc.get("appears_in"))
        if "needs" in payload:
            svc["needs"] = _clean_needs(payload["needs"], svc.get("needs"))
        if "aliases" in payload:
            svc["aliases"] = _clean_aliases(payload["aliases"], svc["name"])
        return jsonify(svc)

    return with_data(mutate)


@bp.delete("/api/services/<service_id>")
def delete_service(service_id):
    """الحذف ممنوع طول ما الخدمة مستخدمة في أي يوم — في يومية التشغيل أو
    على اللوحة. قبل كده كان الفحص على يومية التشغيل بس، فكان ينفع تمسح
    خدمة لسه على اللوحة وتسيب خانتها بلا مرجع."""
    def mutate(data):
        used = sum(1 for day in data.get("duties", {}).values() for e in day.values()
                   for i in e.get("items", []) if i.get("service_id") == service_id)
        used += sum(1 for day in data.get("day_assignments", {}).values() for a in day
                    if a.get("service_id") == service_id)
        if used:
            raise AbortRequest((jsonify({
                "error": f"الخدمة مستخدمة في {used} تكليف. غيّر تصنيفها أو اسمها بدل حذفها."}), 409))
        before = len(data["services"])
        data["services"] = [s for s in data["services"] if s.get("id") != service_id]
        if len(data["services"]) == before:
            raise AbortRequest((jsonify({"error": "الخدمة غير موجودة."}), 404))
        return jsonify({"ok": True})

    return with_data(mutate)
