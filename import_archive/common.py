#!/usr/bin/env python3
"""Shared parsing helpers for the 2026 camp archive."""
import re
from pathlib import Path
from docx_read import read_docx

ROOT = Path('/media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f4410/personal/سيستم المعسكر/2026')

AR_DIAC = re.compile(r'[ؐ-ًؚ-ٰٟۖ-ۭـ]')
PHONE = re.compile(r'\d[\d\s\-]{8,}\d')


def strip_ar(s):
    s = AR_DIAC.sub('', s or '')
    for a, b in (('أ', 'ا'), ('إ', 'ا'), ('آ', 'ا'), ('ٱ', 'ا'),
                 ('ى', 'ي'), ('ة', 'ه'), ('ؤ', 'و'), ('ئ', 'ي')):
        s = s.replace(a, b)
    s = re.sub(r'[^؀-ۿ\w]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def norm_name(s):
    """Normalised name; also glues the common عبد / ابو prefixes to the next token."""
    s = strip_ar(s)
    s = re.sub(r'\b(عبد|ابو|ابن)\s+', r'\1', s)
    return s.strip()


def name_tokens(s):
    return [t for t in norm_name(s).split() if t]


def norm_phone(p):
    d = re.sub(r'\D', '', p or '')
    if len(d) == 12 and d.startswith('01'):
        # a stray inserted digit is the common typo; keep the 11-digit prefix
        d = d[:11]
    if len(d) == 10 and d.startswith('1'):
        d = '0' + d
    return d


def day_dirs():
    for m in sorted((p for p in ROOT.iterdir() if p.is_dir() and p.name.isdigit()),
                    key=lambda p: int(p.name)):
        for d in sorted((p for p in m.iterdir() if p.is_dir() and p.name.isdigit()),
                        key=lambda p: int(p.name)):
            yield int(m.name), int(d.name), d


def iso(m, d):
    return f'2026-{m:02d}-{d:02d}'


def biggest_table(path):
    tables = [b[1] for b in read_docx(path) if b[0] == 'table']
    return max(tables, key=len) if tables else None


# ---------- officers ----------

SECTION_MAIN = 'القوة'
SECTION_GUARD = 'الحراسات المشددة'
SECTION_OUT = 'الخوارج'


def _col(header, *wanted):
    """Index of the first header cell matching one of the given labels."""
    for w in wanted:
        for i, h in enumerate(header):
            if h == w:
                return i
    return None


def parse_officer_day(path):
    """-> list of dicts {rank, name, post, duty, rest, section}"""
    t = biggest_table(path)
    if not t:
        return []
    header = [strip_ar(c) for c in t[0]]
    # column order varies between sheet revisions, so resolve it by label
    post_i = _col(header, 'العمل المسند اليه')
    post_i = 3 if post_i is None else post_i
    duty_i = _col(header, 'التشغيل اليومي', 'التشغيل')
    rest_i = _col(header, 'الراحات')
    out, section = [], SECTION_MAIN
    for row in t[1:]:
        cells = [c.strip() for c in row]
        if len([c for c in cells if c]) <= 1:
            lab = strip_ar(' '.join(cells))
            if 'الحراسات' in lab:
                section = SECTION_GUARD
            elif 'الخوارج' in lab:
                section = SECTION_OUT
            continue
        if len(cells) < 4:
            continue
        name = cells[2]
        if not norm_name(name) or 'الاسم' in strip_ar(name):
            continue

        def get(i):
            return cells[i].strip() if i is not None and len(cells) > i else ''

        out.append({
            'rank': cells[1].strip(),
            'name': name,
            'post': get(post_i),
            'duty': get(duty_i),
            'rest': get(rest_i),
            'section': section,
        })
    return out


def clean_seniority(s):
    """Normalise 'رقم الأقدمية' to number/year."""
    s = re.sub(r'\s*/\s*', '/', (s or '').strip()).strip(' ـ-')
    # Word stores a right-to-left "1211/2016" as the runs ["2016", "1211/"],
    # which concatenate to "20161211/". Put the parts back in order.
    m = re.fullmatch(r'(\d{4})(\d{1,4})/', s)
    if m:
        s = f'{m.group(2)}/{m.group(1)}'
    return s


def parse_officer_ref(path):
    """ارقام الضباط -> list of {rank, name, post, phone, seniority, section}"""
    t = biggest_table(path)
    if not t:
        return []
    out, section = [], SECTION_MAIN
    for row in t[1:]:
        cells = [c.strip() for c in row]
        if len([c for c in cells if c]) <= 1:
            lab = strip_ar(' '.join(cells))
            if 'الحراسات' in lab:
                section = SECTION_GUARD
            elif 'الخوارج' in lab:
                section = SECTION_OUT
            continue
        if len(cells) < 6 or not norm_name(cells[2]):
            continue
        out.append({
            'rank': cells[1], 'name': cells[2], 'post': cells[3],
            'phone': norm_phone(cells[4]), 'seniority': clean_seniority(cells[5]),
            'section': section,
        })
    return out


# ---------- personnel ----------

def parse_personnel_entry(cell):
    """'م.ش / محمد عطية "0105..."' -> (rank, name, phone) | None"""
    s = re.sub(r'[\"“”،]', ' ', cell or '')
    s = re.sub(r'\s+', ' ', s).strip()
    if not s:
        return None
    mph = PHONE.search(s)
    if not mph:
        return None
    phone = norm_phone(mph.group())
    rest = (s[:mph.start()] + ' ' + s[mph.end():])
    rest = re.sub(r'\s+', ' ', rest).strip(' .-/')
    rank, name = '', rest
    if '/' in rest:
        rank, name = rest.split('/', 1)
    rank = rank.strip(' .ِ')
    name = name.strip(' .ِ')
    if len(phone) < 10 or not name:
        return None
    return rank, name, phone


def parse_personnel_day(path):
    t = biggest_table(path)
    if not t:
        return []
    out = []
    for row in t:
        for c in row:
            e = parse_personnel_entry(c)
            if e:
                out.append(e)
    return out


def parse_personnel_ref(path):
    """ارقام الافراد -> list of {grade, name, work, address, phone}"""
    t = biggest_table(path)
    if not t:
        return []
    out = []
    for row in t[1:]:
        cells = [c.strip() for c in row]
        if len(cells) < 6 or not norm_name(cells[2]):
            continue
        if 'الاسم' in strip_ar(cells[2]):
            continue
        out.append({
            'grade': cells[1], 'name': cells[2], 'work': cells[3],
            'address': cells[4], 'phone': norm_phone(cells[5]),
        })
    return out
