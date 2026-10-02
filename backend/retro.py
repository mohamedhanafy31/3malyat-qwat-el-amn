"""تعديل بأثر رجعي على أيام مقفولة.

راحة أو التحاق فرقة أو تعديل بيانات شخص بتاريخ يقع على يوم **مقفول**
بالفعل (`day_status.is_closed`) بيغيّر شكل اليوم ده — أصل القوة، حالة
الضابط، دفتر ٤٣ — من غير ما اليومية التفصيلية نفسها تتلمس (دي محمية
بـ`day_status.check_open` في مسارها هي بس).

القرار هنا: **مسموح**، بس محتاج سبب مكتوب ويتسجّل في سجل التغييرات —
عشان أي تعديل بأثر رجعي يفضل موثّق مش مبهم، بدل ما يترفض بالكامل (لو
رفضناه، راحة أسبوع كامل بتحتاج تفتح استثنائي ٧ أيام لوحدهم).
"""
from urllib.parse import unquote

from flask import jsonify

from . import changes, day_status
from .store import AbortRequest
from .utils import days_between, parse_date


def closed_days_in(data, start, end):
    """كل الأيام المقفولة بين `start` و`end` (شامل)، بصورتهم النصية.
    بترجّع قايمة فاضية لو أي تاريخ منهم غير صالح أو المدى معكوس."""
    if not start or not end:
        return []
    s, e = parse_date(start), parse_date(end)
    if not s or not e or e < s:
        return []
    return [d for d in days_between(s, e) if day_status.is_closed(data, d)]


def status_scope(view):
    """نطاق قراءة لمسار ممكن يسأل `closed_days_in`: الأيام اللي ليها
    سجل قفل/فتح صريح (`day_status`) بس — مش الأرشيف. اليوم من غيرها
    حالته محسوبة من التاريخ لوحده (`day_status.status_of`)، فمش محتاج
    يتحمّل، وعدد الأيام دي صغير (قفل بدري أو فتح استثنائي بإيد المشغّل)."""
    return view.index.days_with("day_status")


def _reason_header():
    """نفس منطق `changes._edited_by()` بالظبط — ترويسة HTTP بتتشفّر لأنها
    غالبًا عربي."""
    try:
        from flask import request
        return unquote(request.headers.get("X-Retro-Reason", "")).strip()
    except RuntimeError:
        return ""


def require_reason(days):
    """لو `days` فيها أيام مقفولة ومفيش سبب في X-Retro-Reason، بيرمي 409
    بالأيام دي عشان الواجهة تسأل المستخدم وتعيد النداء بالسبب. بترجّع
    السبب (فاضي لو مفيش أيام مقفولة أصلًا — التعديل عادي وقتها)."""
    if not days:
        return ""
    reason = _reason_header()
    if not reason:
        raise AbortRequest((jsonify({
            "error": "يؤثر هذا التعديل في يوم مغلق أو عدة أيام مغلقة — يلزم سبب مكتوب للمتابعة.",
            "needs_reason": True, "closed_days": days,
        }), 409))
    return reason


def log_retro(data, entity, entity_id, days, reason, before=None, after=None, text=""):
    """سطر واحد في سجل التغييرات بالأيام المتأثرة والسبب."""
    changes.record(data, entity, entity_id, "retro", before=before, after=after,
                   reason=reason,
                   text=text or f"تعديل بأثر رجعي على يوم مغلق أو عدة أيام مغلقة: {'، '.join(days)}"
                        + (f" — السبب: {reason}" if reason else ""))
