"""استيراد يوم واحد من الأرشيف ملوش بيانات مخزّنة، بنفس مراحل المستورد التاريخي.

الحالة اللي اتعملت عشانها: 2026-10-22 ليه لوحة وروستر في الأرشيف ومفيش ولا ملف
بيانات في `data/days`. تشغيل `python -m importer run` مباشرة على `data/` مرفوض
(ومحتاج ledger كبير 988MB)، فالمرحلة دي بتشغّل نفس المراحل (discover → … → verify)
جوه **مجلد مؤقت** فيه نسخة `core.json` + الأيام وملفات اليوم المطلوب بس، وبعدين
بتطبّق ناتج الـtransform على `data` في الذاكرة بنفس `verify.build_dataset` (اللي
بيستخدمه STORE) — والكتابة على القرص مسؤولية الهجرة.

ملاحظات تصميمية:
* ملفات اليوم بس بتتنسخ للمجلد المؤقت: ملف «افراد/حملة/أعداد» اللي اسمه تاريخ يوم تاني
  (زي `21-10-2026 افراد.docx` الموجود في فولدر 22) ما بيتحسبش لليوم ده.
* بوابة preview البنيوية (`importer/preview.py`) لو رفضت اليوم لسبب واحد معروف وقابل
  للإصلاح (صف «قوة» لوحده اتحوّل لقسم) بنصلحه ونسجّله في `unresolved`؛ أي سبب تاني =
  اليوم مابيتستوردش.
* لو الاستيراد هيعمل ضباط/أفراد جداد بنرفضه (محتاج قرار هوية).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from backend import store
from backend.constants import SECTION_OCCASIONAL

from .aliases import VERSION as ALIASES_VERSION
from .aliases import run_aliases
from .archive_gaps import header_day
from .discover import VERSION as DISCOVER_VERSION
from .discover import run_discover
from .archive_gaps import _section_of
from .extract import VERSION as EXTRACT_VERSION
from .extract import run_extract
from .ledger import Ledger
from .normalize import VERSION as NORMALIZE_VERSION
from .normalize import run_normalize
from .preview import VERSION as PREVIEW_VERSION
from .preview import _strength_only, run_preview
from .resolve import VERSION as RESOLVE_VERSION
from .resolve import run_resolve
from .textnorm import dates_in_text
from .transform import PROTECTED
from .transform import VERSION as TRANSFORM_VERSION
from .transform import run_transform
from .validate import VERSION as VALIDATE_VERSION
from .validate import run_validate
from .verify import DEFAULT_THRESHOLD
from .verify import VERSION as VERIFY_VERSION
from .verify import build_dataset, run_verify, transformed_days

REPAIRABLE = {"strength_used_as_service"}
DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def stored_day_keys(data: dict[str, Any], day: str) -> list[str]:
    """مفاتيح اليوم اللي فيها بيانات فعلًا (فاضية = اليوم مالوش ولا ملف)."""
    return [key for key in store.DAY_SECTIONS if (data.get(key) or {}).get(day)]


def day_files(archive_root: Path, day: str) -> list[Path]:
    """ملفات فولدر اليوم اللي تاريخها المطبوع هو اليوم ده بالظبط (من غير ملفات اليوم اللي قبله)."""
    year = dt.date.fromisoformat(day)
    folder = archive_root / str(year.month) / str(year.day)
    if not folder.is_dir():
        return []
    chosen = []
    for path in sorted(folder.iterdir()):
        name = path.name.translate(DIGITS)
        if not path.is_file() or name.startswith("~") or path.suffix.lower() not in {".docx", ".xlsx"}:
            continue
        stem_day = None
        if re.fullmatch(r"\d+\.docx", name):                      # اللوحة التفصيلية
            stem_day = year.replace(day=int(path.stem)) if int(path.stem) == year.day else None
        elif re.fullmatch(r"\d+\.\.docx", name):                  # يومية الانتظام: اليوم من العنوان
            stem_day = year if header_day(path) == day else None
        elif "يومية الحملة" in name or "ارتكازات" in name or "خط تشكيل" in name:
            stem_day = None                                       # خارج نطاق المستورد التاريخي
        else:
            found = dates_in_text(name)
            if found and found[0] == year and ("افراد" in name or "اعداد الخدمات" in name
                                               or re.fullmatch(r"\d+-\d+-\d{4}\.docx", name)):
                stem_day = found[0]
        if stem_day is not None:
            chosen.append(path)
    return chosen


def missing_days(data: dict[str, Any], archive_root: Path, start: str, end: str | None) -> list[str]:
    """أيام ليها لوحة تفصيلية في الأرشيف ومفيش ليها أي بيانات مخزّنة."""
    from .archive_gaps import discover_boards
    return [day for day in discover_boards(archive_root, start, end) if not stored_day_keys(data, day)]


def _write_scratch(data: dict[str, Any], scratch: Path, archive_root: Path, archive_copy: Path,
                   day: str, files: list[Path], decisions: Path | None) -> None:
    core, days = store.split(data)
    core = {**core, "schema": store.SCHEMA_VERSION}
    (scratch / "core.json").write_text(json.dumps(core, ensure_ascii=False), encoding="utf-8")
    for date, blob in days.items():
        path = scratch / "days" / date[:4] / date[5:7] / f"{date}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(blob, ensure_ascii=False), encoding="utf-8")
    ledger_root = scratch / "import"
    (ledger_root / "decisions").mkdir(parents=True, exist_ok=True)
    if decisions and decisions.is_dir():
        for item in decisions.iterdir():
            if item.is_file():
                shutil.copy2(item, ledger_root / "decisions" / item.name)
        id_map = decisions.parent / "id_map.json"
        if id_map.is_file():
            shutil.copy2(id_map, ledger_root / "id_map.json")
    target = archive_copy / archive_root.name / str(int(day[5:7])) / str(int(day[8:]))
    target.mkdir(parents=True, exist_ok=True)
    for path in files:
        shutil.copy2(path, target / path.name)


def run_stages(archive: Path, scratch: Path, day: str, batch: str) -> tuple[Ledger, dict[str, Any]]:
    """نفس تسلسل `python -m importer run` لحد verify (من غير audit/diff/store)."""
    ledger = Ledger(scratch, batch)
    date = dt.date.fromisoformat(day)
    state = ledger.initialise(
        {"archive": str(archive), "data_dir": str(scratch), "from": day, "to": day, "batch": batch,
         "write": False, "resume": False},
        {"discover": DISCOVER_VERSION, "extract": EXTRACT_VERSION, "validate": VALIDATE_VERSION,
         "normalize": NORMALIZE_VERSION, "resolve": RESOLVE_VERSION, "aliases": ALIASES_VERSION,
         "transform": TRANSFORM_VERSION, "preview": PREVIEW_VERSION, "verify": VERIFY_VERSION})
    run_discover(archive, ledger, date, date, state)
    run_extract(archive, ledger, date, date, state)
    run_validate(ledger, state, date, date)
    run_normalize(ledger, state, date, date)
    run_resolve(ledger, state, date, date)
    run_aliases(ledger, state, date, date)
    run_transform(ledger, state, date, date)
    run_preview(ledger, state)
    run_verify(ledger, state, threshold=DEFAULT_THRESHOLD)
    return ledger, state


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def strength_label_sections(records: list[dict[str, Any]]) -> dict[str, str]:
    """صفوف «القوة» اللي لوحدها (فرد + وحدة) -> القسم اللي كانت تحت عنوانه في Word.

    القسم بيتحدد من آخر عنوان قسم قبلها في نفس نصف الشبكة (مش من ترتيب الصفوف المحوّلة)."""
    current: dict[int, str] = {}
    header = next((r for r in records if r.get("record_type") == "header"), {})
    for half, label in enumerate(header.get("half_labels") or []):
        current[half] = _section_of(label) or ""
    found: dict[str, str] = {}
    for record in records:
        if record.get("record_type") not in {"board_row", "board_label"}:
            continue
        half, label = int(record.get("half") or 0), " ".join(str(record.get("label") or "").split())
        heading = _section_of(label)
        if heading and not str(record.get("manning") or "").strip():
            current[half] = heading
        elif _strength_only(label):
            found[label] = current.get(half, "")
    return found


def repair_strength_sections(blob: dict[str, Any], sections: dict[str, str]) -> list[str]:
    """صف «قوة» لوحده اتحوّل لقسم: نرجّع خدماته لقسمها الأصلي ونسجّله (مانخمّنش القوة).

    القسم الأصلي لازم يكون «الخدمات الطارئة»؛ غير كده ValueError واليوم مابيتستوردش."""
    notes: list[str] = []
    for row in blob.get("assignments") or []:
        label = row.get("section") or ""
        if not _strength_only(label):
            continue
        if sections.get(label) != "emergency":
            raise ValueError(f"صف القوة «{label}» مش تحت عنوان الخدمات الطارئة ({sections.get(label) or 'غير معروف'})")
        notes.append(f"صف القوة «{label}» منفصل عن خدمته في Word — «{row['name']}» اتحطت في الخدمات الطارئة "
                     "ومانسبتش القوة لخدمة بالتخمين")
        row["section"] = SECTION_OCCASIONAL
    return notes


def import_day(data: dict[str, Any], day: str, archive_root: Path, batch: str,
               decisions: Path | None = None, apply: bool = True) -> dict[str, Any]:
    """يستورد `day` في `data` (في الذاكرة). -> {day, status: import|skip, reason, stats, sources, unresolved,
    source_doc}. ما بيكتبش أي حاجة على القرص."""
    result: dict[str, Any] = {"day": day, "status": "skip", "reason": "", "stats": {}, "sources": [],
                              "unresolved": [], "source_doc": None}
    if day in PROTECTED:
        result["reason"] = "يوم مرجعي محمي"
        return result
    if stored_day_keys(data, day):
        result["reason"] = "اليوم عنده بيانات مخزّنة بالفعل"
        return result
    files = day_files(archive_root, day)
    board = next((p for p in files if re.fullmatch(r"\d+\.docx", p.name)), None)
    if board is None:
        result["reason"] = "مفيش لوحة تفصيلية للتاريخ ده في الأرشيف"
        return result
    result["sources"] = [str(p.relative_to(archive_root.parent)) for p in files]
    with tempfile.TemporaryDirectory(prefix="gaps-day-") as tmp:
        tmp_path = Path(tmp)
        scratch, archive = tmp_path / "data", tmp_path / "archive"
        scratch.mkdir()
        _write_scratch(data, scratch, archive_root, archive, day, files, decisions)
        ledger, _state = run_stages(archive, scratch, day, batch)
        days = transformed_days(ledger)
        if day not in days:
            result["reason"] = "الـtransform ما طلّعش اليوم ده"
            return result
        blob = deepcopy(days[day])
        errors = (_read(ledger.root / "quarantine" / f"{batch}-preview.json").get("days") or {}).get(day) or []
        blocking = [code for code in errors if code not in REPAIRABLE]
        if blocking:
            result["reason"] = "اتعزل في preview: " + "، ".join(blocking)
            return result
        if day in (_read(ledger.root / "quarantine" / f"{batch}-verify.json").get("days") or {}):
            result["reason"] = "اتعزل في verify (درجة تحت الحد)"
            return result
        try:
            result["unresolved"] += repair_strength_sections(
                blob, strength_label_sections([r for r in _read_jsonl(ledger.staging_path("extract"))
                                               if r.get("date") == day and r.get("role") == "board"]))
        except ValueError as exc:
            result["reason"] = str(exc)
            return result
        for item in _read_jsonl(ledger.staging_path("transform-review")):
            if item.get("date") == day:
                result["unresolved"].append(f"طابور المراجعة: {item.get('type')} — {item.get('raw', '')}")
        work = deepcopy(data)
        built = build_dataset(ledger, days={day: blob}, skip=set(), data=work)
        stats = built["applied"]["stats"]
        result["stats"] = {key: value for key, value in stats.items() if value}
        result["stats"]["assignments"] = len(blob.get("assignments") or [])
        result["stats"]["officer_states"] = len(blob.get("officer_states") or {})
        if stats.get("officers_created") or stats.get("personnel_created"):
            result["reason"] = "الاستيراد هيعمل ضباط/أفراد جداد — محتاج قرار هوية"
            return result
        result["unresolved"] += [f"مراجعة: {item}" if isinstance(item, str) else
                                 f"مراجعة: {json.dumps(item, ensure_ascii=False)}" for item in built["applied"]["review"]]
        result["status"] = "import"
        result["reason"] = "يوم من غير بيانات مخزّنة — اتبنى من اللوحة + الروستر"
        result["source_doc"] = (str(board), f"board/{day}.docx")
        if apply:
            data.clear()
            data.update(work)
            # علامة المصدر باسم الدفعة الجديدة (بدل اسم الدفعة المؤقتة)
            data.setdefault("day_import", {}).setdefault(day, {})["batch"] = batch
    return result


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
