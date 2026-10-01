"""GOLDEN REPLAY: ناتج TRANSFORM لليومين المرجعيين (1-9 و2-9-2026) مقابل المخزّن في النظام.

المقارنة حقل بحقل: الأقسام وترتيبها؛ لكل صف (قسم، اسم، فترة): النوع والضباط والأفراد
والقوام والعدد والتسليح والساعة والجهة والاحتساب والملاحظة؛ وحالات الضباط. باقي أيام سبتمبر
اتعملت بالمستورد القديم + تعديلات يدوية، فمقارنتها للاطلاع بس.

كل فرق باقي بيتصنف في import/decisions/golden.csv (مصدر الوثيقة / تعديل يدوي في النظام / خطأ
مستورد) — التقرير بيعرض التصنيف جنب الفرق، والفرق اللي مالوش تصنيف بيظهر «غير مصنف».
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from pathlib import Path
from typing import Any

from backend.text import norm

from .apply import remap_day
from .ledger import Ledger, atomic_write_bytes
from .transform import PROTECTED
from .verify import build_dataset, load_target_days, transformed_days

ROW_FIELDS = ("kind", "officer_ids", "personnel_ids", "conscripts", "conscript_count", "weapon", "time", "party",
              "counts_in_summary", "note")
STATE_FIELDS = ("status", "taqseera", "note")
DECISION_FIELDS = ["date", "kind", "key", "field", "classification", "note"]
SEP = " · "


def _key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (row.get("section", ""), row.get("name", ""), row.get("shift", ""))


def _value(row: dict[str, Any], field: str) -> Any:
    value = row.get(field)
    if field.endswith("_ids"):
        return sorted(value or [])
    if field == "conscripts":
        return sorted((item.get("class", ""), int(item.get("count") or 0)) for item in value or [])
    if field == "counts_in_summary":
        return bool(True if value is None else value)
    if field == "conscript_count":
        return int(value or 0)
    return " ".join(str(value or "").split())


def _sections(rows: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for row in rows:
        if row.get("section") not in out:
            out.append(row.get("section"))
    return out


def _pair(missing: list[tuple[str, str, str]], extra: list[tuple[str, str, str]]) -> list[tuple[Any, Any]]:
    """صف ناقص وصف زيادة في نفس القسم والفترة وأسماؤهم شبه بعض = غالبًا نفس الخدمة باسم تاني."""
    pairs = []
    left = list(extra)
    for item in missing:
        tokens = set(norm(item[1]).replace("ال", " ").split())
        best = max(((len(tokens & set(norm(other[1]).replace("ال", " ").split())), other) for other in left
                    if other[2] == item[2]), default=(0, None))
        if best[0] and best[1] is not None:
            pairs.append((item, best[1]))
            left.remove(best[1])
    return pairs


def compare_day(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    ref_rows = reference.get("assignments") or []
    new_rows = candidate.get("assignments") or []
    ref_by = {_key(row): row for row in ref_rows}
    new_by: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in new_rows:
        new_by.setdefault(_key(row), row)
    missing = [key for key in ref_by if key not in new_by]
    extra = [key for key in new_by if key not in ref_by]
    field_diffs = []
    compared = equal = 0
    exact_rows = 0
    for key, ref in ref_by.items():
        if key not in new_by:
            continue
        row_equal = True
        for field in ROW_FIELDS:
            compared += 1
            a, b = _value(ref, field), _value(new_by[key], field)
            if a == b:
                equal += 1
            else:
                row_equal = False
                field_diffs.append({"key": SEP.join(key), "field": field, "system": a, "import": b})
        exact_rows += row_equal
    ref_states = reference.get("officer_states") or {}
    new_states = candidate.get("officer_states") or {}
    state_diffs = []
    state_compared = state_equal = 0
    for officer_id in sorted(set(ref_states) | set(new_states)):
        a, b = ref_states.get(officer_id), new_states.get(officer_id)
        if a is None or b is None:
            state_diffs.append({"key": officer_id, "field": "presence", "system": a is not None, "import": b is not None})
            continue
        for field in STATE_FIELDS:
            state_compared += 1
            left = bool(a.get(field)) if field == "taqseera" else _value(a, field)
            right = bool(b.get(field)) if field == "taqseera" else _value(b, field)
            if left == right:
                state_equal += 1
            else:
                state_diffs.append({"key": officer_id, "field": field, "system": a.get(field), "import": b.get(field)})
    return {
        "sections": {"system": _sections(ref_rows), "import": _sections(new_rows)},
        "rows": {"system": len(ref_rows), "import": len(new_rows), "matched": len(ref_rows) - len(missing),
                 "exact": exact_rows},
        "missing": [SEP.join(key) for key in missing], "extra": [SEP.join(key) for key in extra],
        "renamed": [(SEP.join(a), SEP.join(b)) for a, b in _pair(missing, extra)],
        "field_diffs": field_diffs, "state_diffs": state_diffs,
        "match": {
            "rows_present": round(100 * (len(ref_rows) - len(missing)) / max(1, len(ref_rows)), 1),
            "fields": round(100 * equal / max(1, compared), 1),
            "states": round(100 * state_equal / max(1, state_compared), 1),
            "section_order": _sections(ref_rows) == _sections(new_rows),
        },
    }


def _decisions(path: Path) -> dict[tuple[str, str, str, str], dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return {(row["date"], row["kind"], row["key"], row.get("field", "")): row for row in csv.DictReader(stream)}


def run_golden(ledger: Ledger, state: dict[str, Any] | None = None) -> dict[str, Any]:
    built = build_dataset(ledger)
    assigned = built["assigned"]
    stored = load_target_days(ledger.data_dir)
    days = transformed_days(ledger)
    decisions = _decisions(ledger.root / "decisions" / "golden.csv")
    results = {}
    for date in sorted(day for day in days if day.startswith("2026-09") and day in stored):
        results[date] = compare_day(stored[date], remap_day(days[date], assigned))
    lines = ["# Golden replay", "",
             "اليومين المرجعيين 1-9 و2-9-2026 هما المعيار؛ باقي سبتمبر اتعمل بالمستورد القديم + تعديلات يدوية "
             "فمقارنته للاطلاع بس.", "",
             "| اليوم | صفوف النظام | صفوف الاستيراد | الصفوف الموجودة | الحقول | حالات الضباط | ترتيب الأقسام |",
             "|---|---|---|---|---|---|---|"]
    for date, result in results.items():
        match = result["match"]
        marker = " (مرجعي)" if date in PROTECTED else ""
        lines.append(f"| {date}{marker} | {result['rows']['system']} | {result['rows']['import']} | "
                     f"{match['rows_present']}% | {match['fields']}% | {match['states']}% | "
                     f"{'مطابق' if match['section_order'] else 'مختلف'} |")
    unclassified = 0
    for date in sorted(PROTECTED):
        result = results.get(date)
        if not result:
            continue
        lines += ["", f"## {date}", "", f"- الأقسام في النظام: {' ← '.join(result['sections']['system'])}",
                  f"- الأقسام في الاستيراد: {' ← '.join(result['sections']['import'])}", "",
                  "| النوع | الصف/الضابط | الحقل | النظام | الاستيراد | التصنيف |", "|---|---|---|---|---|---|"]
        items = ([("missing", key, "", "موجود", "—") for key in result["missing"]]
                 + [("extra", key, "", "—", "موجود") for key in result["extra"]]
                 + [("field", item["key"], item["field"], item["system"], item["import"]) for item in result["field_diffs"]]
                 + [("state", item["key"], item["field"], item["system"], item["import"]) for item in result["state_diffs"]])
        for kind, key, field, left, right in items:
            decision = decisions.get((date, kind, key, field), {})
            label = decision.get("classification") or "غير مصنف"
            unclassified += label == "غير مصنف"
            note = f" — {decision['note']}" if decision.get("note") else ""
            lines.append(f"| {kind} | {key} | {field} | {_cell(left)} | {_cell(right)} | {label}{note} |")
    lines += ["", f"فروق غير مصنفة في اليومين المرجعيين: {unclassified}"]
    atomic_write_bytes(ledger.report_path("golden.md").with_name("golden.md"), ("\n".join(lines) + "\n").encode("utf-8"))
    _write_decision_template(ledger, results, decisions)
    summary = {date: result["match"] for date, result in results.items() if date in PROTECTED}
    summary["unclassified"] = unclassified
    return summary


def _cell(value: Any) -> str:
    return str(value).replace("|", "/").replace("\n", " ")[:80]


def _write_decision_template(ledger: Ledger, results: dict[str, Any], decisions: dict[tuple[str, str, str, str], dict[str, str]]) -> None:
    """قالب التصنيف بكل فروق اليومين المرجعيين — التصنيفات اللي اتكتبت قبل كده بتفضل زي ما هي."""
    rows = []
    for date in sorted(PROTECTED):
        result = results.get(date)
        if not result:
            continue
        keys = ([("missing", key, "") for key in result["missing"]] + [("extra", key, "") for key in result["extra"]]
                + [("field", item["key"], item["field"]) for item in result["field_diffs"]]
                + [("state", item["key"], item["field"]) for item in result["state_diffs"]])
        for kind, key, field in keys:
            old = decisions.get((date, kind, key, field), {})
            rows.append({"date": date, "kind": kind, "key": key, "field": field,
                         "classification": old.get("classification", ""), "note": old.get("note", "")})
    current = {(row["date"], row["kind"], row["key"], row["field"]) for row in rows}
    rows += [row for key, row in sorted(decisions.items()) if key not in current and row.get("classification")]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=DECISION_FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    path = ledger.root / "decisions" / "golden.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, b"\xef\xbb\xbf" + stream.getvalue().encode("utf-8"))


__all__ = ["compare_day", "run_golden"]
