"""سجل التغييرات التشغيلية — مين عدّل إيه وإمتى، بالقيمة قبل وبعد.

`logs/audit.log` (store.py) بيسجّل إن فيه طلب كتابة حصل ومين اللي كتبه،
بس من غير القيمة نفسها. السجل ده أدق: بيحفظ الكيان المتأثر والقيمة قبل
وبعد التغيير، عشان سؤال «إيه اللي اتغيّر بالظبط؟» يكون له إجابة من غير
ما حد يرجع لنسخة احتياطية قديمة يقارنها بإيده.

بيتخزّن جوه data.json نفسها (مش ملف لوج منفصل) عشان يدخل في النسخ
الاحتياطية المضغوطة تلقائيًا زي أي بيانات تانية، ويتقرا ويتصفّى من غير
أداة زيادة. مسقوف بعدد ثابت — أقدم سجل بيتشال لما العدد يعدّي السقف،
زي `store.BACKUP_KEEP` بالظبط، عشان الملف ما يكبرش من غير حد.
"""
from datetime import datetime
from urllib.parse import unquote

from .store import reserve_id

MAX_ENTRIES = 5000


def log(data):
    return data.setdefault("change_log", [])


def _edited_by():
    """اسم المشغّل من ترويسة X-Edited-By — نفس منطق store._log_audit()
    بالظبط، لأن الاتنين بيقروا نفس الترويسة في نفس سياق الطلب."""
    try:
        from flask import request
        return unquote(request.headers.get("X-Edited-By", "")).strip()
    except RuntimeError:
        return ""


def record(data, entity, entity_id, action, before=None, after=None, reason="",
           day=None, text="", ts=None):
    """بيسجّل تغيير واحد. `before`/`after` أي قيمة JSON-قابلة (عادة نسخة
    من الكيان نفسه) — بتتعرض جنب بعض في شاشة السجل لعرض الفرق.

    `text` جملة عربية جاهزة («فلان: كان كذا ← بقى كذا»). بتتكتب هنا مرة
    واحدة وقت التسجيل بدل ما الواجهة تحاول تركّبها من الحقول الخام — عشان
    اللي شايف السجل يقرا اللي حصل مش JSON.

    `ts` بيتحدد من برّه لما كذا تغيير يتسجّلوا كوحدة واحدة (تأكيد اليومية
    مثلًا) — كلهم لازم يحملوا **نفس** اللحظة، لحظة التأكيد.
    """
    entries = log(data)
    entries.append({
        "id": reserve_id(data, "CHG", entries),
        "ts": ts or datetime.now().isoformat(timespec="seconds"),
        "entity": entity, "entity_id": entity_id, "action": action,
        "day": day, "text": text,
        "before": before, "after": after, "reason": reason,
        "edited_by": _edited_by() or None,
    })
    if len(entries) > MAX_ENTRIES:
        del entries[:len(entries) - MAX_ENTRIES]


def recent(data, limit=200, entity=None, entity_id=None, day=None):
    """أحدث التغييرات أولًا، قابلة للتصفية بالكيان أو بسجل بعينه أو باليوم."""
    entries = log(data)
    out = entries
    if entity:
        out = [e for e in out if e["entity"] == entity]
    if entity_id:
        out = [e for e in out if e["entity_id"] == entity_id]
    if day:
        out = [e for e in out if e.get("day") == day]
    return list(reversed(out))[:limit]
