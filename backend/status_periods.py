"""حالات الضابط الممتدة — سجل مدى زمني واحد في ``core.json`` بدل نسخ يومية.

نوعان:

  **مستمرة** («مرضي» و«غياب» و«انتداب»): تبدأ مرة من يومية الضباط وتظل
  فعالة كل يوم بعدها حتى يضغط المستخدم «إيقاف الحالة»؛ يوم الإيقاف هو أول
  يوم عادي. سجلها ``end`` فاضي طول ما هي مفتوحة.

  **محددة المدة** («طارئة»): لازم معها يوم نهاية شامل (``حتى يوم``)، وتنتهي
  لوحدها بعده من غير إيقاف.

سجلات «طارئة» القديمة اللي اتعملت مفتوحة قبل التقسيم ده بتفضل مقروءة وقابلة
للإيقاف زي ما هي، ولو اتحفظت تاني بنهاية بتتحول لمدة محددة في نفس السجل —
لكن مفيش سجل «طارئة» مفتوح جديد يتعمل.
"""
from datetime import date, timedelta

from .store import reserve_id
from .utils import canonical_day


CONTINUOUS_STATUSES = ("مرضي", "غياب", "انتداب")
BOUNDED_STATUSES = ("طارئة",)
# أي حالة من دول مصدرها سجل المدى مش ملف اليوم
PERIOD_STATUSES = CONTINUOUS_STATUSES + BOUNDED_STATUSES


class PeriodError(ValueError):
    """طلب حالة ممتدة غير صالح؛ ``status`` كود HTTP المناسب."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def periods(data):
    return data.setdefault("officer_status_periods", [])


def is_bounded(status):
    return status in BOUNDED_STATUSES


def public(row):
    """شكل السجل للواجهة: الحقول المخزنة + نوعه وهل هو مفتوح."""
    if not row:
        return None
    out = {key: row.get(key, "") for key in ("id", "status", "start", "end", "stopped_on")}
    out["kind"] = "bounded" if is_bounded(row.get("status")) else "continuous"
    out["open_ended"] = not row.get("end")
    # «طارئة» مفتوحة = سجل قديم من قبل إلزام يوم النهاية
    out["legacy_open"] = out["open_ended"] and out["kind"] == "bounded"
    return out


def active_on(data, officer_id, day):
    """السجل الذي يغطي اليوم، أو ``None``."""
    matches = [
        row for row in (data.get("officer_status_periods") or [])
        if row.get("officer_id") == officer_id
        and row.get("start", "") <= day
        and (not row.get("end") or day <= row["end"])
    ]
    return max(matches, key=lambda row: (row.get("start", ""), row.get("id", "")),
               default=None)


def _previous_day(day):
    return (date.fromisoformat(day) - timedelta(days=1)).isoformat()


def clean_end(status, raw_end, day):
    """تحقق من يوم النهاية حسب نوع الحالة. يرجع النهاية القانونية أو يرفع ``PeriodError``."""
    raw_end = str(raw_end or "").strip()
    if status in CONTINUOUS_STATUSES:
        if raw_end:
            raise PeriodError(f"حالة «{status}» مستمرة حتى الإيقاف ولا تقبل يوم نهاية.")
        return ""
    if not raw_end:
        raise PeriodError(f"حالة «{status}» تحتاج يوم نهاية (حتى يوم).")
    end = canonical_day(raw_end)
    # الصيغة المعيارية بس (YYYY-MM-DD) — مقارنة التواريخ هنا نصية
    if not end or end != raw_end:
        raise PeriodError("يوم نهاية الحالة غير صحيح (الصيغة YYYY-MM-DD).")
    if end < day:
        raise PeriodError("يوم نهاية الحالة قبل يوم بدايتها.")
    return end


def start(data, officer_id, status, day, end=""):
    """ابدأ/بدّل حالة ممتدة من ``day``.

    ``end`` مطلوب لـ«طارئة» (شامل) وممنوع للحالات المستمرة. يرجع
    ``(record, changed, closed_before)``:

    - نفس الحالة المستمرة مفتوحة بالفعل → لا شيء يتغير.
    - نفس «طارئة» فعالة → تتعدل نهايتها في نفس السجل (ده كمان طريق تحويل
      سجل قديم مفتوح لمدة محددة).
    - حالة ممتدة تانية فعالة → تتقفل في اليوم السابق (أو تتشال لو بادئة
      في نفس اليوم)، وده هو ``closed_before``.
    - سجل لاحق مجدول لنفس الضابط بيتحافظ عليه: الحالة المستمرة بتقف قبله،
      و«طارئة» اللي نهايتها بتعدّي عليه بتترفض بدل ما تبلعه.
    """
    if status not in PERIOD_STATUSES:
        raise PeriodError("الحالة ليست من الحالات الممتدة.")
    end = clean_end(status, end, day)

    future = sorted(
        (row for row in periods(data)
         if row.get("officer_id") == officer_id and row.get("start", "") > day),
        key=lambda row: row.get("start", ""),
    )
    if end and future and future[0]["start"] <= end:
        raise PeriodError(
            f"توجد حالة «{future[0].get('status', '')}» مسجلة من {future[0]['start']}؛ "
            "اختر يوم نهاية قبلها.", 409)

    current = active_on(data, officer_id, day)
    if current and current.get("status") == status:
        if not end:
            return current, False, None
        if current.get("end") == end:
            return current, False, None
        before = dict(current)
        current["end"] = end
        current.pop("stopped_on", None)
        return current, True, before

    closed_before = None
    if current:
        closed_before = dict(current)
        if current.get("start") == day:
            periods(data).remove(current)
        else:
            current["end"] = _previous_day(day)
            current["stopped_on"] = day

    row = {
        "id": reserve_id(data, "OSP", periods(data), width=4),
        "officer_id": officer_id,
        "status": status,
        "start": day,
        "end": end or (_previous_day(future[0]["start"]) if future else ""),
        "stopped_on": "" if end else (future[0]["start"] if future else ""),
    }
    periods(data).append(row)
    periods(data).sort(key=lambda item: (item.get("start", ""), item.get("id", "")))
    return row, True, closed_before


def stop(data, officer_id, day):
    """أوقف الحالة في ``day`` باعتباره أول يوم عودة.

    لو أُوقفت في نفس يوم بدايتها يُلغى السجل بالكامل. يرجع نسختي قبل/بعد؛
    ``after`` تكون ``None`` عند الإلغاء.
    """
    current = active_on(data, officer_id, day)
    if not current:
        return None, None
    before = dict(current)
    if current.get("start") == day:
        periods(data).remove(current)
        return before, None
    current["end"] = _previous_day(day)
    current["stopped_on"] = day
    return before, dict(current)


def drop_starting_on(data, day):
    """يشيل السجلات اللي بادئة في ``day`` — مسح اليوم بالكامل. يرجعها."""
    found = [row for row in periods(data) if row.get("start") == day]
    for row in found:
        periods(data).remove(row)
    return found


def drop_officer(data, officer_id):
    """كل سجلات ضابط اتمسح نهائيًا. يرجع العدد."""
    rows = periods(data)
    kept = [row for row in rows if row.get("officer_id") != officer_id]
    removed = len(rows) - len(kept)
    rows[:] = kept
    return removed
