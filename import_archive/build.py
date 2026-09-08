#!/usr/bin/env python3
"""Build the officer/personnel/leave/duty tables from the 2026 camp archive.

Officers  : the daily "D-M-2026.docx" duty sheets give presence per day;
            "ارقام الضباط.docx" supplies phone + seniority.
Personnel : the daily "داتا افراد.docx" sheets give presence per day;
            "ارقام الافراد.docx" supplies the full name, grade and address.

IMPORTANT — this script REBUILDS its output from the Word files only. It
does not know about anything the running app owns: the board
(`day_services`), `command`, `medical_officers`, `board_categories`,
`service_tags`. Writing it straight over a live data.json would wipe all
of that. Use merge_import.py instead, which runs this to a temp file and
merges only the archive-derived tables back in.

Set BUILD_OUT to choose where to write (defaults to the live data.json,
kept only so the original one-time import stays reproducible).

NOTE — "2026" is hardcoded into filename patterns (e.g. f'{d}-{m}-2026.docx')
and date construction throughout this file. Re-running for a future year's
archive, or after moving/remounting this drive, requires updating the
"2026"/REST_MONTH literals here, common.py's ROOT, and rests.py's ref_year.
"""
import json, os, re, sys, collections, datetime
from pathlib import Path
from common import (ROOT, day_dirs, iso, norm_name, norm_phone, strip_ar,
                    parse_officer_day, parse_officer_ref,
                    parse_personnel_day, parse_personnel_ref)
from resolve import name_compatible, tokens
from rests import parse_rest_system, parse_leave, SYS_NONE

REST_MONTH = 8          # the sheets that carry the current rest entitlement

OUT = Path(os.environ.get("BUILD_OUT") or
           '/media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f4410/personal/'
           'سيستم المعسكر/prototype/personnel_system/data.json')

RANK_MAP = {
    'م.اول': 'ملازم أول', 'م.أول': 'ملازم أول', 'م اول': 'ملازم أول',
    'ملازم اول': 'ملازم أول',
}

GRADE_FAMILY = [
    (r'^م\s*ش\b', 'معاون شرطة'),            # م.ش  = معاون شرطة
    (r'^ا\s*ش\b|^اش\b', 'أمين شرطة'),        # ا.ش / أ.ش = أمين شرطة
    (r'^امين|^أمين', 'أمين شرطة'),
    (r'^معاون', 'معاون شرطة'), (r'^مساعد', 'مساعد شرطة'),
    (r'^رقيب', 'رقيب شرطة'), (r'^مراقب', 'مراقب شرطة'),
    (r'^مندوب', 'مندوب شرطة'), (r'^عريف', 'عريف شرطة'), (r'^شرطي', 'شرطي'),
]
GRADE_SUFFIX = [('ممتاز اول', 'ممتاز أول'), ('ممتاز ثاني', 'ممتاز ثان'),
                ('ممتاز ثان', 'ممتاز ثان'), ('ممتاز ثالث', 'ممتاز ثالث'),
                ('ممتاز', 'ممتاز'), ('اول', 'أول'), ('ثاني', 'ثان'),
                ('ثان', 'ثان'), ('ثالث', 'ثالث')]


def clean_rank(r):
    r = re.sub(r'\s+', ' ', (r or '').strip())
    return RANK_MAP.get(r, r)


def clean_grade(g):
    n = strip_ar(g)
    fam = next((f for pat, f in GRADE_FAMILY if re.search(pat, n)), '')
    if not fam:
        return g.strip() or 'فرد'
    suf = next((out for key, out in GRADE_SUFFIX if key in n), '')
    return f'{fam} {suf}'.strip()


# --------------------------------------------------------------------------
# 1. presence timelines
# --------------------------------------------------------------------------
DAYS = []
off_days, per_days = {}, {}
for m, d, dd in day_dirs():
    day = iso(m, d)
    fo = dd / f'{d}-{m}-2026.docx'
    fp = dd / 'داتا افراد.docx'
    # يومية الضباط هي علامة إن اليوم اتكتب فعلًا. فولدر بيتجهّز لسه بيبقى
    # فيه نسخ من اليوم اللي قبله (نفس الملفات بالحرف) من غير يومية باسمه —
    # لو حسبناه يوم، هيبقى يوم بصفر ضباط وهيزحلق آخر يوم في الأرشيف.
    if not fo.exists():
        continue
    DAYS.append(day)
    off_days[day] = parse_officer_day(fo) if fo.exists() else []
    per_days[day] = parse_personnel_day(fp) if fp.exists() else []

DAYS.sort()
LAST_DAY = DAYS[-1]
print(f'days scanned: {len(DAYS)}  ({DAYS[0]} .. {LAST_DAY})', file=sys.stderr)


def latest(fname, parser):
    """Newest available copy of a reference roster."""
    best = None
    for m, d, dd in day_dirs():
        f = dd / fname
        if f.exists():
            best = (iso(m, d), f)
    return (best[0], parser(best[1])) if best else (None, [])


ref_off_date, OFF_REF = latest('ارقام الضباط.docx', parse_officer_ref)
ref_per_date, PER_REF = latest('ارقام الافراد.docx', parse_personnel_ref)
print(f'officer ref  {ref_off_date}: {len(OFF_REF)} rows', file=sys.stderr)
print(f'personnel ref {ref_per_date}: {len(PER_REF)} rows', file=sys.stderr)


# --------------------------------------------------------------------------
# 2. officers
# --------------------------------------------------------------------------
class Person:
    __slots__ = ('names', 'days', 'obs', 'ref')

    def __init__(self):
        self.names, self.days, self.obs, self.ref = collections.Counter(), set(), [], None


officers = []          # list[Person]
by_norm = {}           # normalised name -> Person

for r in OFF_REF:      # seed with the authoritative roster
    p = Person()
    p.ref = r
    p.names[r['name']] += 1
    officers.append(p)
    by_norm[norm_name(r['name'])] = p


def find_officer(name):
    n = norm_name(name)
    if n in by_norm:
        return by_norm[n]
    hits = [p for p in officers
            if any(name_compatible(name, x) for x in p.names)]
    if hits:
        hits.sort(key=lambda p: -max(len(tokens(x)) for x in p.names))
        by_norm[n] = hits[0]
        return hits[0]
    return None


for day in DAYS:
    for row in off_days[day]:
        p = find_officer(row['name'])
        if p is None:
            p = Person()
            officers.append(p)
            by_norm[norm_name(row['name'])] = p
        p.names[row['name']] += 1
        p.days.add(day)
        p.obs.append((day, row))

officer_records = []
gen = 0
for p in officers:
    if not p.days:                      # in the reference but never on a duty sheet
        if p.ref:
            p.days.add(ref_off_date)
    if not p.days:
        continue
    days_sorted = sorted(p.days)
    join, last = days_sorted[0], days_sorted[-1]
    last_row = p.obs[-1][1] if p.obs else {}
    # the most recent non-blank rank: the sheets record promotions in place
    last_rank = next((r['rank'] for _, r in reversed(p.obs) if r['rank'].strip()), '')
    ref = p.ref or {}
    # prefer the fullest spelling; the reference wins when present
    name = ref.get('name') or max(p.names, key=lambda x: (len(tokens(x)), p.names[x]))
    rank = clean_rank(ref.get('rank') or last_rank)
    code = (ref.get('seniority') or '').strip()
    if not code:
        gen += 1
        code = f'ض-{gen:02d}'
    # rest entitlement: the most recent sheet that states one, preferring شهر 8
    rest_sys, rest_day = SYS_NONE, ''
    for day, row in reversed(p.obs):
        if REST_MONTH and not day.startswith(f'2026-{REST_MONTH:02d}'):
            continue
        s, wd = parse_rest_system(row.get('rest', ''))
        if s != SYS_NONE:
            rest_sys, rest_day = s, wd
            break
    if rest_sys == SYS_NONE:                      # left before شهر 8
        for day, row in reversed(p.obs):
            s, wd = parse_rest_system(row.get('rest', ''))
            if s != SYS_NONE:
                rest_sys, rest_day = s, wd
                break

    rec = {
        'name': name.strip(),
        'role': rank or 'ضابط',
        'code': code,
        'phone': ref.get('phone', ''),
        'join_date': join,
        'post': (ref.get('post') or last_row.get('post', '')).strip(),
        'section': last_row.get('section') or ref.get('section', 'القوة'),
        'rest_system': rest_sys,
        'rest_day': rest_day,
    }
    # still on the force if the closing roster lists them, or they were on the
    # last duty sheet; otherwise they left after their final appearance.
    if p.ref is not None or last == LAST_DAY:
        rec['status'] = 'active'
    else:
        rec['status'] = 'archived'
        rec['leave_date'] = last
        rec['leave_reason'] = ''
    officer_records.append((rec, join, code))


# --------------------------------------------------------------------------
# 3. personnel
# --------------------------------------------------------------------------
NON_PERSON = {'0623440048'}            # إدارة البحث switchboard, not a person

pdays = collections.defaultdict(set)   # phone -> set[day]
pnames = collections.defaultdict(collections.Counter)
pranks = collections.defaultdict(collections.Counter)
for day in DAYS:
    for rank, nm, ph in sorted({(r, n, x) for r, n, x in per_days[day]}):
        if ph in NON_PERSON:
            continue
        pdays[ph].add(day)
        pnames[ph][nm] += 1
        pranks[ph][rank] += 1

# Every dated copy of ارقام الافراد, so a person's roster history counts as
# presence even on days the daily quick-list omits them.
REF_VERSIONS = []
for m, d, dd in day_dirs():
    f = dd / 'ارقام الافراد.docx'
    if f.exists():
        REF_VERSIONS.append((iso(m, d), {r['phone'] for r in parse_personnel_ref(f)}))

ref_by_phone = {r['phone']: r for r in PER_REF}
claimed = {}                            # id(ref row) -> aggregate
groups = []                             # list of dicts


def new_group(ref=None):
    g = {'ref': ref, 'days': set(), 'names': collections.Counter(),
         'ranks': collections.Counter(), 'phones': []}
    groups.append(g)
    return g


for r in PER_REF:                       # seed with the authoritative roster
    claimed[id(r)] = new_group(r)

unresolved = []
for ph, days_ in sorted(pdays.items()):
    ref = ref_by_phone.get(ph)
    if ref is None:
        cands = [r for r in PER_REF
                 if any(name_compatible(n, r['name']) for n in pnames[ph])]
        if cands:
            cands.sort(key=lambda r: -len(tokens(r['name'])))
            ref = cands[0]
    if ref is None:
        unresolved.append(ph)
        g = new_group(None)
    else:
        g = claimed[id(ref)]
    g['days'] |= days_
    g['names'].update(pnames[ph])
    g['ranks'].update(pranks[ph])
    g['phones'].append(ph)

personnel_records = []
seq = 0
for g in groups:
    ref = g['ref']
    if ref is not None:                 # roster membership counts as presence
        for vdate, phones in REF_VERSIONS:
            if ref['phone'] in phones:
                g['days'].add(vdate)
    if not g['days']:
        continue
    days_sorted = sorted(g['days'])
    join, last = days_sorted[0], days_sorted[-1]
    if ref:
        name, grade = ref['name'], ref['grade']
        phone = ref['phone']
    else:
        name = max(g['names'], key=lambda x: (len(tokens(x)), g['names'][x]))
        grade = g['ranks'].most_common(1)[0][0] if g['ranks'] else ''
        phone = g['phones'][0]
    seq += 1
    rec = {
        'name': name.strip(),
        'role': clean_grade(grade),
        'code': f'ف-{seq:03d}',
        'phone': phone,
        'join_date': join,
        'post': (ref or {}).get('work', ''),
        'address': (ref or {}).get('address', ''),
    }
    if len(g['phones']) > 1:
        rec['other_phones'] = [x for x in g['phones'] if x != phone]
    # the closing ارقام الافراد roster is authoritative for who is on the force;
    # the daily quick-list was trimmed on 10/8 and omits serving members.
    if ref is not None or last == LAST_DAY:
        rec['status'] = 'active'
    else:
        rec['status'] = 'archived'
        rec['leave_date'] = last
        rec['leave_reason'] = ''
    personnel_records.append(rec)


# --------------------------------------------------------------------------
# 4. emit
# --------------------------------------------------------------------------
def bucket(records, prefix):
    active, archive = [], []
    for i, rec in enumerate(records, 1):
        rec = dict(rec)
        rec['id'] = f'{prefix}-{i:03d}'
        (active if rec['status'] == 'active' else archive).append(rec)
    active.sort(key=lambda p: (p['name'], p['code']))
    archive.sort(key=lambda p: (p['leave_date'], p['name']), reverse=True)
    return {'active': active, 'archive': archive}


off_sorted = [r for r, _, _ in sorted(officer_records, key=lambda x: (x[1], x[0]['name']))]
data = {
    'officers': bucket(off_sorted, 'OFF'),
    'personnel': bucket(personnel_records, 'IND'),
}

# ---- rest periods, keyed back to the officer records just numbered ----
id_by_norm = {}
for p in data['officers']['active'] + data['officers']['archive']:
    id_by_norm[norm_name(p['name'])] = (p['id'], p['name'])

def _span(lv):
    return (datetime.date.fromisoformat(lv['end'])
            - datetime.date.fromisoformat(lv['start'])).days


periods = {}
confirmed = set()          # (key) شوهد فعلاً يوم جوّه مدى الفترة نفسها
for day in DAYS:
    on = datetime.date.fromisoformat(day)
    for row in off_days[day]:
        lv = parse_leave(row.get('duty', ''), on)
        if not lv:
            continue
        key_name = norm_name(row['name'])
        hit = id_by_norm.get(key_name)
        if hit is None:                     # fall back to the fuzzy matcher
            for n, v in id_by_norm.items():
                if name_compatible(key_name, n):
                    hit = v
                    break
        if hit is None:
            continue
        pid, pname = hit
        key = (pid, lv['start'], lv['end'], lv['type'])
        periods[key] = {
            'person_id': pid, 'name': pname, 'type': lv['type'],
            'start': lv['start'].isoformat(), 'end': lv['end'].isoformat(),
            'return_date': lv['return_date'].isoformat(),
            'note': '', 'source': lv['source'],
        }
        if lv['start'] <= on <= lv['end']:
            confirmed.add(key)

# سطر بيعلن راحة مستقبلية ليوم/فترة ("من 22/8 حتي 3/9") بيتكتب مرة واحدة
# قبل الفترة بيوم، وبيتكرر كل يوم جوه الفترة نفسها فعليًا. لو الإعلان ده
# فضل من غير ما يتأكد بأي يوم فعلي جوّه مداه، يبقى غالبًا خطة اتغيّرت ولحد
# نسي يمسح السطر — واليومية الفعلية لتلك الأيام (خدمة حقيقية) هي الأصح.
periods = {k: v for k, v in periods.items() if k in confirmed}

# Counter-style cells ("راحة (2/3)") yield one record per day; stitch runs of
# consecutive same-type days for the same officer back into a single period.
# Longest first, so an explicit range absorbs the per-day rows it duplicates.
merged = []
for lv in sorted(periods.values(),
                 key=lambda x: (x['person_id'], x['type'], x['start'],
                                x['start'] <= x['end'] and -_span(x))):
    prev = merged[-1] if merged else None
    if prev and prev['person_id'] == lv['person_id'] and prev['type'] == lv['type']:
        if lv['end'] <= prev['end']:                 # already inside the period
            continue
        if lv['start'] <= prev['return_date']:       # adjacent or overlapping
            prev['end'] = lv['end']
            prev['return_date'] = (datetime.date.fromisoformat(prev['end'])
                                   + datetime.timedelta(days=1)).isoformat()
            continue
    merged.append(dict(lv))

leaves = sorted(merged, key=lambda x: (x['start'], x['name']))
for i, lv in enumerate(leaves, 1):
    lv['id'] = f'LV-{i:03d}'
data['leaves'] = leaves

# ---- كتالوج الخدمات + تكليفات اليوم ----
# الكتالوج بقى مبني من الأرشيف كله في catalog_build.py — مش مكتوب هنا.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from services import catalog_matcher, extract_assignment   # noqa: E402
from day_build import build_day, search_attached           # noqa: E402
from common import biggest_table                           # noqa: E402

SEED = Path(__file__).resolve().parent / 'catalog_seed.json'
if not SEED.exists():
    raise SystemExit('مافيش catalog_seed.json — شغّل catalog_build.py الأول.')
services = [{k: v for k, v in s.items() if k != 'seen_days'}
            for s in json.loads(SEED.read_text(encoding='utf-8'))]
data['services'] = services
resolve = catalog_matcher(services)
by_name = {s['name']: s for s in services}

officer_id_by_norm = {n: v[0] for n, v in id_by_norm.items()}
personnel_id_by_norm = {}
for bucket_name in ('personnel',):
    for p in data[bucket_name]['active'] + data[bucket_name]['archive']:
        personnel_id_by_norm.setdefault(norm_name(p['name']), p['id'])


def _lookup(index):
    def find(name):
        key = norm_name(name)
        if key in index:
            return index[key]
        for other, value in index.items():
            if name_compatible(key, other):
                return value
        return None
    return find


find_officer_id = _lookup(officer_id_by_norm)
find_personnel_id = _lookup(personnel_id_by_norm)

# تاريخ الرتبة والمنصب والقسم وجهة التشغيل — بيتبني من كل يوم في الأرشيف
# بدل ما ياخد آخر قيمة ويطبّقها على الماضي كله
history = collections.defaultdict(list)

day_assignments, day_officers = {}, {}
unresolved_services = collections.Counter()
for m, d, folder in day_dirs():
    day = iso(m, d)
    if day not in off_days:
        continue
    board_table = biggest_table(str(folder / f'{d}.docx')) if (folder / f'{d}.docx').exists() else None

    officer_rows = []
    for row in off_days[day]:
        oid = find_officer_id(row['name'])
        if not oid:
            continue
        assignment = extract_assignment(row)
        matched = []
        for hit in assignment['services']:
            svc = by_name.get(hit['name']) or resolve(hit['name'])
            if svc:
                matched.append((svc, '' if svc['kind'] == 'حراسات' else hit['shift']))
        post = row.get('post', '')
        if any(k in strip_ar(post) for k in ('العياده الطبيه', 'الخدمات الطبيه')):
            matched = []          # الطبية بتتحسب من المنصب مش من تكليف
        officer_rows.append({**row, 'services': matched})
        history[oid].append({'from': day, 'role': clean_rank(row.get('rank', '')),
                             'post': post.strip(), 'section': row.get('section', 'القوة'),
                             'search_attached': search_attached(post)})

    assignments, states, missed = build_day(
        board_table, officer_rows, resolve, find_officer_id, find_personnel_id)
    unresolved_services.update(missed)
    if assignments:
        day_assignments[day] = assignments
    if states:
        day_officers[day] = states

data['day_assignments'] = day_assignments
data['day_officers'] = day_officers

# ضغط التاريخ: سجل جديد بس لما حاجة تتغيّر فعلًا
FIELDS = ('role', 'post', 'section', 'search_attached')
for officer in [o for b in ('active', 'archive') for o in data['officers'][b]]:
    entries, out = sorted(history.get(officer['id'], []), key=lambda h: h['from']), []
    for entry in entries:
        if not out or any(out[-1][f] != entry[f] for f in FIELDS):
            out.append(entry)
    if out:
        officer['history'] = out
        for field in FIELDS:
            officer[field] = out[-1][field]

data['schema'] = 3
data.pop('duties', None)
data.pop('day_services', None)
OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------
print('\n=== OFFICERS ===', file=sys.stderr)
print(f'  active  {len(data["officers"]["active"]):3}   archived {len(data["officers"]["archive"]):3}'
      f'   total {len(off_sorted)}', file=sys.stderr)
print(f'  without phone: {sum(1 for r in off_sorted if not r["phone"])}', file=sys.stderr)
dupc = [c for c, n in collections.Counter(r['code'] for r in off_sorted).items() if n > 1]
print(f'  duplicate seniority codes in source: {dupc}', file=sys.stderr)
print('\n  archived (leave_date, name):', file=sys.stderr)
for r in data['officers']['archive']:
    print(f'    {r["leave_date"]}  {r["role"]:10} {r["name"]}', file=sys.stderr)

print('\n  rest systems:', dict(collections.Counter(
    (r['rest_system'] + (' ' + r['rest_day'] if r['rest_day'] else ''))
    for r in data['officers']['active'])), file=sys.stderr)
print(f'\n=== REST PERIODS ===\n  total {len(leaves)}', file=sys.stderr)
print('  by type:', dict(collections.Counter(l['type'] for l in leaves)), file=sys.stderr)
print('  officers covered:', len({l["person_id"] for l in leaves}), file=sys.stderr)
if leaves:
    print(f'  range: {leaves[0]["start"]} .. {max(l["end"] for l in leaves)}', file=sys.stderr)

print(f'\n=== SERVICES / DUTIES ===\n  catalogue {len(services)} خدمة'
      f'  |  {dict(collections.Counter(s["kind"] for s in services))}', file=sys.stderr)
_rows = [r for v in day_assignments.values() for r in v]
print(f'  أيام: {len(day_assignments)}  |  إجمالي خانات: {len(_rows)}', file=sys.stderr)
print(f'  بضابط: {sum(1 for r in _rows if r["officer_ids"])}'
      f'  |  بفرد: {sum(1 for r in _rows if r["personnel_ids"])}'
      f'  |  بمجندين بس (بدون ضابط): {sum(1 for r in _rows if not r["officer_ids"] and r["conscripts"])}'
      f'  |  شاغرة: {sum(1 for r in _rows if not r["officer_ids"] and not r["personnel_ids"] and not r["conscripts"])}',
      file=sys.stderr)
_states = [s for v in day_officers.values() for s in v.values()]
print(f'  حالات ضباط: {len(_states)}  |  '
      + str(dict(collections.Counter(s.get("status", "—") for s in _states))), file=sys.stderr)
print(f'  ضباط لهم تاريخ رتبة/منصب: {sum(1 for b in ("active", "archive") for o in data["officers"][b] if o.get("history"))}'
      f'  |  تغييرات مسجّلة: {sum(len(o.get("history", [])) for b in ("active", "archive") for o in data["officers"][b])}',
      file=sys.stderr)
if unresolved_services:
    print(f'\n  !! أسماء على اللوحة مالهاش خدمة في الكتالوج: {sum(unresolved_services.values())}'
          f' ({len(unresolved_services)} اسم مختلف)', file=sys.stderr)
    for name, n in unresolved_services.most_common(15):
        print(f'     {n:4}  {name}', file=sys.stderr)

print('\n=== PERSONNEL ===', file=sys.stderr)
print(f'  active  {len(data["personnel"]["active"]):3}   archived {len(data["personnel"]["archive"]):3}'
      f'   total {len(personnel_records)}', file=sys.stderr)
print(f'  daily phones with no roster match: {len(unresolved)}', file=sys.stderr)
for ph in unresolved:
    print(f'    {ph}  {pnames[ph].most_common(1)[0][0]}', file=sys.stderr)
print('  roles:', dict(collections.Counter(r['role'] for r in personnel_records)), file=sys.stderr)
leave_hist = collections.Counter(r['leave_date'] for r in data['personnel']['archive'])
print('  departures by date:', sorted(leave_hist.items()), file=sys.stderr)
join_hist = collections.Counter(r['join_date'] for r in personnel_records)
print('  joins by date:', sorted(join_hist.items()), file=sys.stderr)
print(f'\nwrote {OUT}', file=sys.stderr)
