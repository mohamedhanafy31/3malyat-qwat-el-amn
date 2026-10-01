"""VERIFY: بيفحص ناتج TRANSFORM زي ما النظام نفسه هيشوفه بعد التخزين.

بيبني نسخة بيانات في الذاكرة = بيانات الهدف + core_delta مطبّق + أيام TRANSFORM
(بالمعرّفات الحقيقية)، وبعدين بيشغّل دوال النظام الحقيقية عليها: مدققات النماذج،
قواعد المسارات (على القوة، التكرار، قائمة الأهداف المؤرخة، خدمات الأفراد المؤرخة)،
وduty.summarise مقابل جدول الإجمالي في الوورد. مفيش إعادة تنفيذ لقواعد النظام هنا.

درجة اليوم (0–100) = متوسط موزون للمكوّنات المتاحة (المكوّن الغايب بيتشال والأوزان
بتتوزع على الباقي):
- presence 25: يومية الضباط / التكليفات / يومية الأفراد موجودين.
- validity 25: نسبة السجلات اللي بتعدّي المدققات وقواعد المسارات.
- identity 15: نسبة ضباط اليومية اللي اتحسمت هويتهم.
- consistency 15: اتفاق ضباط اللوحة مع تشغيلهم في اليومية + تسلسل عدادات الراحة (k/n).
- summary 20: خانات جدول الإجمالي القابلة للمقارنة اللي طابقت summarise.
اليوم تحت الحد (افتراضي 60) بيتعزل وSTORE ما بيكتبوش.
"""

from __future__ import annotations

import copy
import csv
import io
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from backend.constants import SECTION_GREAT, SECTION_SECURITY, SECTION_SUBCAMP, SECTION_TARGETS
from backend.dated import afraad_basic_on, targets_on
from backend.duty import summarise
from backend.models.day import Assignment, CountEntry, OfficerDayState
from backend.models.leave import Leave
from backend.models.person import Individual, Officer, OfficerHistory
from backend.repo import PeopleRepo
from backend.store import DAY_SECTIONS, merge
from backend.text import norm
from backend.checks import duplicate_of

from .apply import apply_core, assign_ids, remap_day, system_start_of, unlink_off_force
from .ledger import Ledger, atomic_write_bytes, atomic_write_json
from .transform import PROTECTED

VERSION = "1"
DEFAULT_THRESHOLD = 60
WEIGHTS = {"presence": 25, "validity": 25, "identity": 15, "consistency": 15, "summary": 20}
NEW_LAYOUT_FROM = "2026-08-17"

# كلمات عامة ما تنفعش دليل اتفاق بين اسم الخدمة وتشغيل الضابط
_GENERIC = {"خدمه", "خدمات", "وحده", "ارتكاز", "ماموريه", "مامورية", "عمل", "فتره", "صباحيه", "ليليه", "صبح", "ليل",
            "بهدف", "الخدمات", "ضابط", "مشرف", "حمله", "اعمال", "متابعه"}
_ROLE_WORDS = {SECTION_SUBCAMP: ("نوبتجي", "معسكر"), SECTION_GREAT: ("عظيم",), SECTION_SECURITY: ("امن",)}
_COUNTER_RE = re.compile(r"\((\d+)\s*/\s*(\d+)\)")

# الأعمدة القديمة (لحد 7-11-2025): الواضح بس بيتقابل مع summarise، والباقي «غير قابل للمقارنة»
_OLD_DIRECT = {"تقصيره": ("خوارج", "تقصيرة"), "تقصيرة": ("خوارج", "تقصيرة"), "غياب": ("خوارج", "غياب"),
               "مرضي": ("خوارج", "مرضي"), "مرضى": ("خوارج", "مرضي"), "انتداب": ("خوارج", "انتداب"),
               "اجازه طارئه": ("خوارج", "طارئة"), "اجازة طارئة": ("خوارج", "طارئة")}
# «دورية» لوحدها = اجازة دورية (النوع العام «راحة» عندنا)؛ «تدريب دوري» مش راحة
_OLD_REST = re.compile(r"راح|اجاز|أجاز|نصف شهري|^دوري")
_OLD_NOT_REST = ("فرق", "طارئ", "تدريب")
_NEW_GROUPS = {"الخدمات الخارجيه": "خارجية", "الخدمات الداخليه": "داخلية", "الخدمات الطبيه": "طبية",
               "الخوراج": "خوارج", "الخوارج": "خوارج"}
_NEW_SUBS = {"فتره صباحيه": "صباحية", "فتره ليليه": "ليلية", "موجود": "موجود", "راحه": "راحة",
             "تقصيره": "تقصيرة", "طارئه": "طارئة", "غياب": "غياب", "مرضي": "مرضي", "فرقه": "فرقة",
             "انتداب": "انتداب"}


# ---------- بناء النسخة ----------

def _load_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def load_target_days(data_dir: Path) -> dict[str, dict[str, Any]]:
    days = {}
    for path in sorted((data_dir / "days").glob("*/*/*.json")):
        days[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return days


def transformed_days(ledger: Ledger) -> dict[str, dict[str, Any]]:
    folder = ledger.root / "staging" / ledger.batch / "transform" / "days"
    return {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.json"))}


def build_dataset(ledger: Ledger, days: dict[str, dict[str, Any]] | None = None,
                  skip: set[str] | None = None, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """-> {data, assigned, applied, existing, days, ...}. ما بيكتبش أي حاجة.

    `skip`: أيام ما بتتستوردش (بتفضل زي ما هي في الهدف). `data`: نسخة محمّلة بـstore.load_data
    (STORE بيبعتها عشان الحفظ يكتب اللي اتغيّر بس) — وإلا بتتقرا من الملفات."""
    existing = load_target_days(ledger.data_dir)
    if data is None:
        data = merge(_load_json(ledger.data_dir / "core.json", {}), existing)
    before = copy.deepcopy({key: data.get(key) for key in ("officers", "personnel")})
    delta = _load_json(ledger.root / "staging" / ledger.batch / "transform" / "core_delta.json", {})
    id_map = copy.deepcopy(_load_json(ledger.root / "id_map.json", {}))
    assigned = assign_ids(data, delta, id_map)
    days = days if days is not None else transformed_days(ledger)
    imported = {date for date in days if date not in PROTECTED and date not in (skip or set())}
    kept = set(existing) - imported
    applied = apply_core(data, delta, assigned, system_start=system_start_of(existing), imported=imported, kept=kept)
    repo = PeopleRepo(data)
    names = {**(delta.get("ref_names") or {}),
             **{person["id"]: f"{person.get('role', '')}/ {person.get('name', '')}".strip("/ ")
                for person in (data.get("officers") or []) + (data.get("personnel") or [])}}
    remapped = {}
    for date in sorted(imported):
        remapped[date] = remap_day(days[date], assigned)
        on_force = {"officers": set(repo.ids_on_force(date, "officers")),
                    "personnel": set(repo.ids_on_force(date, "personnel"))}
        applied["review"].extend(unlink_off_force(remapped[date], date, on_force, names))
        for key, name in DAY_SECTIONS.items():
            data.setdefault(key, {}).pop(date, None)
            if remapped[date].get(name):
                data[key][date] = remapped[date][name]
    return {"data": data, "assigned": assigned, "applied": applied, "existing": existing, "days": remapped,
            "id_map": id_map, "delta": delta, "before": before, "imported": imported, "kept": kept}


# ---------- جدول الإجمالي ----------

def word_summary(cells: list[dict[str, Any]]) -> dict[str, Any]:
    """خلايا summary_cell لليوم -> {era, values{(group, sub): int}, not_comparable[headers]}."""
    grid: dict[tuple[int, int], dict[int, str]] = defaultdict(dict)
    for cell in cells:
        # الخلية الممتدة على كذا عمود (عنوان «الخدمات الخارجية») بتغطي كل أعمدتها
        for column in cell.get("column_indexes") or [0]:
            grid[(cell.get("table_index") or 0, cell.get("row_index") or 0)][column] = (cell.get("raw_text") or "").strip()
    rows = [grid[key] for key in sorted(grid)]
    for index, row in enumerate(rows):
        joined = norm(" ".join(row.values()))
        if "الخدمات الخارجيه" in joined and index + 2 < len(rows):
            return _new_summary(row, rows[index + 1], rows[index + 2])
        if "اصل القوه" in joined and index + 1 < len(rows):
            return _old_summary(row, rows[index + 1])
    return {"era": "", "values": {}, "not_comparable": []}


def _int(value: str) -> int | None:
    match = re.search(r"\d+", value or "")
    return int(match.group()) if match else (0 if norm(value or "") in {"", "-", "."} else None)


def _old_summary(header: dict[int, str], values: dict[int, str]) -> dict[str, Any]:
    out: dict[tuple[str, str], int] = {}
    skipped = []
    rest = 0
    for column, title in sorted(header.items()):
        key = norm(title)
        value = _int(values.get(column, ""))
        if not key or key == "الجهه" or value is None:
            continue
        if key == "اصل القوه":
            out[("أصل القوة", "")] = value
        elif key in _OLD_DIRECT:
            group, sub = _OLD_DIRECT[key]
            out[(group, sub)] = out.get((group, sub), 0) + value
        elif _OLD_REST.search(key) and not any(word in key for word in _OLD_NOT_REST):
            rest += value
        elif key.startswith("اجمالي خوارج"):
            # بيستبعد التقصيرة وبيشمل أعمدة غير قابلة للمقارنة (فرقة/تدريب/ضابط المباحث) — مش بيتقارن
            skipped.append(title)
        else:
            skipped.append(title)
    # مقيس: الوورد ما بيضمش راحة ضابط العيادة ولا الطارئة لأعمدة الراحة (الضم نزّل الاتفاق من 59% لـ30%)
    out[("خوارج", "راحة")] = rest
    return {"era": "old", "values": out, "not_comparable": skipped}


def _new_summary(groups: dict[int, str], subs: dict[int, str], values: dict[int, str]) -> dict[str, Any]:
    out: dict[tuple[str, str], int] = {}
    skipped = []
    for column in sorted(set(groups) | set(values)):
        group_title, sub_title = norm(groups.get(column, "")), norm(subs.get(column, ""))
        value_text = values.get(column, "")
        if group_title == "اصل القوه":
            out[("أصل القوة", "")] = _int(value_text) or 0
        elif group_title.startswith("الصافي"):
            out[("صافي", "")] = _int(group_title) or 0
        elif group_title.startswith("الحراسات"):
            out[("حراسات", "")] = _int(value_text) or 0
        elif group_title in _NEW_GROUPS and sub_title in _NEW_SUBS:
            group, sub = _NEW_GROUPS[group_title], _NEW_SUBS[sub_title]
            numbers = [int(value) for value in re.findall(r"\d+", value_text)]
            out[(group, sub)] = numbers[0] if numbers else 0
            if group == "خارجية" and "بحث" in value_text and len(numbers) > 1:
                out[("خارجية", "بحث")] = out.get(("خارجية", "بحث"), 0) + numbers[1]
        elif group_title or sub_title:
            skipped.append(f"{groups.get(column, '')} / {subs.get(column, '')}")
    out.setdefault(("خارجية", "بحث"), 0)
    return {"era": "new", "values": out, "not_comparable": sorted(set(skipped))}


def system_summary(summary: dict[str, Any], key: tuple[str, str]) -> int:
    group, sub = key
    if group == "أصل القوة":
        return summary["أصل القوة"]
    if sub == "الإجمالي":
        return sum(summary[group].values())
    value = summary[group]
    return value if isinstance(value, int) else value.get(sub, 0)


def load_summary_cells(ledger: Ledger) -> dict[str, list[dict[str, Any]]]:
    path = ledger.staging_path("extract")
    cells: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if not path.exists():
        return cells
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if '"summary_cell"' not in line:
                continue
            record = json.loads(line)
            if record.get("role") == "roster" and record.get("record_type") == "summary_cell" and not record.get("stale"):
                cells[record["date"]].append(record)
    return cells


def load_quarantined_documents(ledger: Ledger) -> set[tuple[str, str]]:
    path = ledger.staging_path("validate")
    out = set()
    if path.exists():
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                record = json.loads(line)
                if record.get("source_record_type") == "document" and record.get("verdict") == "quarantine":
                    out.add((record.get("date", ""), record.get("path", "")))
    return out


# ---------- فحص يوم ----------

def _tokens(text: str) -> set[str]:
    return {token for token in norm(text).split() if len(token) >= 3 and token not in _GENERIC}


def _agrees(row: dict[str, Any], note: str) -> bool:
    flat = norm(note)
    if row["section"] in _ROLE_WORDS:
        return any(word in flat for word in _ROLE_WORDS[row["section"]])
    tokens = _tokens(row["name"])
    return bool(tokens) and any(token in flat for token in tokens)


def check_day(data: dict[str, Any], date: str, day: dict[str, Any], provenance: dict[str, Any],
              review: list[dict[str, Any]], word: dict[str, Any], repo: PeopleRepo) -> dict[str, Any]:
    issues: list[str] = []
    items = 0
    invalid = 0
    on_force = {"officers": set(repo.ids_on_force(date, "officers")),
                "personnel": set(repo.ids_on_force(date, "personnel"))}
    targets = set(targets_on(data, date))
    rows = day.get("assignments") or []
    for row in rows:
        items += 1
        errors = Assignment.from_dict(row).validate()
        for field, category in (("officer_ids", "officers"), ("personnel_ids", "personnel")):
            missing = [pid for pid in row.get(field) or [] if pid not in on_force[category]]
            if missing:
                errors.append(f"خارج القوة: {','.join(missing)}")
        if row["section"] == SECTION_TARGETS and row["name"] not in targets:
            errors.append("الهدف ليس في قائمة الأهداف المؤرخة")
        people = (row.get("officer_ids") or []) + (row.get("personnel_ids") or [])
        if people and duplicate_of(data, date, row["name"], row.get("shift", ""), people, ignore_id=row["id"]):
            errors.append("تكرار نفس الشخص على نفس الخدمة والفترة")
        if errors:
            invalid += 1
            issues.extend(f"{error} — {row['id']} {row['name']}" for error in errors)
    states = day.get("officer_states") or {}
    for officer_id, state in states.items():
        items += 1
        errors = OfficerDayState.from_dict(state).validate()
        if officer_id not in on_force["officers"]:
            errors.append("خارج القوة")
        if errors:
            invalid += 1
            issues.extend(f"{error} — {officer_id}" for error in errors)
    for entry in ((day.get("counts") or {}).get("entries") or []):
        items += 1
        errors = CountEntry.from_dict(entry).validate()
        if errors:
            invalid += 1
            issues.extend(f"{error} — {entry.get('id')}" for error in errors)
    allowed = {item["id"] for item in afraad_basic_on(data, date)}
    afraad_outside = 0
    for entry_id, entry in (day.get("afraad_basic") or {}).items():
        items += 1
        errors = []
        if entry_id not in allowed:
            afraad_outside += 1  # محفوظ في الملف بس مش ظاهر في يومية الأفراد لليوم ده
        for field in ("morning_person_id", "night_person_id"):
            if entry.get(field) and entry[field] not in on_force["personnel"]:
                errors.append(f"{field} خارج القوة")
        if errors:
            invalid += 1
            issues.extend(f"{error} — {entry_id}" for error in errors)

    roster = provenance.get("roster") or []
    unresolved = sum(1 for item in review if item["type"] == "unresolved_roster_officer")
    duplicates = sum(1 for item in review if item["type"] == "duplicate_roster_officer")
    derived = bool((day.get("import") or {}).get("derived"))
    agree = total = 0
    if not derived:
        for row in rows:
            for officer_id in row.get("officer_ids") or []:
                if officer_id in roster:
                    total += 1
                    agree += int(_agrees(row, (states.get(officer_id) or {}).get("note", "")))
    comparison = {}
    if word.get("values"):
        summary = summarise(data, date)["summary"]
        for key, value in word["values"].items():
            comparison["/".join(part for part in key if part)] = (value, system_summary(summary, key))
    matched = sum(1 for word_value, ours in comparison.values() if word_value == ours)
    components = {
        "presence": (0.5 * bool(roster) + 0.3 * bool(rows) + 0.2 * bool(day.get("afraad_basic"))),
        "validity": 1 - invalid / items if items else None,
        "identity": len(roster) / (len(roster) + unresolved) if roster or unresolved else None,
        "consistency": agree / total if total else None,
        "summary": matched / len(comparison) if comparison else None,
    }
    return {"date": date, "derived": derived, "rows": len(rows), "states": len(states), "roster": len(roster),
            "items": items, "invalid": invalid, "issues": issues, "unresolved": unresolved,
            "duplicate_roster": duplicates, "board_agree": agree, "board_total": total,
            "afraad_outside_list": afraad_outside, "on_force_not_on_roster": len(on_force["officers"] - set(roster)),
            "summary_era": word.get("era", ""), "summary": comparison, "not_comparable": word.get("not_comparable", []),
            "components": components}


def leave_counter_breaks(days: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """«(k/n)» في تشغيل الضابط لازم يزيد 1 كل يوم لنفس n — بيرجع الكسور لكل يوم."""
    out: dict[str, list[str]] = defaultdict(list)
    last: dict[str, tuple[str, int, int]] = {}
    for date in sorted(days):
        for officer_id, state in (days[date].get("officer_states") or {}).items():
            match = _COUNTER_RE.search(state.get("note") or "")
            if not match:
                last.pop(officer_id, None)
                continue
            k, n = int(match.group(1)), int(match.group(2))
            previous = last.get(officer_id)
            if previous and previous[2] == n and k not in (previous[1] + 1, 1) and _next_day(previous[0]) == date:
                out[date].append(f"{officer_id}: ({previous[1]}/{n}) ← ({k}/{n})")
            last[officer_id] = (date, k, n)
    return out


def _next_day(value: str) -> str:
    import datetime as dt
    return (dt.date.fromisoformat(value) + dt.timedelta(days=1)).isoformat()


def score(components: dict[str, float | None]) -> int:
    available = {key: value for key, value in components.items() if value is not None}
    weight = sum(WEIGHTS[key] for key in available)
    return round(100 * sum(WEIGHTS[key] * value for key, value in available.items()) / weight) if weight else 0


# ---------- فحص البيانات الأساسية ----------

def person_errors(people: list[dict[str, Any]], model: type) -> dict[str, list[str]]:
    out = {}
    for person in people:
        errors = model.from_dict(person).validate()
        if model is Officer:
            for entry in person.get("history") or []:
                errors.extend(OfficerHistory.from_dict(entry).validate())
        if errors:
            out[person["id"]] = sorted(set(errors))
    return out


def check_core(data: dict[str, Any], before: dict[str, Any], applied: dict[str, Any]) -> dict[str, Any]:
    """أخطاء النماذج اللي الاستيراد **أدخلها** بس — الموجودة قبله في بيانات النظام بتتعد لوحدها."""
    issues, preexisting = [], []
    for category, model in (("officers", Officer), ("personnel", Individual)):
        old = person_errors(before.get(category) or [], model)
        new = person_errors(data.get(category) or [], model)
        names = {person["id"]: person.get("name") for person in data.get(category) or []}
        for person_id, errors in sorted(new.items()):
            introduced = [error for error in errors if error not in old.get(person_id, [])]
            if introduced:
                issues.append({"id": person_id, "name": names.get(person_id), "errors": introduced})
            elif errors:
                preexisting.append({"id": person_id, "name": names.get(person_id), "errors": errors})
    leave_problems = Counter(problem for item in applied["review"] if item["type"] == "leave_not_added"
                             for problem in item["problems"])
    return {"people_issues": issues, "preexisting_issues": preexisting, "leave_issues": dict(leave_problems),
            "applied": applied["stats"], "review": applied["review"]}


# ---------- المرحلة ----------

def run_verify(ledger: Ledger, state: dict[str, Any], *, threshold: int = DEFAULT_THRESHOLD) -> dict[str, Any]:
    ledger.mark_stage(state, "verify", "running")
    built = build_dataset(ledger)
    data, days = built["data"], built["days"]
    review_by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    review_path = ledger.staging_path("transform-review")
    if review_path.exists():
        for line in review_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                review_by_day[item.get("date", "")].append(item)
    cells = load_summary_cells(ledger)
    counters = leave_counter_breaks(days)
    repo = PeopleRepo(data)
    results = []
    for date in sorted(days):
        provenance = _load_json(ledger.root / "provenance" / date[:4] / date[5:7] / f"{date}.json", {})
        result = check_day(data, date, days[date], provenance, review_by_day.get(date, []),
                           word_summary(cells.get(date, [])), repo)
        breaks = counters.get(date, [])
        if breaks:
            result["issues"].extend(f"كسر تسلسل عداد راحة — {item}" for item in breaks)
            consistency = result["components"]["consistency"]
            penalty = max(0.0, 1 - len(breaks) / max(1, result["roster"]))
            result["components"]["consistency"] = penalty if consistency is None else (consistency + penalty) / 2
        result["counter_breaks"] = len(breaks)
        result["score"] = score(result["components"])
        result["quarantined"] = result["score"] < threshold
        results.append(result)
    core = check_core(data, built["before"], built["applied"])
    quarantined = {r["date"]: _reasons(r) for r in results if r["quarantined"]}
    atomic_write_json(ledger.root / "quarantine" / f"{ledger.batch}-verify.json",
                      {"threshold": threshold, "days": quarantined})
    report = _report(ledger, results, core, threshold)
    atomic_write_bytes(ledger.report_path("verify.md"), report.encode("utf-8"))
    atomic_write_bytes(ledger.report_path("verify.csv"), _csv(results).encode("utf-8-sig"))
    checkpoint = {"days": len(results), "quarantined": len(quarantined), "threshold": threshold,
                  "mean_score": round(sum(r["score"] for r in results) / len(results), 1) if results else 0,
                  "people_issues": len(core["people_issues"]), "leave_issues": core["leave_issues"],
                  "version": VERSION}
    atomic_write_json(ledger.report_path("verify.json"), {**checkpoint, "core": core,
                                                          "summary_agreement": _summary_agreement(results)})
    ledger.mark_stage(state, "verify", "complete", checkpoint)
    return checkpoint


def _reasons(result: dict[str, Any]) -> list[str]:
    reasons = []
    components = result["components"]
    if components["presence"] < 1:
        reasons.append("مستندات ناقصة")
    for key in ("validity", "identity", "consistency", "summary"):
        if components[key] is not None and components[key] < 0.6:
            reasons.append(f"{key} {components[key]:.0%}")
    return reasons or ["درجة منخفضة"]


def _summary_agreement(results: list[dict[str, Any]]) -> dict[str, dict[str, list[int]]]:
    out: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for result in results:
        for key, (word_value, ours) in result["summary"].items():
            cell = out[result["summary_era"]][key]
            cell[0] += int(word_value == ours)
            cell[1] += 1
    return {era: dict(cells) for era, cells in out.items()}


def _csv(results: list[dict[str, Any]]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["date", "score", "quarantined", "derived", "rows", "states", "roster", "invalid", "unresolved",
                     "board_agree", "board_total", "summary_era", "summary_matched", "summary_cells",
                     "counter_breaks", "afraad_outside_list", "first_issue"])
    for r in results:
        matched = sum(1 for a, b in r["summary"].values() if a == b)
        writer.writerow([r["date"], r["score"], int(r["quarantined"]), int(r["derived"]), r["rows"], r["states"],
                         r["roster"], r["invalid"], r["unresolved"], r["board_agree"], r["board_total"],
                         r["summary_era"], matched, len(r["summary"]), r["counter_breaks"],
                         r["afraad_outside_list"], r["issues"][0] if r["issues"] else ""])
    return stream.getvalue()


def _report(ledger: Ledger, results: list[dict[str, Any]], core: dict[str, Any], threshold: int) -> str:
    lines = [f"# VERIFY — {ledger.batch}", "", f"الحد: {threshold}. الأيام: {len(results)}.", "",
             "## الدرجات حسب السنة", "", "| السنة | أيام | متوسط | أقل | ≥90 | 60–89 | <60 (معزول) |", "|---|---|---|---|---|---|---|"]
    by_year: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        by_year[r["date"][:4]].append(r)
    for year, items in sorted(by_year.items()):
        scores = [r["score"] for r in items]
        lines.append(f"| {year} | {len(items)} | {sum(scores) / len(scores):.1f} | {min(scores)} | "
                     f"{sum(s >= 90 for s in scores)} | {sum(threshold <= s < 90 for s in scores)} | "
                     f"{sum(s < threshold for s in scores)} |")
    reasons = Counter(reason for r in results if r["quarantined"] for reason in _reasons(r))
    lines += ["", "## أسباب العزل", ""] + [f"- {reason}: {count}" for reason, count in reasons.most_common()] or ["- لا يوجد"]
    lines += ["", "## اتفاق جدول الإجمالي (الوورد مقابل summarise)", "",
              "| الحقبة | الخانة | مطابق | من | النسبة |", "|---|---|---|---|---|"]
    for era, cells in sorted(_summary_agreement(results).items()):
        for key, (ok, total) in sorted(cells.items()):
            lines.append(f"| {era} | {key} | {ok} | {total} | {ok / total:.0%} |")
    skipped = Counter(title for r in results for title in r["not_comparable"])
    lines += ["", "أعمدة غير قابلة للمقارنة (معناها مش مؤكد ومالهاش خانة واضحة في summarise):", ""]
    lines += [f"- {title}: {count} يوم" for title, count in skipped.most_common()]
    totals = Counter()
    for r in results:
        totals.update({"rows": r["rows"], "invalid": r["invalid"], "agree": r["board_agree"], "total": r["board_total"],
                       "breaks": r["counter_breaks"], "unresolved": r["unresolved"], "dup": r["duplicate_roster"],
                       "afraad_outside": r["afraad_outside_list"]})
    issue_types = Counter(issue.split(" — ")[0].split(":")[0] for r in results for issue in r["issues"])
    lines += ["", "## الاتساق", "",
              f"- سجلات مخالفة لقواعد النظام: {totals['invalid']} من {totals['rows']} تكليف + الحالات والأعداد.",
              f"- اتفاق ضباط اللوحة مع تشغيلهم في اليومية: {totals['agree']} من {totals['total']}"
              + (f" ({totals['agree'] / totals['total']:.0%})" if totals["total"] else ""),
              f"- كسور تسلسل عدادات الراحة (k/n): {totals['breaks']}",
              f"- ضباط يومية بلا هوية محسومة: {totals['unresolved']}؛ ضابط مكرر في نفس اليومية: {totals['dup']}",
              f"- خدمات أفراد خارج القائمة المؤرخة لليوم (محفوظة ومش ظاهرة): {totals['afraad_outside']}",
              "- اتفاق قائد/ساعة الطوارئ بين يومية الأفراد وكشف المواعيد: بيتدمجوا في TRANSFORM (الساعة من أول مصدر"
              " فيه قيمة)؛ الاختلاف مش متسجل كبند منفصل.", "",
              "### أكثر المخالفات", ""] + [f"- {kind}: {count}" for kind, count in issue_types.most_common(15)]
    lines += ["", "## البيانات الأساسية بعد التطبيق", "",
              "إحصائيات: " + ", ".join(f"{k}={v}" for k, v in core["applied"].items()), "",
              f"- أشخاص فيهم أخطاء نموذج أدخلها الاستيراد: {len(core['people_issues'])}",
              f"- أشخاص فيهم أخطاء نموذج موجودة في النظام قبل الاستيراد (مش من الاستيراد): "
              f"{len(core['preexisting_issues'])}"]
    lines += [f"  - {item['id']} {item['name']}: {'؛ '.join(item['errors'])}" for item in core["people_issues"][:30]]
    lines += [f"- راحات اتسابت للمراجعة: {key} = {value}" for key, value in core["leave_issues"].items()]
    review = Counter(item["type"] for item in core["review"])
    lines += [f"- مراجعة: {key} = {value}" for key, value in review.most_common()]
    worst = sorted(results, key=lambda r: (r["score"], r["date"]))[:30]
    lines += ["", "## أسوأ 30 يوم", "", "| اليوم | الدرجة | مشتق | الأسباب | أول مخالفة |", "|---|---|---|---|---|"]
    for r in worst:
        first = (r["issues"][0] if r["issues"] else "").replace("|", "/")
        lines.append(f"| {r['date']} | {r['score']} | {'نعم' if r['derived'] else ''} | {'، '.join(_reasons(r))} | {first[:90]} |")
    return "\n".join(lines) + "\n"


__all__ = ["VERSION", "DEFAULT_THRESHOLD", "build_dataset", "check_day", "run_verify", "score", "word_summary"]
