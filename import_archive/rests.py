#!/usr/bin/env python3
"""Read the officers' rest system and rest periods out of the duty sheets.

The "الراحات" column records the standing entitlement (weekly / semi-monthly /
monthly, and for weekly the fixed day). The "التشغيل اليومي" column records the
actual absence, e.g. "راحة شهرية من(16/8 عودة 23/8)".
"""
import re
from datetime import date, timedelta
from common import strip_ar

WEEKDAYS = ['السبت', 'الأحد', 'الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة']
_WD_NORM = {strip_ar(w): w for w in WEEKDAYS}
_WD_NORM.update({'الاحد': 'الأحد', 'الاربعاء': 'الأربعاء', 'الاتنين': 'الاثنين'})

SYS_WEEKLY, SYS_HALF, SYS_MONTH, SYS_NONE = 'أسبوعية', 'نصف شهرية', 'شهرية', '—'

LEAVE_TYPES = [SYS_WEEKLY, SYS_HALF, SYS_MONTH,
               'إجازة مصيف', 'إجازة طارئة', 'راحة فرقة', 'مرضي', 'مجمعة', 'راحة']

_DATE = re.compile(r'(\d{1,2})\s*/\s*(\d{1,2})')


def parse_rest_system(cell):
    """'الخميس' -> ('أسبوعية', 'الخميس');  'شهرية' -> ('شهرية', '')"""
    s = strip_ar(cell)
    if not s or set(s) <= {'ـ', '-', ' '}:
        return SYS_NONE, ''
    if s in _WD_NORM:
        return SYS_WEEKLY, _WD_NORM[s]
    if 'نصف شهري' in s:
        return SYS_HALF, ''
    if 'شهري' in s:
        return SYS_MONTH, ''
    if 'اسبوعي' in s:
        return SYS_WEEKLY, ''
    return SYS_NONE, ''


def leave_type(text):
    s = strip_ar(text)
    if 'مصيف' in s:
        return 'إجازة مصيف'
    if 'طاري' in s:                 # strip_ar يحوّل الهمزة: طارئ → طاري
        return 'إجازة طارئة'
    if 'مرضي' in s:
        return 'مرضي'
    if 'مجمعه' in s:                # وليس "مجمع" بمفردها — عشان "المجمع الطبي" ما تتلخبطش
        return 'مجمعة'
    if 'فرقه' in s or 'فرقة' in s:
        return 'راحة فرقة'
    if 'نصف شهري' in s:
        return SYS_HALF
    if 'شهري' in s:
        return SYS_MONTH
    if 'اسبوعي' in s:
        return SYS_WEEKLY
    return 'راحة'


def _mk(day, month, ref_year=2026):
    try:
        return date(ref_year, month, day)
    except ValueError:
        return None


def parse_leave(text, on_day):
    """Parse a duty cell into a leave dict, or None if it is not a rest entry.

    `on_day` is the date of the sheet, used for open-ended weekly rests.
    """
    s = re.sub(r'\s+', ' ', (text or '').strip())
    n = strip_ar(s)
    # "فرقة"/"فرقة قادة أهداف حيوية" وحدها (بدون "راحة") بتتكرر أيام متتالية
    # وهي غياب حقيقي عن الهدف، على عكس "فرقة القيادات الأولى" اللي هي خدمة
    # تدريب فعلية مش غياب — عشان كده الشرط ضيق على العبارة دي بالتحديد.
    is_bare_firqa = n == 'فرقه' or 'قاده اهداف حيويه' in n
    if not (is_bare_firqa or 'راح' in n or 'جاز' in n):
        return None
    kind = 'راحة فرقة' if is_bare_firqa else leave_type(s)

    # "(2/3)" is a day counter (day 2 of 3), not a date. Only read dates when
    # the cell actually frames them as a period.
    has_range = bool(re.search(r'من|عوده|حتي|الي', n))
    dates = _DATE.findall(s) if has_range else []
    if not dates:
        # a plain "راحة اسبوعية" applies to the sheet's own day
        return {'type': kind, 'start': on_day, 'end': on_day,
                'return_date': on_day + timedelta(days=1), 'note': '', 'source': s}

    parsed = [_mk(int(d), int(m)) for d, m in dates[:2]]
    parsed = [p for p in parsed if p]
    if not parsed:
        return None
    start = parsed[0]
    if len(parsed) == 1:
        return {'type': kind, 'start': start, 'end': start,
                'return_date': start + timedelta(days=1), 'note': '', 'source': s}
    second = parsed[1]
    if second < start:                     # crosses into the next year
        second = second.replace(year=second.year + 1)
    # "عودة" gives the return date (exclusive); "حتى" gives the last rest day
    if 'عوده' in n or 'عودة' in s:
        end, ret = second - timedelta(days=1), second
    else:
        end, ret = second, second + timedelta(days=1)
    if end < start:
        end = start
    return {'type': kind, 'start': start, 'end': end,
            'return_date': ret, 'note': '', 'source': s}
