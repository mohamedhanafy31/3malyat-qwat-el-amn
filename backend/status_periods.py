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
from datetime import date, datetime, timedelta

from .store import reserve_id
from .utils import canonical_day


CONTINUOUS_STATUSES = ("مرضي", "غياب")
BOUNDED_STATUSES = ("طارئة", "مأمورية", "انتداب")
# الحالات اللي لازم معاها اسم وتفاصيل بتظهر في اليومية
DETAILED_STATUSES = ("مأمورية", "انتداب")
MAX_TITLE_LEN = 120
MAX_DETAILS_LEN = 300
MAX_CUSTOM_DETAILS_LEN = 500
# أي حالة من دول مصدرها سجل المدى مش ملف اليوم
PERIOD_STATUSES = CONTINUOUS_STATUSES + BOUNDED_STATUSES


class PeriodError(ValueError):
    """طلب حالة ممتدة غير صالح؛ ``status`` كود HTTP المناسب."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def periods(data):
    return data.setdefault("officer_status_periods", [])


def is_bounded(status, custom=False, continuous=False):
    return status in BOUNDED_STATUSES or (bool(custom) and not continuous)


def is_continuous(row):
    """هل سجل المدى مستمر حتى الإنهاء؟

    السجلات المخصصة المفتوحة القديمة تُعامل كمستمرة عند القراءة، بينما
    ``mode`` يحفظ المعنى بعد إيقاف السجل حتى تظل حالته واضحة في التاريخ.
    """
    row = row or {}
    if row.get("status") in CONTINUOUS_STATUSES:
        return True
    return bool(row.get("custom")) and (
        row.get("mode") == "continuous" or not row.get("end"))


def public(row):
    """شكل السجل للواجهة: الحقول المخزنة + نوعه وهل هو مفتوح."""
    if not row:
        return None
    out = {key: row.get(key, "") for key in ("id", "status", "start", "end", "stopped_on",
                                               "start_time", "end_time")}
    out["title"] = row.get("title", "") or ""
    out["details"] = row.get("details", "") or ""
    custom = bool(row.get("custom"))
    if custom:
        out["custom"] = True
    if custom and row.get("mode"):
        out["mode"] = row["mode"]
    out["kind"] = "continuous" if is_continuous(row) else "bounded"
    out["open_ended"] = not row.get("end")
    # «طارئة»/«انتداب» مفتوحة = سجل قديم من قبل إلزام يوم النهاية؛
    # السجل المخصص المفتوح مقصود به الاستمرار، وليس سجلًا قديمًا ناقصًا.
    out["legacy_open"] = (out["open_ended"] and out["kind"] == "bounded"
                          and not custom)
    out["label"] = describe(row)
    out["duration"] = duration(row)
    return out


def duration(row, today=None, now=None):
    """Duration display for absence and sick leave, preserving date-only history."""
    status = str((row or {}).get("status") or "")
    custom = bool((row or {}).get("custom"))
    if status not in ("غياب", "مرضي") and not custom:
        return None
    start = str(row.get("start") or "")
    end = str(row.get("end") or "")
    if not start:
        return {"text": "غير محددة", "days": 0, "hours": 0, "minutes": 0,
                "precision": "unknown"}
    today = today or date.today().isoformat()
    if status == "مرضي":
        last = end or today
        try:
            days = max(0, (date.fromisoformat(last) - date.fromisoformat(start)).days + 1)
        except ValueError:
            days = 0
        return {"text": f"{days} يوم", "days": days, "hours": 0, "minutes": 0,
                "precision": "days"}
    start_time = str(row.get("start_time") or "").strip()
    end_time = str(row.get("end_time") or "").strip()
    if not start_time:
        try:
            days = max(0, (date.fromisoformat(end or today) - date.fromisoformat(start)).days + 1)
        except ValueError:
            days = 0
        return {"text": f"{days} يوم (التوقيت غير مسجل)", "days": days,
                "hours": 0, "minutes": 0, "precision": "days"}
    try:
        beginning = datetime.combine(date.fromisoformat(start), datetime.strptime(start_time, "%H:%M").time())
        if end and end_time:
            finish_day = str(row.get("stopped_on") or end)
            finish = datetime.combine(date.fromisoformat(finish_day), datetime.strptime(end_time, "%H:%M").time())
        elif end:
            days = max(0, (date.fromisoformat(end) - date.fromisoformat(start)).days + 1)
            return {"text": f"{days} يوم (التوقيت غير مكتمل)", "days": days,
                    "hours": 0, "minutes": 0, "precision": "days"}
        else:
            finish = now or datetime.now()
        minutes = max(0, int((finish - beginning).total_seconds() // 60))
    except ValueError:
        return {"text": "التوقيت غير صحيح", "days": 0, "hours": 0,
                "minutes": 0, "precision": "invalid"}
    days, remainder = divmod(minutes, 1440)
    hours, mins = divmod(remainder, 60)
    parts = ([f"{days} يوم"] if days else []) + ([f"{hours} ساعة"] if hours else []) + ([f"{mins} دقيقة"] if mins or not (days or hours) else [])
    return {"text": "، ".join(parts), "days": days, "hours": hours,
            "minutes": mins, "precision": "minutes"}


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
    if row.get("custom") and parts:
        if row.get("start") and row.get("end"):
            parts.append(f"من {_dmy(row['start'])} حتى {_dmy(row['end'])}")
        elif row.get("start"):
            parts.append(f"من {_dmy(row['start'])}")
        return f"{status}: " + " — ".join(parts)
    if status not in DETAILED_STATUSES or not parts:
        return status
    if row.get("start") and row.get("end"):
        parts.append(f"من {_dmy(row['start'])} حتى {_dmy(row['end'])}")
    elif row.get("start"):
        parts.append(f"من {_dmy(row['start'])}")
    return f"{status}: " + " — ".join(parts)


def clean_details(status, title, details, custom=False):
    """الاسم والتفاصيل لحالة «مأمورية»/«انتداب» — بترمي ``PeriodError`` لو ناقصة.

    باقي الحالات مابتخزّنش اسم ولا تفاصيل."""
    if custom:
        details = " ".join(str(details or "").split())
        if len(details) > MAX_CUSTOM_DETAILS_LEN:
            raise PeriodError(f"نص الحالة أطول من الحد المسموح ({MAX_CUSTOM_DETAILS_LEN} حرف).")
        return "", details
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


def clean_clock(value, label):
    value = str(value or "").strip()
    if value and (len(value) != 5 or value[2] != ":" or not value[:2].isdigit()
                  or not value[3:].isdigit() or not (0 <= int(value[:2]) < 24)
                  or not (0 <= int(value[3:]) < 60)):
        raise PeriodError(f"{label} غير صحيح؛ استخدم ساعة ودقيقة بصيغة HH:MM.")
    return value


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


def clean_end(status, raw_end, day, custom=False, continuous=False):
    """تحقق من يوم النهاية حسب نوع الحالة. يرجع النهاية القانونية أو يرفع ``PeriodError``."""
    raw_end = str(raw_end or "").strip()
    if continuous:
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


def start(data, officer_id, status, day, end="", title="", details="", start_time="",
          custom=False, continuous=False):
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
    if status not in PERIOD_STATUSES and not custom:
        raise PeriodError("الحالة ليست من الحالات الممتدة.")
    continuous = (status in CONTINUOUS_STATUSES and not custom) or (custom and continuous)
    end = clean_end(status, end, day, custom=custom, continuous=continuous)
    title, details = clean_details(status, title, details, custom=custom)
    start_time = clean_clock(start_time, "وقت بداية الغياب") if status == "غياب" else ""

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
    if current and current.get("status") == status and bool(current.get("custom")) == bool(custom):
        effective_end = end or (_previous_day(future[0]["start"]) if continuous and future else "")
        if custom:
            before = dict(current)
            desired_mode = "continuous" if continuous else ""
            desired_stopped_on = future[0]["start"] if continuous and future else ""
            changed = (
                current.get("end", "") != effective_end
                or current.get("stopped_on", "") != desired_stopped_on
                or (current.get("details") or "") != details
                or current.get("mode", "") != desired_mode
            )
            if not changed:
                return current, False, None
            current["end"] = effective_end
            current["stopped_on"] = desired_stopped_on
            current["custom"] = True
            current["details"] = details
            current.pop("title", None)
            if desired_mode:
                current["mode"] = desired_mode
            else:
                current.pop("mode", None)
            return current, True, before
        if not end:
            changed = current.get("start_time", "") != start_time
            before = dict(current) if changed else None
            if start_time:
                current["start_time"] = start_time
            else:
                current.pop("start_time", None)
            return current, changed, before
        if (current.get("end") == end and (current.get("title") or "") == title
                and (current.get("details") or "") == details
                and current.get("start_time", "") == start_time):
            return current, False, None
        before = dict(current)
        current["end"] = end
        current.pop("stopped_on", None)
        if custom:
            current["custom"] = True
        if custom:
            current["details"] = details
            current.pop("title", None)
        elif title:
            current["title"], current["details"] = title, details
        if start_time:
            current["start_time"] = start_time
        else:
            current.pop("start_time", None)
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
        "end": end or (_previous_day(future[0]["start"]) if continuous and future else ""),
        "stopped_on": "" if end else (future[0]["start"] if future else ""),
    }
    if custom:
        row["custom"] = True
        row["details"] = details
        if continuous:
            row["mode"] = "continuous"
    if title:
        row["title"], row["details"] = title, details
    if start_time:
        row["start_time"] = start_time
    periods(data).append(row)
    periods(data).sort(key=lambda item: (item.get("start", ""), item.get("id", "")))
    return row, True, closed_before


def stop(data, officer_id, day, end_time=""):
    """أوقف الحالة في ``day`` باعتباره أول يوم عودة.

    لو أُوقفت في نفس يوم بدايتها يُلغى السجل بالكامل. يرجع نسختي قبل/بعد؛
    ``after`` تكون ``None`` عند الإلغاء.
    """
    current = active_on(data, officer_id, day)
    if not current:
        return None, None
    before = dict(current)
    if current.get("start") == day and not (current.get("status") == "غياب"
                                             and current.get("start_time") and end_time):
        periods(data).remove(current)
        return before, None
    current["end"] = day if current.get("start") == day else _previous_day(day)
    current["stopped_on"] = day
    if current.get("status") == "غياب" and current.get("start_time"):
        end_time = clean_clock(end_time, "وقت نهاية الغياب")
        if end_time:
            current["end_time"] = end_time
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
