#!/usr/bin/env python3
"""قراءة جدول الإجمالي المكتوب في يومية الضباط — مرجع المعايرة.

الجدول ده ظهر في يوميات 17/8 وطالع (22 يوم)، وبنيته:

    أصل القوة | خارجية (صباحية|ليلية) | داخلية (صباحية|ليلية)
    | طبية (موجود|راحة) | خوارج (تقصيرة|راحة|طارئة|غياب|مرضي|فرقة|انتداب)
    | الحراسات المشددة | الصافي (N)

⚠ الجدول نفسه مكتوب بالإيد وفيه أيام واضح إنها منسوخة من يوم قبله من غير
تحديث: يومية 31/8 مكتوب فيها «غياب 0» رغم إن فيه ضابط تشغيله «غياب»،
و«فرقة 1» من غير ما يكون فيه حد على فرقة. عشان كده `is_stale()` بتعلّم
اليوم اللي بيناقض النص المكتوب في نفس الصفحة، والمعايرة بتستثنيه وتذكره.
"""
import re
from pathlib import Path

from common import ROOT, day_dirs, iso, strip_ar

try:
    from docx_read import read_docx
except ImportError:      # pragma: no cover
    read_docx = None

CELL_ORDER = [
    "أصل القوة",
    "خارجية/صباحية", "خارجية/ليلية",
    "داخلية/صباحية", "داخلية/ليلية",
    "طبية/موجود", "طبية/راحة",
    "خوارج/تقصيرة", "خوارج/راحة", "خوارج/طارئة", "خوارج/غياب",
    "خوارج/مرضي", "خوارج/فرقة", "خوارج/انتداب",
    "حراسات",
]

_NUM = re.compile(r'^\s*(\d+)')
_NET = re.compile(r'\((\d+)\)')


def _num(text):
    m = _NUM.match(text or "")
    return int(m.group(1)) if m else None


def _tables(path):
    return [b[1] for b in read_docx(str(path)) if b[0] == "table"]


def parse_summary(path):
    """-> dict الخانة -> رقم، أو None لو اليوم مالوش جدول إجمالي."""
    for table in _tables(path):
        if not table or "الخدمات الخارجية" not in " ".join(table[0]):
            continue
        header, values = table[0], table[2] if len(table) > 2 else []
        if not values:
            return None
        out = {}
        for name, cell in zip(CELL_ORDER, values):
            value = _num(cell)
            if value is not None:
                out[name] = value
        # «9 + 1 بحث» — الوسم بيتكتب جوّه خانة الخارجية الصباحية
        out["خارجية/بحث"] = 1 if "بحث" in (values[1] if len(values) > 1 else "") else 0
        net = _NET.search(header[-1] if header else "")
        if net:
            out["صافي"] = int(net.group(1))
        return out
    return None


def word_summaries():
    """-> {اليوم: {الخانة: رقم}} لكل يوم في الأرشيف فيه جدول إجمالي."""
    if read_docx is None:
        return {}
    out = {}
    for m, d, folder in day_dirs():
        path = folder / f"{d}-{m}-2026.docx"
        if not path.exists():
            continue
        try:
            summary = parse_summary(path)
        except Exception:
            continue
        if summary:
            out[iso(m, d)] = summary
    return out


def is_stale(word, computed_rows):
    """اليوم بيتعلّم «متقادم» لو الجدول بيناقض نص التشغيل في نفس الصفحة.

    مثال موثّق (31/8): الجدول بيقول «غياب 0» و«فرقة 1»، والصفحة نفسها فيها
    ضابط تشغيله «غياب» ومحدش على فرقة — يعني الجدول اتنسخ من يوم قبله.
    """
    reasons = []
    # مجموع الخانات لازم يساوي أصل القوة — ده ثابت في كل يوم سليم. لو مش
    # مساوي يبقى الصف متزحلق أو ناقص (بيحصل في جداول أغسطس الأولى).
    force = word.get("أصل القوة")
    total = sum(v for k, v in word.items() if k not in ("أصل القوة", "صافي"))
    total += word.get("صافي", 0)
    if force and total != force:
        reasons.append(f"مجموع الخانات {total} مش مساوي أصل القوة {force}")

    for bucket in ("غياب", "مرضي", "فرقة", "طارئة"):
        seen = sum(1 for r in computed_rows
                   if r["group"] == "خوارج" and r["bucket"] == bucket)
        stated = word.get(f"خوارج/{bucket}")
        if stated is None:
            continue
        if bool(seen) != bool(stated):
            reasons.append(f"{bucket}: الجدول {stated} والنص {seen}")
    return reasons
