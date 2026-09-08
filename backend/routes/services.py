"""كتالوج الخدمات — إضافة/تعديل/حذف."""
from flask import Blueprint, jsonify

from ..constants import SERVICE_KINDS
from ..store import AbortRequest, next_id, with_data
from ..utils import json_payload

bp = Blueprint("services", __name__)


@bp.post("/api/services")
def add_service():
    payload = json_payload()
    name = str(payload.get("name", "")).strip()
    kind = str(payload.get("kind", "")).strip()
    if not name:
        return jsonify({"error": "اسم الخدمة مطلوب."}), 400
    if kind not in SERVICE_KINDS:
        return jsonify({"error": "تصنيف الخدمة غير صحيح."}), 400

    def mutate(data):
        if any(s["name"] == name for s in data["services"]):
            raise AbortRequest((jsonify({"error": "الخدمة موجودة بالفعل."}), 409))
        svc = {"id": next_id(data["services"], "SVC"), "name": name, "kind": kind,
               "standing": bool(payload.get("standing", False))}
        data["services"].append(svc)
        return jsonify(svc), 201

    return with_data(mutate)


@bp.patch("/api/services/<service_id>")
def edit_service(service_id):
    """تعديل تصنيف خدمة — بيغيّر كل الإجماليات التاريخية على طول."""
    payload = json_payload()

    def mutate(data):
        svc = next((s for s in data["services"] if s.get("id") == service_id), None)
        if not svc:
            raise AbortRequest((jsonify({"error": "الخدمة غير موجودة."}), 404))
        if "kind" in payload:
            if payload["kind"] not in SERVICE_KINDS:
                raise AbortRequest((jsonify({"error": "تصنيف الخدمة غير صحيح."}), 400))
            svc["kind"] = payload["kind"]
        if "name" in payload:
            name = str(payload["name"]).strip()
            if not name:
                raise AbortRequest((jsonify({"error": "اسم الخدمة مطلوب."}), 400))
            svc["name"] = name
        if "standing" in payload:
            svc["standing"] = bool(payload["standing"])
        return jsonify(svc)

    return with_data(mutate)


@bp.delete("/api/services/<service_id>")
def delete_service(service_id):
    def mutate(data):
        used = sum(1 for day in data["duties"].values() for e in day.values()
                   for i in e.get("items", []) if i.get("service_id") == service_id)
        if used:
            raise AbortRequest((jsonify({"error": f"الخدمة مستخدمة في {used} تكليف. غيّر تصنيفها بدل حذفها."}), 409))
        before = len(data["services"])
        data["services"] = [s for s in data["services"] if s.get("id") != service_id]
        if len(data["services"]) == before:
            raise AbortRequest((jsonify({"error": "الخدمة غير موجودة."}), 404))
        return jsonify({"ok": True})

    return with_data(mutate)
