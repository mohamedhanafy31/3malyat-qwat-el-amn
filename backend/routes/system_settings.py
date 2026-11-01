"""معاينة التصدير، وإعدادات النظام اللي بيتحكم فيها المدير."""
import base64

from flask import Blueprint, jsonify, request

from .. import export_preview
from ..settings import read_settings, write_settings

bp = Blueprint("system_settings", __name__)

# الإعدادات المسموح للمدير يغيّرها من الواجهة، وقيمتها الافتراضية.
EDITABLE = {"ops_confirm_other_days": True}


def public_settings():
    stored = read_settings()
    return {key: bool(stored.get(key, default)) for key, default in EDITABLE.items()}


@bp.post("/api/export-preview")
def preview_export():
    kind = request.args.get("kind", "")
    try:
        content = request.get_data(cache=False)
        pages, engine = export_preview.to_pages(content, kind)
    except ValueError as exc:
        return jsonify(error=str(exc), code="invalid"), 400
    except export_preview.PreviewUnavailable as exc:
        return jsonify(error=str(exc), code="preview_unavailable"), 503
    response = jsonify(pages=[f"data:image/png;base64,{base64.b64encode(page).decode()}" for page in pages],
                       engine=engine,
                       missing_fonts=export_preview.missing_fonts(content, kind) if engine == "libreoffice" else [])
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/api/settings")
def get_settings():
    return jsonify(settings=public_settings())


@bp.put("/api/settings")
def update_settings():
    body = request.get_json(silent=True) or {}
    unknown = set(body) - set(EDITABLE)
    if unknown or not all(isinstance(value, bool) for value in body.values()):
        return jsonify(error="إعداد غير معروف أو قيمة غير صالحة.", code="invalid"), 400
    write_settings({**read_settings(), **body})
    return jsonify(settings=public_settings())
