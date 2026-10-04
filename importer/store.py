"""STORE / DIFF / ROLLBACK / REPORT: كتابة الدفعة على مجلد البيانات بأمان وإمكانية الرجوع.

STORE (عرض بس من غير --write):
- لازم verify يكون اكتمل للدفعة، وهجرات 013/014 متطبقة على الهدف.
- اليومين المرجعيين (1-9 و2-9-2026) عمرهم ما بيتكتبوا؛ اليوم المعزول بيتساب.
- يوم موجود اتعمل جوه النظام (من غير علامة استيراد) بيتستبدل بس مع --replace-existing
  وصف موافقة لتاريخه في import/decisions/replace.csv (بعد قراية تقرير الفرق).
- قبل الكتابة: نسخة أصل لكل ملف هيتلمس (أو علامة «ماكانش موجود») في import/preimage/<batch>/،
  وstore.snapshot_now(). الكتابة نفسها بـstore.save_data فبتكتب الملفات اللي اتغيرت بس، وكل ملف ذري.
- إعادة التشغيل: نفس النتيجة بالظبط (id_map بيثبت المعرّفات) — صفر ملفات مكتوبة.

ROLLBACK: بيرجّع كل نسخة أصل بالبايت (وبيمسح الملفات اللي ماكانتش موجودة) ويتأكد بالبصمة.
سجل الرجوع بيتكتب في سجل الدفعة مش في change_log، عشان core.json يرجع زي ما كان بالبايت.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from backend import changes, store

from .golden import compare_day
from .ledger import Ledger, atomic_write_bytes, atomic_write_json
from .transform import PROTECTED
from .verify import build_dataset, load_target_days, transformed_days

VERSION = "1"
REPLACE_FIELDS = ["date", "approve", "note"]
_YES = {"نعم", "yes", "y", "1", "موافق"}


class StoreRefused(RuntimeError):
    pass


_LOCKED: set[str] = set()


def _lock() -> None:
    """قفل النظام نفسه (السيرفر شغال على نفس المجلد = رفض). مرة واحدة لكل عملية — store ثم rollback
    في نفس العملية ما يرفضوش بعض."""
    key = str(Path(store.DATA_DIR).resolve())
    if key not in _LOCKED:
        store.acquire_process_lock()
        _LOCKED.add(key)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "absent"


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, b"\xef\xbb\xbf" + stream.getvalue().encode("utf-8"))


def approvals(ledger: Ledger) -> set[str]:
    return {row["date"] for row in _read_csv(ledger.root / "decisions" / "replace.csv")
            if (row.get("approve") or "").strip().lower() in _YES}


def partial_source_dates(ledger: Ledger) -> set[str]:
    """Dates missing an authoritative roster or personnel source."""
    path = ledger.report_path("manifest.csv")
    if not path.exists():
        return set()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return {row["date"] for row in csv.DictReader(stream)
                if row.get("date") and (not (row.get("roster") or "").strip()
                                         or not (row.get("afraad") or "").strip())}


def quarantined(ledger: Ledger) -> set[str]:
    path = ledger.root / "quarantine" / f"{ledger.batch}-verify.json"
    return set((json.loads(path.read_text(encoding="utf-8")).get("days") or {}) if path.exists() else {})


# ---------- الخطة ----------

def plan(ledger: Ledger, *, replace_existing: bool = False) -> dict[str, Any]:
    """-> {date: (action, reason)} لكل يوم مستورد. action ∈ write/replace/update/skip."""
    days = transformed_days(ledger)
    target = load_target_days(ledger.data_dir)
    held = quarantined(ledger)
    approved = approvals(ledger)
    partial = partial_source_dates(ledger)
    result: dict[str, tuple[str, str]] = {}
    for date in sorted(days):
        current = target.get(date)
        if date in PROTECTED:
            result[date] = ("skip", "يوم مرجعي محمي")
        elif date in partial:
            result[date] = ("skip", "مصدر جزئي — محتاج مراجعة")
        elif date in held:
            result[date] = ("skip", "معزول في verify")
        elif current is None:
            result[date] = ("write", "يوم جديد")
        elif current.get("import"):
            result[date] = ("update", f"مستورد قبل كده ({current['import'].get('batch', '')})")
        elif not replace_existing:
            result[date] = ("skip", "يوم من النظام — محتاج --replace-existing")
        elif date not in approved:
            result[date] = ("skip", "يوم من النظام — مفيش موافقة في decisions/replace.csv")
        else:
            result[date] = ("replace", "يوم من النظام بموافقة المراجع")
    return {"days": days, "plan": result}


def check_migrations(data_dir: Path, dates: set[str] | None = None) -> list[str]:
    """013/014 لازم يكونوا اتطبقوا: مفيش «medical» في حالات الضباط ولا label_override/tags على التكليفات."""
    problems = []
    for date, blob in load_target_days(data_dir).items():
        if dates is not None and date not in dates:
            continue
        if any("medical" in state for state in (blob.get("officer_states") or {}).values()):
            problems.append(f"{date}: medical (هجرة 013)")
        if any("label_override" in row or "tags" in row for row in blob.get("assignments") or []):
            problems.append(f"{date}: label_override/tags (هجرة 014)")
    return problems


# ---------- DIFF ----------

def run_diff(ledger: Ledger, state: dict[str, Any] | None = None) -> dict[str, Any]:
    """تقرير فرق لكل يوم موجود في الهدف من غير علامة استيراد، وقالب الموافقات."""
    built = build_dataset(ledger)
    target = load_target_days(ledger.data_dir)
    out_dir = ledger.root / "reports" / f"{ledger.batch}-replace-diff"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for date, proposed in sorted(built["days"].items()):
        current = target.get(date)
        if current is None or current.get("import"):
            continue
        result = compare_day(current, proposed)
        atomic_write_bytes(out_dir / f"{date}.md", _diff_markdown(date, current, proposed, result).encode("utf-8"))
        rows.append({"date": date, "system_rows": result["rows"]["system"], "import_rows": result["rows"]["import"],
                     "rows_present": result["match"]["rows_present"], "fields": result["match"]["fields"],
                     "states": result["match"]["states"], "missing": len(result["missing"]),
                     "extra": len(result["extra"]), "field_diffs": len(result["field_diffs"]),
                     "state_diffs": len(result["state_diffs"])})
    _write_csv(out_dir / "summary.csv", list(rows[0]) if rows else ["date"], rows)
    path = ledger.root / "decisions" / "replace.csv"
    prior = {row["date"]: row for row in _read_csv(path)}
    _write_csv(path, REPLACE_FIELDS, [{"date": row["date"], "approve": prior.get(row["date"], {}).get("approve", ""),
                                       "note": prior.get(row["date"], {}).get("note", "")} for row in rows])
    return {"days": len(rows), "folder": str(out_dir)}


def _diff_markdown(date: str, current: dict[str, Any], proposed: dict[str, Any], result: dict[str, Any]) -> str:
    lines = [f"# {date} — النظام مقابل الاستيراد", "",
             f"- الصفوف: النظام {result['rows']['system']}، الاستيراد {result['rows']['import']}؛ "
             f"الموجود في الاستيراد {result['match']['rows_present']}%، الحقول {result['match']['fields']}%، "
             f"حالات الضباط {result['match']['states']}%.",
             f"- أقسام النظام: {' ← '.join(result['sections']['system'])}",
             f"- أقسام الاستيراد: {' ← '.join(result['sections']['import'])}", ""]
    if result["missing"]:
        lines += ["## صفوف في النظام بس (هتتشال لو اليوم اتستبدل)", ""] + [f"- {key}" for key in result["missing"]] + [""]
    if result["extra"]:
        lines += ["## صفوف في الاستيراد بس", ""] + [f"- {key}" for key in result["extra"]] + [""]
    if result["field_diffs"]:
        lines += ["## حقول مختلفة", "", "| الصف | الحقل | النظام | الاستيراد |", "|---|---|---|---|"]
        lines += [f"| {item['key']} | {item['field']} | {_cell(item['system'])} | {_cell(item['import'])} |"
                  for item in result["field_diffs"]] + [""]
    if result["state_diffs"]:
        lines += ["## حالات الضباط", "", "| الضابط | الحقل | النظام | الاستيراد |", "|---|---|---|---|"]
        lines += [f"| {item['key']} | {item['field']} | {_cell(item['system'])} | {_cell(item['import'])} |"
                  for item in result["state_diffs"]] + [""]
    for key in ("afraad_basic", "counts"):
        if (current.get(key) or None) != (proposed.get(key) or None):
            lines.append(f"- «{key}»: {'موجود' if current.get(key) else 'فاضي'} في النظام ← "
                         f"{'موجود' if proposed.get(key) else 'فاضي'} في الاستيراد")
    return "\n".join(lines) + "\n"


def _cell(value: Any) -> str:
    return str(value).replace("|", "/").replace("\n", " ")[:80]


# ---------- STORE ----------

def _store_record_path(ledger: Ledger) -> Path:
    return ledger.root / "batches" / f"{ledger.batch}-store.json"


def run_store(ledger: Ledger, state: dict[str, Any], *, write: bool = False, replace_existing: bool = False,
              resume: bool = False) -> dict[str, Any]:
    if Path(store.DATA_DIR).resolve() != ledger.data_dir.resolve():
        raise StoreRefused(f"store.DATA_DIR ({store.DATA_DIR}) غير مجلد الدفعة ({ledger.data_dir}) — "
                           "عيّن PERSONNEL_DATA_DIR لنفس المجلد")
    verify_state = (state.get("stages") or {}).get("verify") or {}
    if verify_state.get("status") != "complete":
        raise StoreRefused("لازم verify يكتمل للدفعة الأول")
    if write and resume:
        # A recovered store journal may already have applied the intended files;
        # continue far enough to write the importer completion record.
        store.recover_journal()
    planned = plan(ledger, replace_existing=replace_existing)
    actions = planned["plan"]
    write_dates = {date for date, (action, _) in actions.items()
                   if action in {"write", "update", "replace"}}
    problems = check_migrations(ledger.data_dir, write_dates)
    if problems:
        raise StoreRefused("هجرات 013/014 لسه ما اتطبقتش على الهدف: " + "؛ ".join(problems[:5]))
    skip = {date for date, (action, _) in actions.items() if action == "skip"}
    counts: dict[str, int] = {}
    for action, _ in actions.values():
        counts[action] = counts.get(action, 0) + 1
    if write:
        _lock()
    data = store.load_data(store.ALL_DAYS)       # الاستيراد بيبني الأرشيف كله
    built = build_dataset(ledger, skip=skip, data=data)
    core, days = store.split(data)
    changed = _changed_files(ledger.data_dir, core, days)
    source_docs = _board_source_docs(ledger, state, write_dates, built["days"])
    for name, source in source_docs.items():
        target = ledger.data_dir / name
        if _sha(target) != _sha(source):
            changed.append(name)
    report = {"batch": ledger.batch, "at": datetime.now().isoformat(timespec="seconds"), "write": write,
              "plan": counts, "files_to_write": len(changed), "applied": built["applied"]["stats"],
              "skipped": {date: reason for date, (action, reason) in actions.items() if action == "skip"}}
    _write_plan(ledger, actions, changed, report)
    if not write or (not changed and not resume):
        if write:
            report["result"] = "لا تغيير — الدفعة مكتوبة بالفعل"
        ledger.mark_stage(state, "store", "complete" if write else "dry-run",
                          {"plan": counts, "files_to_write": len(changed)})
        return report
    # سطر change_log بيتضاف لـcore.json مع أي كتابة، فهو دايمًا من الملفات الملموسة
    if "core.json" not in changed:
        changed.insert(0, "core.json")
    preimage = ledger.root / "preimage" / ledger.batch
    # --resume بعد وقوع: نسخ الأصل الأولى بتفضل (_capture_preimage ما بيكتبش فوقها)
    _capture_preimage(ledger, preimage, changed + ["import/id_map.json"])
    snapshot = store.snapshot_now()
    # id_map قبل البيانات: لو الكتابة وقفت في النص، إعادة التشغيل بتدي نفس المعرّفات
    atomic_write_json(ledger.root / "id_map.json", built["id_map"])
    written_days = sum(1 for action, _ in actions.values() if action in {"write", "update", "replace"})
    changes.record(data, "import", ledger.batch, "batch",
                   text=f"استيراد الأرشيف ({ledger.batch}): {written_days} يوم، "
                        f"{built['applied']['stats']['officers_created']} ضابط و"
                        f"{built['applied']['stats']['personnel_created']} فرد جديد، "
                        f"{built['applied']['stats']['leaves_added']} راحة",
                   after={"plan": counts, "applied": built["applied"]["stats"]})
    store.save_data(data)
    for name, source in source_docs.items():
        atomic_write_bytes(ledger.data_dir / name, source.read_bytes())
    files = [{"path": name, "sha256": _sha(ledger.data_dir / name)} for name in changed]
    record = {"batch": ledger.batch, "at": report["at"], "snapshot": str(snapshot) if snapshot else "",
              "preimage": str(preimage), "written": files, "plan": counts,
              "applied": built["applied"]["stats"], "status": "complete", "version": VERSION}
    atomic_write_json(_store_record_path(ledger), record)
    atomic_write_json(ledger.root / "review" / f"{ledger.batch}-store-review.json", built["applied"]["review"])
    report["result"] = f"اتكتب {len(files)} ملف"
    ledger.mark_stage(state, "store", "complete", {"plan": counts, "files_written": len(files)})
    return report


def _changed_files(data_dir: Path, core: dict[str, Any], days: dict[str, dict[str, Any]]) -> list[str]:
    """أسماء الملفات (نسبية لمجلد البيانات) اللي محتواها هيتغيّر — نفس قرار store._write."""
    out = []
    on_disk = _load(data_dir / "core.json")
    if {**core, "schema": store.SCHEMA_VERSION} != on_disk:
        out.append("core.json")
    for date, blob in sorted(days.items()):
        path = store.day_path(date)
        if _load(path) != blob:
            out.append(str(path.relative_to(data_dir)))
    return out


def _board_source_docs(ledger: Ledger, state: dict[str, Any], dates: set[str],
                       days: dict[str, dict[str, Any]]) -> dict[str, Path]:
    """Resolve verified board DOCX sources into stable, portable data paths.

    Source paths recorded by transform are relative to the archive root.  The
    containment check prevents a malformed manifest from copying files from
    outside that explicitly selected archive.
    """
    raw_root = ((state.get("params") or {}).get("archive") or "").strip()
    if not raw_root:
        return {}
    archive = Path(raw_root).resolve()
    result: dict[str, Path] = {}
    for date in sorted(dates):
        sources = ((days.get(date) or {}).get("import") or {}).get("sources") or []
        board = next((item for item in sources if item.get("type") == "board" and item.get("path")), None)
        if not board:
            continue
        source = (archive / board["path"]).resolve()
        try:
            source.relative_to(archive)
        except ValueError:
            continue
        if source.is_file() and source.suffix.lower() == ".docx":
            result[f"source_docs/board/{date}.docx"] = source
    return result


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _capture_preimage(ledger: Ledger, folder: Path, names: list[str]) -> None:
    """النسخة الأولى بس هي اللي بتتحفظ — إعادة التشغيل بعد وقوع ما بتكتبش فوق الأصل."""
    manifest_path = folder / "manifest.json"
    manifest = _load(manifest_path)
    for name in names:
        if name in manifest:
            continue
        source = ledger.data_dir / name
        if source.exists():
            target = folder / "files" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            manifest[name] = {"existed": True, "sha256": _sha(source)}
        else:
            manifest[name] = {"existed": False, "sha256": "absent"}
    folder.mkdir(parents=True, exist_ok=True)
    atomic_write_json(manifest_path, manifest)


def _write_plan(ledger: Ledger, actions: dict[str, tuple[str, str]], changed: list[str], report: dict[str, Any]) -> None:
    lines = [f"# خطة STORE — {ledger.batch}", "", f"- كتابة فعلية: {'نعم' if report['write'] else 'لا (عرض بس)'}",
             f"- الأيام: " + "، ".join(f"{key} {value}" for key, value in sorted(report["plan"].items())),
             f"- ملفات هتتغيّر: {len(changed)}", "",
             "## البيانات الأساسية", ""] + [f"- {key}: {value}" for key, value in report["applied"].items()]
    reasons: dict[str, int] = {}
    for action, reason in actions.values():
        if action == "skip":
            reasons[reason] = reasons.get(reason, 0) + 1
    lines += ["", "## أيام متسابة", ""] + [f"- {reason}: {count}" for reason, count in sorted(reasons.items())]
    atomic_write_bytes(ledger.report_path("store-plan.md"), ("\n".join(lines) + "\n").encode("utf-8"))


# ---------- ROLLBACK ----------

def run_rollback(ledger: Ledger, state: dict[str, Any] | None = None, *, write: bool = False) -> dict[str, Any]:
    record = _load(_store_record_path(ledger))
    if record.get("status") != "complete":
        raise StoreRefused(f"مفيش تخزين مكتمل للدفعة {ledger.batch}")
    folder = Path(record["preimage"])
    manifest = _load(folder / "manifest.json")
    touched = set(manifest)
    for other in sorted((ledger.root / "batches").glob("*-store.json")):
        later = _load(other)
        if later.get("batch") != ledger.batch and later.get("status") == "complete" and later.get("at", "") > record["at"]:
            overlap = touched & set(_load(Path(later["preimage"]) / "manifest.json"))
            if overlap:
                raise StoreRefused(f"الدفعة {later['batch']} لمست نفس الملفات بعدها — ارجعها الأول")
    plan_rows = [{"path": name, "restore": "حذف" if not info["existed"] else "استرجاع", "sha256": info["sha256"]}
                 for name, info in sorted(manifest.items())]
    if not write:
        return {"files": len(plan_rows), "write": False}
    if Path(store.DATA_DIR).resolve() != ledger.data_dir.resolve():
        raise StoreRefused("عيّن PERSONNEL_DATA_DIR لنفس مجلد الدفعة")
    _lock()
    mismatches = []
    for name, info in sorted(manifest.items()):
        path = ledger.data_dir / name
        if info["existed"]:
            source = folder / "files" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".rollback")
            shutil.copy2(source, tmp)
            tmp.replace(path)
        else:
            path.unlink(missing_ok=True)
        if _sha(path) != info["sha256"]:
            mismatches.append(name)
    store._cache.clear()
    record.update({"status": "rolled_back", "rolled_back_at": datetime.now().isoformat(timespec="seconds"),
                   "rollback_mismatches": mismatches})
    atomic_write_json(_store_record_path(ledger), record)
    if state is not None:
        ledger.mark_stage(state, "store", "rolled_back", {"files": len(plan_rows), "mismatches": mismatches})
    return {"files": len(plan_rows), "write": True, "mismatches": mismatches}


# ---------- REPORT ----------

def run_report(ledger: Ledger, state: dict[str, Any] | None = None) -> Path:
    def report(name: str) -> dict[str, Any]:
        return _load(ledger.report_path(name))
    transform, verify = report("transform.json"), report("verify.json")
    stored = _load(_store_record_path(ledger))
    review = _load(ledger.root / "review" / f"{ledger.batch}-store-review.json") or []
    lines = [f"# تقرير الدفعة {ledger.batch}", ""]
    stages = (state or {}).get("stages") or {}
    lines += ["## المراحل", "", "| المرحلة | الحالة |", "|---|---|"]
    lines += [f"| {name} | {info.get('status', '')} |" for name, info in stages.items()]
    lines += ["", "## TRANSFORM", ""] + [f"- {key}: {value}" for key, value in transform.items() if key != "review"]
    lines += [f"- مراجعة {key}: {value}" for key, value in (transform.get("review") or {}).items()]
    lines += ["", "## VERIFY", "", f"- أيام: {verify.get('days')}، متوسط الدرجة {verify.get('mean_score')}، "
              f"معزول {verify.get('quarantined')} (الحد {verify.get('threshold')})",
              "- التفاصيل: reports/" + f"{ledger.batch}-verify.md"]
    agreement = verify.get("summary_agreement") or {}
    for era, cells in sorted(agreement.items()):
        lines.append(f"- جدول الإجمالي ({era}): " + "، ".join(
            f"{key} {ok}/{total}" for key, (ok, total) in sorted(cells.items())))
    lines += ["", "## STORE", ""]
    if stored:
        lines += [f"- الحالة: {stored.get('status')}، الوقت {stored.get('at')}",
                  f"- الخطة: {stored.get('plan')}", f"- ملفات مكتوبة: {len(stored.get('written') or [])}",
                  f"- نسخة احتياطية: {stored.get('snapshot')}", f"- نسخ الأصل: {stored.get('preimage')}"]
    else:
        lines.append("- لسه ما اتكتبش (شوف reports/" + f"{ledger.batch}-store-plan.md)")
    kinds: dict[str, int] = {}
    for item in review:
        kinds[item.get("type", "")] = kinds.get(item.get("type", ""), 0) + 1
    lines += ["", "## طوابير المراجعة", ""] + [f"- {key}: {value}" for key, value in sorted(kinds.items())]
    lines += ["", "- قرارات الهويات: decisions/officers.csv و personnel.csv",
              "- قرارات المرادفات والأحداث: decisions/aliases.csv و events.csv",
              f"- استبدال أيام النظام: decisions/replace.csv + reports/{ledger.batch}-replace-diff/"]
    path = ledger.report_path("report.md")
    atomic_write_bytes(path, ("\n".join(lines) + "\n").encode("utf-8"))
    return path


__all__ = ["StoreRefused", "check_migrations", "plan", "run_diff", "run_report", "run_rollback", "run_store"]
