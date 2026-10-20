#!/usr/bin/env python3
"""Align the emergency-service columns of the detailed daily log — المجندون،
التسليح، الانتظام، الجهة — with the «الخدمات الطارئة» part of each day's
«افراد» .docx (the only per-day source that carries all four).

Reference shape (2026-08-01): `time` is just the hour («7ص»), `party` is the
quoted place («عتاقة»), `weapon` is the weapon, `conscript_count` is the total
قوام written in the sheet.

Per day, for each sheet row matched by name to the log's emergency / custom rows
(every row of that name, e.g. the 8ص and 8م rows of one service):
  * conscript_count / weapon / time / party  ← the sheet, but only when the sheet
    has a value (a blank «ـــ» never erases anything);
  * "8ص + 8م" is split per shift row (صباحية → 8ص، ليلية → 8م);
  * otherwise-unmatched rows whose `time` has the place glued to it
    («7ص عتاقة») are split into time + party when `party` is empty.
People (officers/personnel) are never touched.

Dry-run by default; --write needs the system stopped, and keeps a snapshot and a
pre-image of the touched day files.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import docx  # noqa: E402

from backend import store  # noqa: E402
from backend.assignments import peek_day  # noqa: E402
from backend.board import ASSIGNMENT_SECTIONS  # noqa: E402
from backend.constants import SECTION_OCCASIONAL  # noqa: E402
from backend.text import norm  # noqa: E402
from tools.import_afraad_emergency import candidates, emergency_rows  # noqa: E402
from tools.import_afraad_rosters import DEFAULT_ROOT, DIGITS, PLACEHOLDER, discover  # noqa: E402

QUOTED = re.compile(r'["“”]\s*(.+?)\s*["“”]')
HOUR = re.compile(r"^\s*(\d{1,2}(?::\d{2})?\s*[صظم])", re.U)
HOUR_RE = r"\d{1,2}(?:[:.]\d{2})?\s*[صظم]"
FIELDS = ("conscript_count", "weapon", "time", "party")
WEAPON_WORDS = {"الي": "آلي", "الى": "آلي", "آلي": "آلي", "ألي": "آلي", "دونك": "دونك", "دوك": "دونك",
                "فض": "فض", "طلبه": "طلبة", "طلبة": "طلبة", "رياضي": "رياضي", "رياضى": "رياضي",
                "حفظ نظام": "حفظ نظام", "ميك": "ميك", "مايك": "ميك", "ف": "فيدرال",
                "فدرال": "فيدرال", "فيدرال": "فيدرال", "خ": "خرطوش", "خرطوش": "خرطوش",
                "خفيفة": "خفيفة", "كلبش": "كلبش"}


def canonical_weapon(text: str) -> str:
    """التسليح بصيغته الموحّدة، أو «» لو الخلية مش تسليح (اسم ضابط مثلًا)."""
    text = " ".join(str(text or "").translate(DIGITS).replace("/", "+").split())
    if blank(text):
        return ""
    tokens = [t.strip() for t in text.split("+") if t.strip()]
    mapped = []
    for token in tokens:
        token = re.sub(r"^\d+\s*", "", token)  # «1خفيفة»
        parts = [token] if token in WEAPON_WORDS or token == "حفظ نظام" else token.split()
        for part in parts:
            if part not in WEAPON_WORDS:
                return ""
            mapped.append(WEAPON_WORDS[part])
    return " + ".join(dict.fromkeys(mapped))


# فئة المجندين بتتحدد من نوع الخدمة (التسليح): كل نوع ليه فئة، والفئات المكمّلة
# (فيدرال/خرطوش/كلبش…) مالهاش فئة. «فرد» مش فئة مجندين — بتفضل زي ما هي.
CLASS_BY_WEAPON = {"آلي": "مج", "دونك": "وحدة حفظ نظام", "فض": "وحدة فض",
                   "رياضي": "رياضي", "طلبة": "طلبة"}
KEEP_CLASSES = {"فرد"}


def conscript_classes(row, weapon):
    """-> قايمة الفئات الجديدة للصف، أو None لو مفيش داعي للتغيير."""
    old = [dict(c) for c in row.get("conscripts") or [] if isinstance(c, dict)]
    kept = [c for c in old if str(c.get("class") or "").strip() in KEEP_CLASSES]
    units = [c for c in old if c not in kept]
    wanted = list(dict.fromkeys(
        CLASS_BY_WEAPON[t] for t in str(weapon or "").split(" + ") if t in CLASS_BY_WEAPON))
    if not wanted:
        if units or not (row.get("conscript_count") or 0):
            # بدون تسليح معروف: الفئة الفاضية/«وحدة» بس هي اللي بتتسمّى «مج»
            fixed = [{"class": (str(c.get("class") or "").strip() if str(c.get("class") or "").strip()
                                not in ("", "وحدة") else "مج"), "count": c.get("count") or 1}
                     for c in units]
            return (fixed + kept) if fixed != units else None
        wanted = ["مج"]
    prior = {str(c.get("class") or "").strip(): c.get("count") for c in units}
    fresh = [{"class": name, "count": prior.get(name) or 1} for name in wanted]
    new = fresh + kept
    return new if new != old else None


def same(a, b) -> bool:
    return norm(str(a or "")).replace(" ", "") == norm(str(b or "")).replace(" ", "")


def blank(text: str) -> bool:
    return not str(text or "").strip() or bool(PLACEHOLDER.match(str(text)))


def parse_count(text: str):
    text = str(text or "").translate(DIGITS)
    if blank(text):
        return None
    numbers = [int(n) for n in re.findall(r"\d+", text)]
    if not numbers:
        return None
    # «4 / 1» = قوامان مجمّعان (طلبة / آلي)
    return sum(numbers) if "/" in text else numbers[0]


def split_time(text: str):
    """«7ص "عتاقة"» -> ('7ص', 'عتاقة'); «8ص + 8م» -> (['8ص','8م'], '')."""
    text = " ".join(str(text or "").translate(DIGITS).split())
    quoted = QUOTED.search(text)
    party = quoted[1].strip() if quoted else ""
    rest = QUOTED.sub(" ", text).strip()
    hours = re.findall(HOUR_RE, rest)
    return [h.replace(" ", "") for h in hours], party, rest


def shift_time(hours, shift, raw_rest):
    if not hours:
        return raw_rest or ""
    if len(hours) > 1:
        return hours[1] if shift == "ليلية" else hours[0]
    return hours[0]


def wanted(sheet, row, fill_only=False, count_override=None):
    """القيم اللي الصف ده لازم ياخدها من صف الورقة (أو {} لو مفيش)."""
    hours, party, rest = split_time(sheet["time"])
    count = count_override if count_override is not None else parse_count(sheet["count"])
    want = {}
    if count is not None:
        want["conscript_count"] = count
    weapon = canonical_weapon(sheet["weapon"])
    if weapon:
        want["weapon"] = weapon
    if hours:  # «12ل» وأمثالها مالهاش ساعة واضحة فمابتتغيّرش
        want["time"] = shift_time(hours, row.get("shift"), rest)
    if party:
        want["party"] = party
    elif hours:
        tail = re.sub(HOUR_RE, " ", rest).strip(" +-/،")
        if re.search(r"[\u0600-\u06ff]", tail) and not (row.get("party") or "").strip():
            want["party"] = " ".join(tail.split())  # المكان مكتوب من غير اقتباس
    out = {}
    for key, value in want.items():
        old = row.get(key)
        if value in ("", None) or old == value:
            continue
        if fill_only and old not in ("", None, 0):
            continue
        if key in ("weapon", "party", "time") and same(old, value):
            continue  # فرق إملائي فقط
        if key == "weapon" and old and canonical_weapon(old) == value:
            continue
        out[key] = value
    return out


def plan_day(data, day, path):
    log = [a for a in peek_day(data, day)
           if (a.get("section") or SECTION_OCCASIONAL) == SECTION_OCCASIONAL
           or a.get("section") not in ASSIGNMENT_SECTIONS]
    groups = {}
    for sheet in emergency_rows(docx.Document(path)):
        idx = tuple(candidates(log, sheet["service"]))
        if idx:
            groups.setdefault(idx, []).append(sheet)
    changes, touched = [], set()

    def add(row, want):
        for key, value in want.items():
            changes.append({"id": row["id"], "service": row["name"], "field": key,
                            "old": row.get(key), "new": value})

    for idx, sheets in groups.items():
        touched.update(idx)
        rows = [log[i] for i in idx]
        if len(sheets) == 1:                      # خدمة واحدة، ممكن لها صف لكل فترة
            for row in rows:
                add(row, wanted(sheets[0], row))
        elif len(sheets) == len(rows):            # نفس العدد: واحد لواحد بالترتيب
            for sheet, row in zip(sheets, rows):
                add(row, wanted(sheet, row))
        elif len(rows) == 1:                      # اللوحة دامجة الصفوف في صف واحد
            counts = [parse_count(s["count"]) for s in sheets]
            total = sum(c for c in counts if c) or None
            add(rows[0], wanted(sheets[0], rows[0], fill_only=True, count_override=total))
        else:                                     # غير متطابق: ماسيبش غير الفاضي
            for sheet, row in zip(sheets, rows):
                add(row, wanted(sheet, row, fill_only=True))
    # فئات المجندين من نوع الخدمة، بعد ما التسليح الجديد يتطبّق
    pending = {}
    for change in changes:
        pending.setdefault(change["id"], {})[change["field"]] = change["new"]
    for row in log:
        weapon = pending.get(row["id"], {}).get("weapon", row.get("weapon"))
        count = pending.get(row["id"], {}).get("conscript_count", row.get("conscript_count") or 0)
        probe = {**row, "conscript_count": count}
        fixed = conscript_classes(probe, canonical_weapon(weapon))
        if fixed is not None:
            changes.append({"id": row["id"], "service": row["name"], "field": "conscripts",
                            "old": row.get("conscripts"), "new": fixed})

    # hour+place glued together in rows the sheet did not cover
    for i, row in enumerate(log):
        if i in touched:
            continue
        hours, party, rest = split_time(row.get("time"))
        tail = re.sub(HOUR_RE, " ", rest).strip(" +-/،")
        if hours and tail and not (row.get("party") or "").strip():
            changes.append({"id": row["id"], "service": row["name"], "field": "time",
                            "old": row.get("time"), "new": hours[0]})
            changes.append({"id": row["id"], "service": row["name"], "field": "party",
                            "old": row.get("party"), "new": tail.strip(' "')})
    return changes


def apply_day(data, day, changes):
    rows = {a["id"]: a for a in peek_day(data, day)}
    for change in changes:
        rows[change["id"]][change["field"]] = change["new"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--start", default="2026-08-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--show", default=None, help="اطبع تفاصيل يوم بعينه (YYYY-MM-DD)")
    args = parser.parse_args()

    files, _notes = discover(args.root, args.start, args.end)
    data = store.load_data(store.ALL_DAYS)
    plan, per_field = {}, Counter()
    for day, path in files.items():
        if not peek_day(data, day):
            continue
        changes = plan_day(data, day, path)
        if changes:
            plan[day] = changes
            per_field.update(c["field"] for c in changes)
    print(f"days={len(files)} days_to_change={len(plan)} changes={sum(map(len, plan.values()))} "
          + " ".join(f"{k}={v}" for k, v in sorted(per_field.items())))
    if args.show:
        for c in plan.get(args.show, []):
            print(f"  {c['service']} · {c['field']}: {c['old']!r} -> {c['new']!r}")
    if args.report:
        args.report.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    if not args.write:
        print("dry-run — أضف --write للتنفيذ.")
        return 0

    store.acquire_process_lock()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    preimage = store.DATA_DIR / "import" / "preimage" / f"emergency-columns-{stamp}"
    for day in plan:
        source = store.day_path(day)
        if source.exists():
            target = preimage / "files" / source.relative_to(store.DATA_DIR)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    snapshot = store.snapshot_now()
    for day, changes in plan.items():
        apply_day(data, day, changes)
    store.save_data(data)
    preimage.mkdir(parents=True, exist_ok=True)
    (preimage / "report.json").write_text(json.dumps(
        {"at": datetime.now().isoformat(timespec="seconds"), "snapshot": str(snapshot or ""),
         "changes": plan}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written={len(plan)} preimage={preimage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
