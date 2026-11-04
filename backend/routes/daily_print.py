"""طباعة اليوميات: الحالة، إرسال شغلانة، وإدارة المجموعات."""
from flask import Blueprint, jsonify

from .. import daily_files, daily_print, tech_log
from .. import print_collections as lib
from ..auth import current_actor
from ..auth.audit_log import emit
from ..store import AbortRequest, load_data, with_data
from ..utils import canonical_day, json_payload
from .auth import _is_local_request

bp = Blueprint("daily_print", __name__)


def _print_block_reason():
    """سبب منع الطباعة، أو "" لو متاحة. الطباعة من جهاز المكتب بس."""
    if not _is_local_request():
        return "الطباعة متاحة من جهاز المكتب فقط."
    if not daily_print.available():
        return "الطباعة تحتاج Microsoft Word على جهاز المكتب."
    return ""


@bp.get("/api/daily-print/<day>")
def status(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    jobs = daily_print.QUEUE.snapshot(day)
    idle = {"state": "idle", "docs": {}, "done": 0, "total": 0, "errors": [], "stuck": False}
    collections = [{**item, "status": jobs.get(item["id"], idle)}
                   for item in lib.listing(load_data(()))]
    reason = _print_block_reason()
    return jsonify({
        "day": day,
        "kinds": lib.PRINT_KINDS,
        "documents": {kind: daily_files.document_state(day, kind) for kind in lib.PRINT_KINDS},
        "updating": daily_files.is_updating(day),
        "collections": collections,
        "can_print": not reason,
        "block_reason": reason,
        "printer": daily_print.printer_name() if not reason else "",
        "max_copies": daily_print.MAX_COPIES,
    })


@bp.post("/api/daily-print/jobs")
def create_job():
    reason = _print_block_reason()
    if reason:
        return jsonify({"error": reason, "code": "print_blocked"}), 403
    body = json_payload()
    day = canonical_day(body.get("day"))
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    wanted = body.get("collection_ids")
    if not isinstance(wanted, list) or not wanted:
        return jsonify({"error": "اختار مجموعة واحدة على الأقل."}), 400
    copies = body.get("copies", 1)
    if isinstance(copies, bool) or not isinstance(copies, int) \
            or not 1 <= copies <= daily_print.MAX_COPIES:
        return jsonify({"error": f"عدد النسخ من 1 إلى {daily_print.MAX_COPIES}."}), 400
    known = {item["id"]: item for item in lib.listing(load_data(()))}
    if any(item not in known for item in wanted):
        return jsonify({"error": "مجموعة غير معروفة. حدّث الصفحة."}), 404
    selected = [known[item] for item in known if item in wanted]   # بترتيب الصفحة
    # مسودة أمر الخدمة اللي ماحدش عدّلها مابتتطبعش إلا بموافقة صريحة.
    is_draft = daily_files.document_state(day, "service_order")["state"] == "draft"
    skip = ("service_order",) if is_draft and body.get("include_draft") is not True else ()
    actor = current_actor().get("display_name")
    job = daily_print.QUEUE.submit(day, selected, copies, actor, skip_kinds=skip)
    if job is None:
        return jsonify({"error": "مفيش ملفات جديدة للطباعة: المجموعة في الطابور بالفعل "
                                 "أو كلها مسودة أمر خدمة.", "code": "nothing_to_print"}), 409
    emit("daily_print_started", status=202, job_id=job["id"], day=day, copies=copies,
         total=len(job["items"]), collections=[item["label"] for item in selected])
    tech_log.event("backend.daily_print", "daily_print.job", job=job["id"], day=day,
                   copies=copies, items=len(job["items"]))
    return jsonify({"job_id": job["id"], "total": len(job["items"]),
                    "skipped_draft": bool(skip)}), 202


def _mutate(action):
    def run(data):
        try:
            return action(data)
        except lib.CollectionError as exc:
            raise AbortRequest((jsonify({"error": str(exc)}), 400)) from exc
        except KeyError as exc:
            raise AbortRequest((jsonify({"error": "المجموعة غير موجودة."}), 404)) from exc
    return with_data(run, ())


@bp.post("/api/print-collections")
def create_collection():
    payload = json_payload()
    return _mutate(lambda data: (jsonify(lib.create(data, payload)), 201))


@bp.patch("/api/print-collections/<collection_id>")
def update_collection(collection_id):
    payload = json_payload()
    return _mutate(lambda data: jsonify(lib.update(data, collection_id, payload)))


@bp.delete("/api/print-collections/<collection_id>")
def delete_collection(collection_id):
    def action(data):
        lib.delete(data, collection_id)
        return jsonify({"ok": True})
    return _mutate(action)
