"""اعداد الخدمات — API القالب الثابت ونسخة كل يوم منه.

نسخة اليوم بتتفرّد أول ما تتلمس بتعديل فعلي (`for_day_entries`) — GET بيرجّع
نسخة القالب الحيّة من غير ما يكتبها، عشان يوم محدش فتحه أصلًا مايتسجّلش له
مدخل فاضي في الملف.
"""
from flask import Blueprint, jsonify

from .. import counts as counts_lib
from .. import day_status
from ..repo import Repos
from ..store import AbortRequest, load_data, with_data
from ..utils import canonical_day, json_payload

bp = Blueprint("counts", __name__)


def _guard_day(data, day):
    """اليوم المقفول بيرفض الكتابة هنا زي ما بيرفضها على اللوحة بالظبط —
    من غير كده الورقة دي كانت باب جانبي بيعدّل يوم معتمد."""
    ok, err = day_status.check_open(data, day)
    if not ok:
        raise AbortRequest((jsonify({"error": err}), 409))


def _clean_payload(data, payload, current=None):
    """يرجّع (fields, error). fields جاهزة تتحط في الصف، أو error لو في مشكلة."""
    out = dict(current or {})
    if "block" in payload:
        block = str(payload["block"]).strip()
        if block not in counts_lib.BLOCKS:
            return None, "القسم غير صحيح."
        out["block"] = block
    if "name" in payload:
        out["name"] = str(payload["name"]).strip()
    if "party" in payload:
        out["party"] = str(payload["party"]).strip()
    if "count" in payload:
        try:
            out["count"] = max(0, int(payload["count"]))
        except (TypeError, ValueError):
            return None, "عدد المجندين لازم يكون رقم."
    if not out.get("name"):
        return None, "اسم الخدمة مطلوب."
    out.setdefault("block", counts_lib.BLOCKS[0])
    out.setdefault("count", 0)
    out.setdefault("party", "")
    out.setdefault("name", "")
    return out, None


@bp.get("/api/counts/<day>")
def get_counts(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    return jsonify(counts_lib.build(load_data(), day))


@bp.get("/api/counts/template")
def get_template():
    data = load_data()
    return jsonify({
        "entries": counts_lib.peek_template(data),
        "seeded": counts_lib.is_seeded(data),
    })


@bp.post("/api/counts/template/seed")
def seed_template():
    def mutate(data):
        if counts_lib.is_seeded(data):
            raise AbortRequest((jsonify({"error": "القالب فيه بيانات بالفعل."}), 409))
        entries = counts_lib.seed_template(data)
        return jsonify({"entries": entries}), 201

    return with_data(mutate)


@bp.post("/api/counts/template/entries")
def add_template_entry():
    payload = json_payload()

    def mutate(data):
        fields, err = _clean_payload(data, payload)
        if err:
            raise AbortRequest((jsonify({"error": err}), 400))
        entries = counts_lib.for_template(data)
        fields["id"] = counts_lib.new_entry_id(data, entries)
        fields["order"] = len(entries)
        entries.append(fields)
        return jsonify(fields), 201

    return with_data(mutate)


@bp.patch("/api/counts/template/entries/<entry_id>")
def edit_template_entry(entry_id):
    payload = json_payload()

    def mutate(data):
        entries = counts_lib.for_template(data)
        entry = next((e for e in entries if e["id"] == entry_id), None)
        if not entry:
            raise AbortRequest((jsonify({"error": "الصف غير موجود."}), 404))
        fields, err = _clean_payload(data, payload, current=entry)
        if err:
            raise AbortRequest((jsonify({"error": err}), 400))
        fields["id"], fields["order"] = entry["id"], entry.get("order", 0)
        entry.clear()
        entry.update(fields)
        return jsonify(entry)

    return with_data(mutate)


@bp.delete("/api/counts/template/entries/<entry_id>")
def delete_template_entry(entry_id):
    def mutate(data):
        config = Repos(data).config
        kept = [e for e in config.template() if e.id != entry_id]
        if len(kept) == len(config.template_rows()):
            raise AbortRequest((jsonify({"error": "الصف غير موجود."}), 404))
        config.save_template(kept)
        return jsonify({"ok": True})

    return with_data(mutate)


@bp.post("/api/counts/<day>/entries")
def add_day_entry(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    payload = json_payload()

    def mutate(data):
        _guard_day(data, day)
        fields, err = _clean_payload(data, payload)
        if err:
            raise AbortRequest((jsonify({"error": err}), 400))
        entries = counts_lib.for_day_entries(data, day)
        fields["id"] = counts_lib.new_entry_id(data, entries)
        fields["order"] = len(entries)
        entries.append(fields)
        return jsonify(fields), 201

    return with_data(mutate)


@bp.patch("/api/counts/<day>/entries/<entry_id>")
def edit_day_entry(day, entry_id):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    payload = json_payload()

    def mutate(data):
        _guard_day(data, day)
        entries = counts_lib.for_day_entries(data, day)
        entry = next((e for e in entries if e["id"] == entry_id), None)
        if not entry:
            raise AbortRequest((jsonify({"error": "الصف غير موجود."}), 404))
        fields, err = _clean_payload(data, payload, current=entry)
        if err:
            raise AbortRequest((jsonify({"error": err}), 400))
        fields["id"], fields["order"] = entry["id"], entry.get("order", 0)
        entry.clear()
        entry.update(fields)
        return jsonify(entry)

    return with_data(mutate)


@bp.delete("/api/counts/<day>/entries/<entry_id>")
def delete_day_entry(day, entry_id):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400

    def mutate(data):
        _guard_day(data, day)
        # `for_day_entries` بتفرد نسخة اليوم من القالب أول تعديل — لازم
        # تتنادي قبل الحذف عشان الحذف يلمس نسخة اليوم مش القالب
        entries = counts_lib.for_day_entries(data, day)
        kept = [e for e in entries if e["id"] != entry_id]
        if len(kept) == len(entries):
            raise AbortRequest((jsonify({"error": "الصف غير موجود."}), 404))
        entries[:] = kept
        return jsonify({"ok": True})

    return with_data(mutate)


@bp.patch("/api/counts/<day>/emergency/<assignment_id>")
def set_emergency_count(day, assignment_id):
    """عدد مجندين خدمة طارئة — بيتكتب على صف التكليف في اليومية التفصيلية،
    مش في سجل تاني هنا. فنفس الرقم بيتعدّل من الصفحتين وبيفضل واحد."""
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    payload = json_payload()
    try:
        count = max(0, int(payload.get("count", 0)))
    except (TypeError, ValueError):
        return jsonify({"error": "عدد المجندين لازم يكون رقم."}), 400

    def mutate(data):
        _guard_day(data, day)
        row, err = counts_lib.set_emergency_count(data, day, assignment_id, count)
        if err:
            raise AbortRequest((jsonify({"error": err}), 404))
        return jsonify(counts_lib.build(data, day))

    return with_data(mutate)


@bp.post("/api/counts/<day>/reset")
def reset_day(day):
    """يرجّع اليوم لنسخة القالب الحالية — بيمسح تخصيص اليوم ده بس، وما
    بيلمسش القالب ولا أي يوم تاني."""
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400

    def mutate(data):
        _guard_day(data, day)
        Repos(data).days.reset_counts(day)
        return jsonify(counts_lib.build(data, day))

    return with_data(mutate)
