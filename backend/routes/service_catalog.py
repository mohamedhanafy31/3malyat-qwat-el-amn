"""دليل الخدمات — توليد أولي من قالب اعداد الخدمات، وبعدها إضافة/تعديل/حذف حر
+ صور الموقع (مخزّنة كملفات، مش base64 جوّه الـJSON)."""
import uuid

from flask import Blueprint, jsonify, request, send_from_directory

from .. import changes
from .. import service_catalog as catalog_lib
from ..repo import Repos
from ..store import AbortRequest, load_data, revision, stale_revision, with_data
from ..utils import json_payload
from .. import service_lines as lines_lib
from ..constants import CAMPAIGN_LORRIES

bp = Blueprint("service_catalog", __name__)


@bp.get("/api/service-lines")
def list_service_lines():
    data = load_data(())
    return jsonify({"lines": [_line_view(data, line) for line in lines_lib.lines(data)],
                    "revision": revision(data)})


def _line_view(data, line):
    return {**line,
            "members": [{"id": e.get("id"), "name": e.get("name", "")}
                        for e in lines_lib.members(data, line.get("id"))],
            "lorry_name": lines_lib.lorry_name(line.get("lorry_id"))}


def _line_mutation(payload, line_id=None):
    def mutate(data):
        stale = stale_revision(data, payload.get("revision"))
        if stale:
            raise AbortRequest((jsonify({"error": "تغيّرت بيانات الدليل؛ حدّث الصفحة.",
                                         "code": "stale_revision", "revision": stale}), 409))
        entries = lines_lib.lines(data)
        existing = next((line for line in entries if line.get("id") == line_id), None) if line_id else None
        if line_id and not existing:
            raise AbortRequest((jsonify({"error": "خط السير غير موجود."}), 404))
        before = dict(existing) if existing else None
        line, error = lines_lib.apply_line(data, payload, existing)
        if error:
            raise AbortRequest((jsonify({"error": error}), 400))
        if existing:
            existing.clear()
            existing.update(line)
            action = "update"
        else:
            entries.append(line)
            action = "create"
        changes.record(data, "service_line", line["id"], action,
                       before=before, after=dict(line),
                       text=f"{'تعديل' if action == 'update' else 'إضافة'} خط سير «{line.get('name', '')}»")
        return jsonify(_line_view(data, line)), 200 if before else 201
    return with_data(mutate, ())


@bp.post("/api/service-lines")
def add_service_line():
    return _line_mutation(json_payload())


@bp.patch("/api/service-lines/<line_id>")
def edit_service_line(line_id):
    return _line_mutation(json_payload(), line_id)


@bp.delete("/api/service-lines/<line_id>")
def delete_service_line(line_id):
    payload = json_payload()

    def mutate(data):
        stale = stale_revision(data, payload.get("revision"))
        if stale:
            raise AbortRequest((jsonify({"error": "تغيّرت بيانات الدليل؛ حدّث الصفحة.",
                                         "code": "stale_revision", "revision": stale}), 409))
        entries = lines_lib.lines(data)
        line = next((item for item in entries if item.get("id") == line_id), None)
        if not line:
            raise AbortRequest((jsonify({"error": "خط السير غير موجود."}), 404))
        entries.remove(line)
        changes.record(data, "service_line", line_id, "delete", before=dict(line),
                       text=f"حذف خط سير «{line.get('name', '')}»")
        return jsonify({"ok": True})

    return with_data(mutate, ())


@bp.get("/api/service-catalog")
def list_catalog():
    data = load_data(())
    entries = sorted(catalog_lib.catalog(data), key=lambda e: e.get("order", 0))
    return jsonify({
        "entries": entries,
        "seeded": catalog_lib.is_seeded(data),
        "periods": catalog_lib.PERIODS,
        "kinds": catalog_lib.KINDS,
        "post_types": catalog_lib.POST_TYPES,
        "service_tags": Repos(data).config.tags(),
    })


@bp.post("/api/service-catalog/seed")
def seed_catalog():
    def mutate(data):
        if catalog_lib.is_seeded(data):
            raise AbortRequest((jsonify({"error": "يحتوي الدليل على بيانات بالفعل."}), 409))
        entries = catalog_lib.seed_from_counts_template(data)
        return jsonify({"entries": entries}), 201

    return with_data(mutate, ())


@bp.post("/api/service-catalog/entries")
def add_entry():
    payload = json_payload()
    name = str(payload.get("name", "")).strip()
    if not name:
        return jsonify({"error": "اسم الخدمة مطلوب."}), 400

    def mutate(data):
        entries = catalog_lib.catalog(data)
        entry = catalog_lib.blank_entry(catalog_lib.new_id(data), name)
        entry, err = catalog_lib.apply_entry(data, entry, payload)
        if err:
            raise AbortRequest((jsonify({"error": err}), 400))
        entry["order"] = len(entries)
        entries.append(entry)
        return jsonify(entry), 201

    return with_data(mutate, ())


@bp.patch("/api/service-catalog/entries/<entry_id>")
def edit_entry(entry_id):
    payload = json_payload()

    def mutate(data):
        entries = catalog_lib.catalog(data)
        entry = next((e for e in entries if e["id"] == entry_id), None)
        if not entry:
            raise AbortRequest((jsonify({"error": "الخدمة غير موجودة."}), 404))
        entry, err = catalog_lib.apply_entry(data, entry, payload)
        if err:
            raise AbortRequest((jsonify({"error": err}), 400))
        return jsonify(entry)

    return with_data(mutate, ())


@bp.delete("/api/service-catalog/entries/<entry_id>")
def delete_entry(entry_id):
    def mutate(data):
        entries = catalog_lib.catalog(data)
        entry = next((e for e in entries if e["id"] == entry_id), None)
        if not entry:
            raise AbortRequest((jsonify({"error": "الخدمة غير موجودة."}), 404))
        # صور الموقع بتاعته ملهاش لازمة برّه الصف ده — بتتمسح معاه
        for filename in list(entry.get("location_images") or []):
            catalog_lib.remove_image(entry, filename)
        entries.remove(entry)
        return jsonify({"ok": True})

    return with_data(mutate, ())


@bp.post("/api/service-catalog/entries/<entry_id>/images")
def upload_image(entry_id):
    file = request.files.get("image")
    if not file or not file.filename:
        return jsonify({"error": "لا توجد صورة مرفوعة."}), 400
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in catalog_lib.ALLOWED_IMAGE_EXT:
        return jsonify({"error": "امتداد الصورة غير مدعوم (png/jpg/jpeg/webp فقط)."}), 400
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > catalog_lib.MAX_IMAGE_BYTES:
        limit_mb = catalog_lib.MAX_IMAGE_BYTES // (1024 * 1024)
        return jsonify({"error": f"حجم الصورة أكبر من الحد المسموح ({limit_mb}MB)."}), 400

    images_dir = catalog_lib.images_dir()
    images_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{entry_id}-{uuid.uuid4().hex[:8]}.{ext}"
    target = images_dir / filename
    file.save(target)

    def mutate(data):
        entries = catalog_lib.catalog(data)
        entry = next((e for e in entries if e["id"] == entry_id), None)
        if not entry:
            raise AbortRequest((jsonify({"error": "الخدمة غير موجودة."}), 404))
        catalog_lib.add_image(entry, filename)
        return jsonify(entry), 201

    # الملف بيتكتب على القرص **قبل** ما نضمن إن السجل نفسه فعلًا اتحفظ —
    # لو الخدمة مش موجودة (404) أو الحفظ نفسه وقع لأي سبب، الملف بيفضل
    # ملف يتيم من غير أي مرجع ليه. الاسم فيه UUID عشوائي فمفيش داعي نقلق
    # من تعارض أسماء لو حد رفع تاني في نفس اللحظة.
    try:
        result = with_data(mutate, ())
    except Exception:
        target.unlink(missing_ok=True)
        raise
    status = result[1] if isinstance(result, tuple) else getattr(result, "status_code", 200)
    if status >= 400:
        target.unlink(missing_ok=True)
    return result


@bp.delete("/api/service-catalog/entries/<entry_id>/images/<filename>")
def delete_image(entry_id, filename):
    def mutate(data):
        entries = catalog_lib.catalog(data)
        entry = next((e for e in entries if e["id"] == entry_id), None)
        if not entry:
            raise AbortRequest((jsonify({"error": "الخدمة غير موجودة."}), 404))
        if not catalog_lib.remove_image(entry, filename):
            raise AbortRequest((jsonify({"error": "الصورة غير موجودة."}), 404))
        return jsonify(entry)

    return with_data(mutate, ())


@bp.get("/uploads/service-catalog/<filename>")
def serve_image(filename):
    return send_from_directory(catalog_lib.images_dir(), filename)
