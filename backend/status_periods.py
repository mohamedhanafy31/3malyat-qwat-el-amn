"""حالات الضابط الممتدة — سجل مدى زمني واحد في ``core.json`` بدل نسخ يومية.

نوعان:

  **مستمرة** («مرضي» و«غياب»): تبدأ مرة من يومية الضباط وتظل فعالة كل يوم
  بعدها حتى يضغط المستخدم «إنهاء الحالة من هذا اليوم»؛ يوم الإنهاء هو أول
  يوم عادي. سجلها ``end`` فاضي طول ما هي مفتوحة.

  **محددة المدة** («طارئة» و«مأمورية» و«انتداب»): لازم معها يوم نهاية شامل
  (``حتى يوم``)، وتنتهي لوحدها بعده من غير إيقاف. «مأمورية» و«انتداب»
  بيتخزّن معاهم مرة واحدة على السجل ``title`` (الاسم/العنوان) و``details``
  (التفاصيل) وبيظهروا في كل يوم بيغطيه السجل.

سجلات «طارئة» و«انتداب» القديمة اللي اتعملت مفتوحة بتفضل مقروءة وقابلة
للإنهاء والإلغاء زي ما هي، ولو اتحفظت تاني بنهاية (ومعاها الاسم والتفاصيل
في الانتداب) بتتحول لمدة محددة في نفس السجل — لكن مفيش سجل مفتوح جديد
من الأنواع المحددة بيتعمل.

**الإنهاء** (``stop``) بيقصّر السجل ويحفظ التاريخ اللي فات؛ **الإلغاء**
(``cancel``) بيمسح السجل كله (الماضي والمستقبل) لأنه كان تسجيل بالغلط.
"""
from datetime import date, timedelta

from .store import reserve_id
from .utils import canonical_day


CONTINUOUS_STATUSES = ("مرضي", "غياب")
BOUNDED_STATUSES = ("طارئة", "مأمورية", "انتداب")
# الحالات اللي لازم معاها اسم وتفاصيل بتظهر في اليومية
DETAILED_STATUSES = ("مأمورية", "انتداب")
MAX_TITLE_LEN = 120
MAX_DETAILS_LEN = 300
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
    out["title"] = row.get("title", "") or ""
    out["details"] = row.get("details", "") or ""
    out["kind"] = "bounded" if is_bounded(row.get("status")) else "continuous"
    out["open_ended"] = not row.get("end")
    # «طارئة»/«انتداب» مفتوحة = سجل قديم من قبل إلزام يوم النهاية
    out["legacy_open"] = out["open_ended"] and out["kind"] == "bounded"
    out["label"] = describe(row)
    return out


def _dmy(iso):
    try:
        year, month, day = (int(part) for part in str(iso).split("-"))
    except ValueError:
        return str(iso or "")
    return f"{day}/{month}/{year}"


def describe(row):
    """النص المعروض للحالة في اليومية: «مأمورية: <الاسم> — <التفاصيل> — من … حتى …».

    الحالة من غير اسم/تفاصيل (طارئة، أو انتداب قديم) بتتعرض باسمها بس."""
    if not row:
        return ""
    status = row.get("status", "") or ""
    parts = [part for part in (str(row.get("title") or "").strip(),
                               str(row.get("details") or "").strip()) if part]
    if status not in DETAILED_STATUSES or not parts:
        return status
    if row.get("start") and row.get("end"):
        parts.append(f"من {_dmy(row['start'])} حتى {_dmy(row['end'])}")
    elif row.get("start"):
        parts.append(f"من {_dmy(row['start'])}")
    return f"{status}: " + " — ".join(parts)


def clean_details(status, title, details):
    """الاسم والتفاصيل لحالة «مأمورية»/«انتداب» — بترمي ``PeriodError`` لو ناقصة.

    باقي الحالات مابتخزّنش اسم ولا تفاصيل."""
    if status not in DETAILED_STATUSES:
        return "", ""
    title = " ".join(str(title or "").split())
    details = " ".join(str(details or "").split())
    if not title:
        raise PeriodError(f"اسم {status} مطلوب.")
    if not details:
        raise PeriodError(f"تفاصيل {status} مطلوبة.")
    if len(title) > MAX_TITLE_LEN:
        raise PeriodError(f"اسم {status} أطول من الحد المسموح ({MAX_TITLE_LEN} حرف).")
    if len(details) > MAX_DETAILS_LEN:
        raise PeriodError(f"تفاصيل {status} أطول من الحد المسموح ({MAX_DETAILS_LEN} حرف).")
    return title, details


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
            raise PeriodError(f"حالة «{status}» مستمرة حتى الإنهاء ولا تقبل يوم نهاية.")
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


def start(data, officer_id, status, day, end="", title="", details=""):
    """ابدأ/بدّل حالة ممتدة من ``day``.

    ``end`` مطلوب للحالات محددة المدة (شامل) وممنوع للمستمرة؛ و«مأمورية»
    و«انتداب» محتاجين كمان ``title`` و``details``. يرجع
    ``(record, changed, closed_before)``:

    - نفس الحالة المستمرة مفتوحة بالفعل → لا شيء يتغير.
    - نفس الحالة محددة المدة فعالة → تتعدل نهايتها/اسمها/تفاصيلها في نفس
      السجل (ده كمان طريق تحويل سجل قديم مفتوح لمدة محددة).
    - حالة ممتدة تانية فعالة → تتقفل في اليوم السابق (أو تتشال لو بادئة
      في نفس اليوم)، وده هو ``closed_before``.
    - سجل لاحق مجدول لنفس الضابط بيتحافظ عليه: الحالة المستمرة بتقف قبله،
      و«طارئة» اللي نهايتها بتعدّي عليه بتترفض بدل ما تبلعه.
    """
    if status not in PERIOD_STATUSES:
        raise PeriodError("الحالة ليست من الحالات الممتدة.")
    end = clean_end(status, end, day)
    title, details = clean_details(status, title, details)

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
        if (current.get("end") == end and (current.get("title") or "") == title
                and (current.get("details") or "") == details):
            return current, False, None
        before = dict(current)
        current["end"] = end
        current.pop("stopped_on", None)
        if title:
            current["title"], current["details"] = title, details
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
    if title:
        row["title"], row["details"] = title, details
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


def cancel(data, officer_id, day):
    """إلغاء تسجيل الحالة بالكامل: بيمسح السجل اللي بيغطي ``day`` (الماضي
    والمستقبل) — عكس ``stop`` اللي بيحفظ اللي فات. يرجع نسخة السجل المحذوف
    أو ``None`` لو مفيش حالة بتغطي اليوم."""
    current = active_on(data, officer_id, day)
    if not current:
        return None
    before = dict(current)
    periods(data).remove(current)
    return before


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
