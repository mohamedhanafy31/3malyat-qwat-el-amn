#!/usr/bin/env python3
"""فحص التكامل المرجعي — بيدوّر على أي مرجع بيشاور على سجل مش موجود.

الحذف كان مكتوب بالإيد في كل مسار لوحده، ومن غير الفحص ده مفيش أي طريقة
تعرف إن مسار نسي ينضّف مكان. ده بالظبط اللي حصل: حذف سجل أرشيف كان
بينضّف ٦ أماكن ويسيب `course_terms.officer_id` و`missions.member_ids`
معلّقين — والنتيجة صف دورة باسم فاضي في الصفحة، ومفيش طريقة توصله تمسحه.

الأداة دي **بتقرا بس، ما بتكتبش أي حاجة**. بتتشغّل كذا طريقة:

    python3 tools/check_integrity.py              # الملف الحيّ
    python3 tools/check_integrity.py path.json    # أي نسخة احتياطية مفكوكة

بترجّع كود خروج 1 لو فيه مرجع معلّق — عشان تنفع في سكربت قبل الهجرة.

خريطة المراجع نفسها في `backend/references.py`، وهي نفسها اللي محرّك
الحذف بيمشي عليها. الأداة بتقرا منها مش بتعيد كتابتها.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data.json"


# ---------- بناء مجموعات المفاتيح الموجودة ----------

def _people_ids(data, category):
    """معرّفات كل الأشخاص في الفئة — بيفهم شكل التخزين القديم والجديد.

    من هجرة 008 القوة قايمة واحدة و`status` بيفرّق. الشكل القديم
    (`{"active": [...], "archive": [...]}`) لسه بيتقرا هنا عشان الأداة
    دي شغلها الأساسي إنها تتشغّل على **نسخة احتياطية** قبل استعادتها،
    والنسخ القديمة بالشكل القديم.
    """
    holder = data.get(category)
    if isinstance(holder, list):
        return {p.get("id") for p in holder}
    if isinstance(holder, dict):
        return {p.get("id") for bucket in ("active", "archive")
                for p in holder.get(bucket) or []}
    return set()


def targets(data):
    """المفاتيح الموجودة فعلًا لكل نوع سجل — الأهداف المشروعة لأي مرجع."""
    return {
        "officer": _people_ids(data, "officers"),
        "individual": _people_ids(data, "personnel"),
        "person": _people_ids(data, "officers") | _people_ids(data, "personnel"),
        "course": {c.get("id") for c in data.get("courses") or []},
        "service": {s.get("id") for s in data.get("services") or []},
    }


# ---------- المراجع اللي بتتفحص ----------
#
# الخريطة نفسها اللي محرّك الحذف بيمشي عليها — `backend/references.py`.
# المصدر واحد عن قصد: مرجع جديد بيتضاف مرة، والحذف والفحص الاتنين
# بيعرفوه. لما كانوا نسختين، أي واحدة تتحدّث من غير التانية بتخلي الفحص
# يقول «سليم» على حاجة الحذف بينساها (أو العكس).

sys.path.insert(0, str(ROOT))
from backend.references import person_references as _iter_refs   # noqa: E402


def check(data):
    """قايمة بكل مرجع معلّق: (المكان, نوع الهدف, المعرّف المفقود)."""
    known = targets(data)
    return [(where, kind, ref) for where, kind, ref in _iter_refs(data)
            if ref and ref not in known[kind]]


def counts(data):
    """عدد المراجع المفحوصة لكل نوع — عشان التقرير يبيّن إن الفحص اشتغل فعلًا."""
    tally = {}
    for _, kind, ref in _iter_refs(data):
        if ref:
            tally[kind] = tally.get(kind, 0) + 1
    return tally


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DATA_FILE
    if not path.exists():
        raise SystemExit(f"مافيش ملف في {path}")
    data = json.loads(path.read_text(encoding="utf-8"))

    tally = counts(data)
    total = sum(tally.values())
    print(f"=== فحص التكامل المرجعي — {path.name} ===")
    print(f"اتفحص {total} مرجع: " + "، ".join(f"{k}={v}" for k, v in sorted(tally.items())))

    broken = check(data)
    if not broken:
        print("\n✓ مفيش أي مرجع معلّق.")
        return 0

    print(f"\n✗ {len(broken)} مرجع معلّق:\n")
    for where, kind, ref in broken:
        print(f"  {where}  →  {kind} «{ref}» مش موجود")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
