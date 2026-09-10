"""مدى تاريخ مشترك — التحقق من صحته وتقاطعه مع مدى تاني.

الراحات والفرق الاتنين بيسجّلوا "شخص + من تاريخ لتاريخ"، وكانوا بيكرروا
نفس منطق التحليل والتقاطع بالحرف. الفرق الوحيد بينهم: الراحة تاريخها
إجباري ورسالة خطأ واحدة مجمّعة لو ناقص، والفرقة تاريخها اختياري ورسالة
منفصلة لكل حقل غلط — فده معمول بـ`required` بدل ما يتكرر الكود.
"""
from .utils import parse_date


def overlapping_of(records, start, end, owner_key, owner_id, ignore_id=None):
    """أول سجل في `records` بيتقاطع مداه مع `start`-`end` لنفس صاحب `owner_id`."""
    if not start or not end:
        return None
    for r in records:
        if r.get("id") == ignore_id or r.get(owner_key) != owner_id:
            continue
        s2, e2 = r.get("start", ""), r.get("end", "")
        if s2 and e2 and s2 <= end and start <= e2:
            return r
    return None


def parse_range(payload, max_span_days, span_error, required=False):
    """يحلل ويتحقق من start/end في payload. بيرجع (start, end, error).

    required=True (الراحات): لازم الاتنين موجودين وصحيحين، ورسالة واحدة
    مجمّعة لو حصل نقص. required=False (الفرق): كل تاريخ اختياري، ورسالة
    منفصلة لكل حقل غلط لو موجود فعلًا.
    """
    raw_start = str(payload.get("start", "") or "").strip()
    raw_end = str(payload.get("end", "") or "").strip()
    start = parse_date(raw_start) if raw_start else None
    end = parse_date(raw_end) if raw_end else None

    if required:
        if not start or not end:
            return None, None, "برجاء إدخال تاريخ بداية ونهاية صحيحين."
    else:
        if raw_start and not start:
            return None, None, "تاريخ البداية غير صحيح."
        if raw_end and not end:
            return None, None, "تاريخ النهاية غير صحيح."

    if start and end and end < start:
        return None, None, "تاريخ النهاية لا يمكن أن يسبق تاريخ البداية."
    if start and end and (end - start).days > max_span_days:
        return None, None, span_error
    return start, end, None
