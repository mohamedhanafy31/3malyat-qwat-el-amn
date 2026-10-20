"""API لإدارة ملفات الأرشيف اليومية."""

from datetime import date, timedelta
from threading import Thread

from flask import Blueprint, jsonify

from .. import daily_files
from ..utils import canonical_day, json_payload

bp = Blueprint("day_files", __name__)


def _file_rows(folder):
    rows = []
    if not folder.is_dir():
        return rows
    for path in folder.iterdir():
        if not path.is_file() or not daily_files.is_daily_file(path.name):
            continue
        stat = path.stat()
        kind = next(
            (name for name, pattern in daily_files._PATTERNS.items()
             if pattern.match(path.name)),
            "",
        )
        rows.append({
            "kind": kind,
            "name": path.name,
            "size": stat.st_size,
            "mtime": stat.st_mtime,
        })
    return rows


@bp.get("/api/day-files/<day>")
def status(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400

    folder = daily_files.day_folder(day)
    manifest = daily_files._manifest()
    worker = daily_files.worker()
    pending = bool(worker and day in worker.pending())
    return jsonify({
        "day": day,
        "folder": str(folder),
        "exists": folder.is_dir(),
        "files": _file_rows(folder),
        "last_generated": manifest.get(day, {}).get("at"),
        "pending": pending,
        "managed_from": daily_files.managed_from(),
        "enabled": daily_files.enabled(),
    })


@bp.post("/api/day-files/<day>/refresh")
def refresh(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    if not daily_files.enabled():
        return jsonify({"error": "نظام الملفات اليومية متوقف."}), 409

    body = json_payload()
    kinds = body.get("kinds") if "kinds" in body else None
    result = daily_files.write_day_files(day, kinds)
    return jsonify({
        "day": day,
        "folder": result.folder,
        "cloned_from": result.cloned_from,
        "warnings": list(result.warnings),
        "results": result.files,
    })


@bp.post("/api/day-files/refresh-range")
def refresh_range():
    body = json_payload()
    start = canonical_day(body.get("from"))
    end = canonical_day(body.get("to"))
    if not start or not end:
        return jsonify({"error": "تاريخ غير صحيح."}), 400

    first = date.fromisoformat(start)
    last = date.fromisoformat(end)
    if first > last:
        first, last = last, first
    if (last - first).days > 400:
        return jsonify({"error": "النطاق أكبر من 400 يوم."}), 400
    if not daily_files.enabled():
        return jsonify({"error": "نظام الملفات اليومية متوقف."}), 409

    days = [
        (first + timedelta(days=offset)).isoformat()
        for offset in range((last - first).days + 1)
    ]
    worker = daily_files.worker()
    if worker is not None:
        worker.enqueue(days)
    else:
        Thread(
            target=lambda: [daily_files.write_day_files(day) for day in days],
            daemon=True,
        ).start()
    return jsonify({"accepted": len(days)})
