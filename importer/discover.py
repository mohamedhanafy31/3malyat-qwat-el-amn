"""مرحلة جرد الأرشيف واختيار الوثائق المرجعية لكل يوم."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

from .ledger import Ledger, atomic_write_text, atomic_write_jsonl
from .textnorm import clean_text, dates_in_text, norm, parse_date, weekday_matches


VERSION = "1"
WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MONTH_RE = re.compile(r"^(?:شهر\s*)?(\d{1,2})\s*$")
DAY_NUMBER_RE = re.compile(r"^\s*(\d{1,2})(?:\s|$|-)" )
SUPPORTED = {".docx", ".xlsx", ".pdf", ".doc", ".xls", ".jpg", ".jpeg", ".png", ".txt"}
ROLES = (
    "roster", "old_officer_sheet", "board", "afraad", "duty_list", "counts",
    "counts_leader", "command_order", "match", "deployment", "ref_officers",
    "ref_personnel", "out_of_scope", "other",
)
AUTHORITATIVE_ROLES = tuple(role for role in ROLES if role not in {"out_of_scope", "other"})


@dataclass(frozen=True)
class DocumentContent:
    paragraphs: tuple[str, ...] = ()
    tables: tuple[tuple[tuple[str, ...], ...], ...] = ()
    body_hash: str | None = None
    error: str | None = None

    @property
    def paragraph_text(self) -> str:
        return " ".join(self.paragraphs)

    @property
    def table_text(self) -> str:
        return " ".join(cell for table in self.tables for row in table for cell in row)


def is_junk(path: Path) -> tuple[bool, str | None]:
    name = path.name
    low = name.lower()
    if name.startswith("~"):
        return True, "temporary"
    if low in {"desktop.ini", "thumbs.db"} or low.endswith((".tmp", ".lnk", ".rar", ".zip")):
        return True, "junk-extension"
    if low.endswith(".txt") and path.is_file() and path.stat().st_size == 0:
        return True, "empty-text"
    return False, None


def sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _element_text(element: ET.Element) -> str:
    return clean_text("".join(node.text or "" for node in element.iter(WORD_NS + "t")))


def read_docx(path: Path, *, max_paragraphs: int = 20, max_tables: int = 5,
              max_rows: int = 12, max_cells: int = 12) -> DocumentContent:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
        root = ET.fromstring(xml)
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        return DocumentContent(error=f"{type(exc).__name__}: {exc}")
    body = root.find(WORD_NS + "body")
    paragraphs: list[str] = []
    tables: list[tuple[tuple[str, ...], ...]] = []
    if body is not None:
        for element in body:
            if element.tag == WORD_NS + "p" and len(paragraphs) < max_paragraphs:
                value = _element_text(element)
                if value:
                    paragraphs.append(value)
            elif element.tag == WORD_NS + "tbl" and len(tables) < max_tables:
                rows: list[tuple[str, ...]] = []
                for row in element.findall(WORD_NS + "tr")[:max_rows]:
                    cells = tuple(_element_text(cell) for cell in row.findall(WORD_NS + "tc")[:max_cells])
                    rows.append(cells)
                tables.append(tuple(rows))
    return DocumentContent(tuple(paragraphs), tuple(tables), hashlib.sha1(xml).hexdigest())


def read_xlsx(path: Path) -> DocumentContent:
    try:
        from openpyxl import load_workbook
        workbook = load_workbook(path, read_only=True, data_only=True)
        sheet = workbook[workbook.sheetnames[0]]
        rows = []
        for row in sheet.iter_rows(min_row=1, max_row=12, max_col=12, values_only=True):
            rows.append(tuple(clean_text(str(value)) if value is not None else "" for value in row))
        workbook.close()
        return DocumentContent(tables=(tuple(rows),))
    except Exception as exc:  # openpyxl يجمع أخطاء صيغ الملفات القديمة هنا.
        return DocumentContent(error=f"{type(exc).__name__}: {exc}")


def _has(text: str, *words: str) -> bool:
    simplified = norm(text).replace(" ", "")
    return all(norm(word).replace(" ", "") in simplified for word in words)


def detect_roster_layout(content: DocumentContent) -> str | None:
    table_norm = norm(content.table_text)
    paragraph_norm = norm(content.paragraph_text)
    roster_heading = "يوميه تشغيل الضباط" in paragraph_norm
    roster_columns = (
        _has(content.table_text, "الرتبة", "الاسم") and
        (
            ("التشغيل" in table_norm and
             ("العمل المسند" in table_norm or "رقم التلفون" in table_norm or roster_heading)) or
            (roster_heading and "العمل المسند" in table_norm)
        )
    )
    if not roster_columns:
        return None
    first_rows = [cell for table in content.tables[:2] for row in table[:3] for cell in row]
    header = norm(" ".join(first_rows))
    if any(word in header for word in ("الحاله", "رقم التلفون", "العمل المسند مجددا", "ملاحظات")):
        return "roster_temporary_variant"
    has_seniority = "الاقدميه" in header or "الاقدميه" in norm(content.table_text)
    has_rest = "الراحات" in header
    if has_rest:
        return "roster_v4_rest"
    if has_seniority:
        # اختلاف الموضع لا يظهر بأمان بعد دمج الخلايا، لذلك نسجل التوقيع لا رقمًا زائفًا.
        return "roster_v2_seniority"
    if "0" in header and "العمل المسند" in header:
        return "roster_v1_corrupt_header"
    return "roster_v1_basic"


def classify_document(name: str, content: DocumentContent | None = None,
                      extension: str | None = None) -> tuple[str, str | None, str | None]:
    """إرجاع (الدور، السبب، نسخة التخطيط)؛ المحتوى يسبق الاسم دائمًا."""
    content = content or DocumentContent()
    ext = (extension or Path(name).suffix).lower()
    display = clean_text(Path(name).stem.lstrip("."))
    nname = norm(display)
    paragraphs = content.paragraph_text
    tables = content.table_text
    all_text = f"{paragraphs} {tables}"

    if ext in {".pdf", ".jpg", ".jpeg", ".png"}:
        return "other", "non-source-format", None
    # هذه الأسماء ليست تخمينًا عامًا: التقرير يحددها كمصادر أو نسخ مستبعدة
    # حتى حين تشبه جداولها لوحة التشغيل.
    if nname.startswith(("ارقام الضباط", "كشف اقدميه", "جدول ارقام", "جدول اراقام",
                         "بيان الهيكلي", "كشف باسماء و ارقام", "كشف بخطه استدعاء")):
        return "ref_officers", "known-reference-name", None
    if nname.startswith(("ارقام الافراد", "داتا افراد", "يوميه الافراد بالارقام")):
        return "ref_personnel", "known-reference-name", None
    named_out_patterns = (
        (("يوميه الحمله", "حمله", "المركبات", "يوميه السيارات"), "vehicles-or-campaign"),
        (("خط تشكيل", "خطج تسكيل"), "formation"),
        (("يوميه الاهداف",), "stale-target-sheet"),
        (("كفر", "cover", "ملصقات"), "cover-or-printing"),
        (("يوميه وايل", "يوميه شادي", "يويمه وايل", "للحكمدار", "حكمدار"), "named-or-hakmdar-copy"),
        (("يوميه تعيينات",), "assignments-copy"),
        (("تفريغ امر الخدمه",), "command-order-transcript-copy"),
    )
    for needles, reason in named_out_patterns:
        if any(needle in nname for needle in needles):
            return "out_of_scope", reason, None
    if ext == ".docx" and nname.startswith("امر خدمه يوم"):
        return "command_order", "known-command-order-name", None
    # «يومية القائد» جدول شبيه باللوحة لكنه مصدر عدّ مستقل في التقرير.
    if nname.startswith("يوميه القايد") or _has(paragraphs, "يومية القائد"):
        return "counts_leader", None, None

    layout = detect_roster_layout(content)
    if layout:
        return "roster", None, layout
    if (_has(tables, "الخدمة", "الخدمة الصباحية", "الخدمة الليلية") and
            (_has(tables, "قوام الخدمة") or _has(tables, "التسليح", "الانتظام"))):
        return "afraad", None, None
    if (_has(tables, "الخدمات الأساسية", "الخدمات الطارئة") or
            _has(tables, "خدمات أساسية", "الأهداف") or
            (_has(tables, "الأساسية", "الأهداف", "الطارئة"))):
        return "board", None, None
    if (_has(all_text, "انتظام خدمات", "أمر الخدمة") or
            _has(tables, "قائم للخدمة", "ساعة الانتظام") or
            _has(tables, "الخدمة", "قوامها", "الانتظام")):
        return "duty_list", None, None
    if _has(all_text, "يومية تشغيل السادة الضباط") or _has(all_text, "كشف راحات", "الضباط"):
        return "old_officer_sheet", None, None
    if _has(tables, "الرتبة", "الأقدمية", "الاسم") and any(
            _has(tables, word) for word in ("المسمى الوظيفي", "رقم الهاتف", "التليفون")):
        return "ref_officers", None, None
    if _has(tables, "الدرجة", "الاسم") and any(
            _has(tables, word) for word in ("العنوان", "العمل المسند", "رقم الهاتف")):
        return "ref_personnel", None, None
    if _has(all_text, "يومية القائد"):
        return "counts_leader", None, None
    if _has(all_text, "أعداد الخدمات") or (ext == ".xlsx" and _has(tables, "الخدمة", "العدد")):
        return "counts", None, None
    if (_has(all_text, "خطة انتشار") or "خطه انتشار" in nname or
            "خطه الانتشار" in nname or "الانتشار" == nname):
        return "deployment", None, None
    if any(word in nname or norm(word) in norm(all_text) for word in ("ماتش", "مباراة", "المباره")):
        return "match", None, None
    if (_has(paragraphs, "أمر خدمة") or nname.startswith("امر خدمه")) and not content.tables:
        return "command_order", None, None

    out_patterns = (
        (("يوميه الحمله", "الحمله", "المركبات", "السيارات"), "vehicles-or-campaign"),
        (("خط تشكيل", "التشكيل"), "formation"),
        (("يوميه الاهداف",), "stale-target-sheet"),
        (("كفر", "cover", "ملصقات"), "cover-or-printing"),
        (("يوميه وايل", "يوميه شادي", "للحكمدار", "حكمدار"), "named-or-hakmdar-copy"),
        (("راحات", "النصف شهريه", "الشهريه"), "leave-reference"),
        (("تعيينات",), "assignments-copy"),
    )
    for needles, reason in out_patterns:
        if any(needle in nname for needle in needles):
            return "out_of_scope", reason, None

    # الأسماء المعروفة تظل احتياطًا بعد فشل توقيع المحتوى (مثل ملف Word فارغ).
    if "للمديريه" in nname:
        return "roster", "name-fallback", "unknown"
    if "افراد" in nname and dates_in_text(display):
        return "afraad", "name-fallback", None
    if nname.startswith("اعداد الخدمات"):
        return "counts", "name-fallback", None
    if nname.startswith("يوميه القايد"):
        return "counts_leader", "name-fallback", None
    if nname.startswith(("ارقام الضباط", "كشف اقدميه", "جدول ارقام", "بيان الهيكلي", "كشف باسماء و ارقام")):
        return "ref_officers", "name-fallback", None
    if nname.startswith(("ارقام الافراد", "داتا افراد", "يوميه الافراد بالارقام")):
        return "ref_personnel", "name-fallback", None
    if content.error:
        return "other", f"unreadable-{ext.lstrip('.') or 'file'}", None
    return "other", "no-supported-content-signature", None


def parse_folder_date(year: int, month_name: str, day_name: str) -> dt.date | None:
    explicit = parse_date(day_name)
    if explicit:
        return explicit
    month_match = MONTH_RE.match(clean_text(month_name))
    day_match = DAY_NUMBER_RE.match(clean_text(day_name))
    if not month_match or not day_match:
        return None
    try:
        return dt.date(year, int(month_match.group(1)), int(day_match.group(1)))
    except ValueError:
        return None


def _title_date(content: DocumentContent) -> dt.date | None:
    # العنوان في الفقرات؛ لا نستعمل كل خلايا الجدول كي لا نلتقط تاريخ إجازة داخله.
    for text in content.paragraphs[:8]:
        values = dates_in_text(text)
        if values:
            return values[0]
    for table in content.tables[:1]:
        for row in table[:2]:
            values = dates_in_text(" ".join(row))
            if values:
                return values[0]
    return None


def _file_record(path: Path, archive: Path, scope: str, folder_date: dt.date | None,
                 folder_path: str | None, nested_folders: list[str] | None = None,
                 draft_folder: bool = False) -> dict[str, Any]:
    ext = path.suffix.lower()
    content = read_docx(path) if ext == ".docx" and path.stat().st_size else (
        read_xlsx(path) if ext == ".xlsx" else DocumentContent()
    )
    role, reason, layout = classify_document(path.name, content, ext)
    title_date = _title_date(content)
    filename_date = parse_date(path.name)
    original_filename_date = filename_date
    record_notes: list[str] = []
    if (folder_date and filename_date and filename_date.year != folder_date.year and
            (filename_date.month, filename_date.day) == (folder_date.month, folder_date.day)):
        filename_date = folder_date
        record_notes.append("name year typo")
    title_text = list(content.paragraphs[:3])
    return {
        "record_type": "file",
        "path": path.relative_to(archive).as_posix(),
        "name": path.name,
        "scope": scope,
        "folder_path": folder_path,
        "folder_date": folder_date.isoformat() if folder_date else None,
        "draft_folder": draft_folder,
        "nested_folders": sorted(nested_folders or []),
        "top_level": scope == "day",
        "extension": ext,
        "size": path.stat().st_size,
        "sha1": sha1_file(path),
        "body_sha1": content.body_hash,
        "read_error": content.error,
        "title": title_text,
        "title_date": title_date.isoformat() if title_date else None,
        "title_weekday_matches": weekday_matches(" ".join(title_text), title_date) if title_date else None,
        "filename_date": filename_date.isoformat() if filename_date else None,
        "original_filename_date": original_filename_date.isoformat() if original_filename_date else None,
        "notes": record_notes,
        "role": role,
        "classification_reason": reason,
        "layout_version": layout,
        "chosen_for": [],
        "stale_for": [],
        "evidence": True,
    }


def scan_archive(archive: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    folders: list[dict[str, Any]] = []
    for year_path in sorted((p for p in archive.iterdir() if p.is_dir() and re.fullmatch(r"20\d{2}", p.name)), key=lambda p: p.name):
        year = int(year_path.name)
        for item in sorted(year_path.iterdir(), key=lambda p: p.name):
            if item.is_file():
                junk, _ = is_junk(item)
                if not junk:
                    records.append(_file_record(item, archive, "year-loose", None, None))
                continue
            month_match = MONTH_RE.match(clean_text(item.name))
            if not month_match:
                folders.append({"path": item.relative_to(archive).as_posix(), "kind": "year-reference-folder", "date": None})
                continue
            for child in sorted(item.iterdir(), key=lambda p: p.name):
                if child.is_file():
                    junk, _ = is_junk(child)
                    if not junk:
                        records.append(_file_record(child, archive, "month-loose", None, None))
                    continue
                folder_date = parse_folder_date(year, item.name, child.name)
                month = int(month_match.group(1))
                draft_folder = bool(folder_date and (folder_date.year != year or folder_date.month != month))
                nested = sorted(p.name for p in child.iterdir() if p.is_dir())
                folder_rel = child.relative_to(archive).as_posix()
                folders.append({
                    "path": folder_rel,
                    "kind": "day-folder" if folder_date else "odd-folder",
                    "date": folder_date.isoformat() if folder_date else None,
                    "nested_folders": nested,
                    "copy": "copy" in child.name.lower(),
                    "draft": draft_folder,
                })
                for file_path in sorted((p for p in child.iterdir() if p.is_file()), key=lambda p: p.name):
                    junk, _ = is_junk(file_path)
                    if junk:
                        continue
                    records.append(_file_record(
                        file_path, archive, "day", folder_date, folder_rel, nested, draft_folder
                    ))
    records.sort(key=lambda record: record["path"])
    folders.sort(key=lambda record: record["path"])
    return records, folders


def _as_date(value: str | None) -> dt.date | None:
    return dt.date.fromisoformat(value) if value else None


def _effective_folder_date(record: dict[str, Any], recovered: dict[str, dt.date]) -> dt.date | None:
    return recovered.get(record.get("folder_path")) or _as_date(record.get("folder_date"))


def _document_dates(record: dict[str, Any]) -> list[dt.date]:
    return [value for value in (
        _as_date(record.get("title_date")), _as_date(record.get("filename_date"))
    ) if value is not None]


def _clean_date_match(record: dict[str, Any], day: dt.date) -> bool:
    dates = _document_dates(record)
    return bool(dates) and all(value == day for value in dates)


def _candidate_score(record: dict[str, Any], day: dt.date,
                     recovered: dict[str, dt.date]) -> tuple[Any, ...]:
    exact_title = _as_date(record["title_date"]) == day
    exact_name = _as_date(record["filename_date"]) == day
    exact_folder = _effective_folder_date(record, recovered) == day
    extension_rank = {".docx": 0, ".xlsx": 0, ".doc": 1, ".xls": 1, ".pdf": 2}.get(record["extension"], 3)
    copy = "copy" in record["path"].lower()
    # كل معيار مستقل حتى يظل ترتيب الأولوية كما ورد في التقرير.
    return (
        0 if exact_title else 1,
        0 if exact_name else 1,
        0 if exact_folder else 1,
        0 if record["top_level"] else 1,
        extension_rank,
        1 if copy else 0,
        record["path"],
    )


def _candidate_for_day(record: dict[str, Any], day: dt.date,
                       recovered: dict[str, dt.date]) -> bool:
    folder_date = _effective_folder_date(record, recovered)
    if folder_date == day:
        return True
    if folder_date is None or abs((folder_date - day).days) > 2:
        return False
    # خارج مجلد اليوم لا يكفي القرب: يجب أن تسمّي كل التواريخ الظاهرة اليوم نفسه.
    return _clean_date_match(record, day)


def _covered_dates(folders: list[dict[str, Any]], records: list[dict[str, Any]],
                   start: dt.date, end: dt.date) -> tuple[set[dt.date], dict[str, dt.date]]:
    folder_dates = {
        _as_date(folder["date"]) for folder in folders if folder.get("kind") == "day-folder"
    }
    folder_dates = {day for day in folder_dates if day and start <= day <= end}
    recovered: dict[str, dt.date] = {}
    for folder in folders:
        if not folder.get("copy"):
            continue
        own = _as_date(folder.get("date"))
        if own is None:
            continue
        votes = Counter()
        for record in records:
            if record.get("folder_path") != folder["path"] or record["role"] not in {"roster", "afraad"}:
                continue
            for key in ("title_date", "filename_date"):
                value = _as_date(record.get(key))
                if value and abs((value - own).days) <= 1 and value != own:
                    votes[value] += 1
        if votes:
            winner, count = votes.most_common(1)[0]
            if count >= 2 and start <= winner <= end:
                recovered[folder["path"]] = winner
    return folder_dates, recovered


def select_documents(records: list[dict[str, Any]], folders: list[dict[str, Any]],
                     start: dt.date, end: dt.date) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    folder_dates, recovered = _covered_dates(folders, records, start, end)
    recovered_dates = set(recovered.values())
    covered = folder_dates | recovered_dates
    top_records = [record for record in records if record["scope"] == "day"]
    rows: list[dict[str, Any]] = []
    previous_hash: dict[str, tuple[dt.date, str]] = {}
    for day in sorted(covered):
        row: dict[str, Any] = {"date": day.isoformat(), "chosen": {}, "conflicts": [], "notes": []}
        if day in recovered_dates and day not in folder_dates:
            row["notes"].append("recovered-from-copy-folder")
        for role in AUTHORITATIVE_ROLES:
            candidates = [
                record for record in top_records
                if record["role"] == role and _candidate_for_day(record, day, recovered)
            ]
            if not candidates:
                continue
            non_draft = [record for record in candidates if not record.get("draft_folder")]
            if non_draft:
                candidates = non_draft
            matching = [record for record in candidates if _clean_date_match(record, day)]
            if matching:
                candidates = matching
            candidates.sort(key=lambda record: _candidate_score(record, day, recovered))
            chosen = candidates[0]
            body_hash = chosen.get("body_sha1")
            prior = previous_hash.get(role)
            stale = bool(body_hash and prior and prior == (day - dt.timedelta(days=1), body_hash))
            chosen["chosen_for"].append(day.isoformat())
            if stale:
                chosen["stale_for"].append(day.isoformat())
                chosen["evidence"] = False
            if body_hash:
                previous_hash[role] = (day, body_hash)
            equally_ranked = [candidate["path"] for candidate in candidates[1:]
                              if _candidate_score(candidate, day, recovered)[:-1] ==
                              _candidate_score(chosen, day, recovered)[:-1]]
            if equally_ranked:
                row["conflicts"].append(f"{role}: " + " | ".join(equally_ranked))
            differing_dates = sorted({value.isoformat() for value in _document_dates(chosen) if value != day})
            if differing_dates:
                row["conflicts"].append(
                    f"{role}: chosen own-folder document has a different date ({', '.join(differing_dates)})"
                )
            for note in chosen.get("notes", []):
                row["notes"].append(f"{role}: {note}")
            row["chosen"][role] = {
                "path": chosen["path"],
                "stale": stale,
                "evidence": not stale,
                "layout_version": chosen.get("layout_version"),
                "title_date": chosen.get("title_date"),
                "filename_date": chosen.get("filename_date"),
                "folder_date": chosen.get("folder_date"),
            }
        rows.append(row)
    metrics = {
        "folder_dates": len(folder_dates),
        "covered_dates": len(covered),
        "recovered_dates": sorted(day.isoformat() for day in recovered_dates - folder_dates),
        "missing_dates": [
            (start + dt.timedelta(days=offset)).isoformat()
            for offset in range((end - start).days + 1)
            if start + dt.timedelta(days=offset) not in covered
        ],
    }
    return rows, metrics


def _manifest_csv(rows: list[dict[str, Any]]) -> str:
    fields = ["date"]
    for role in AUTHORITATIVE_ROLES:
        fields.extend((role, f"{role}_stale"))
    fields.extend(("roster_layout", "conflicts", "notes"))
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        flat: dict[str, Any] = {"date": row["date"]}
        for role in AUTHORITATIVE_ROLES:
            chosen = row["chosen"].get(role)
            flat[role] = chosen["path"] if chosen else ""
            flat[f"{role}_stale"] = "STALE" if chosen and chosen["stale"] else ""
        flat["roster_layout"] = row["chosen"].get("roster", {}).get("layout_version") or ""
        flat["conflicts"] = "; ".join(row["conflicts"])
        flat["notes"] = "; ".join(row["notes"])
        writer.writerow(flat)
    return output.getvalue()


def _discover_report(records: list[dict[str, Any]], folders: list[dict[str, Any]],
                     rows: list[dict[str, Any]], metrics: dict[str, Any]) -> str:
    by_year_role: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        for role in row["chosen"]:
            by_year_role[row["date"][:4]][role] += 1
    odd = [folder for folder in folders if folder["kind"] != "day-folder"]
    by_date: dict[str, list[str]] = defaultdict(list)
    for folder in folders:
        if folder.get("date"):
            by_date[folder["date"]].append(folder["path"])
    duplicates = {date: paths for date, paths in by_date.items() if len(paths) > 1}
    unexplained = [record for record in records if record["scope"] == "day" and record["role"] == "other"]
    missing_core = [
        (row["date"], role) for row in rows for role in ("roster", "afraad") if role not in row["chosen"]
    ]
    lines = [
        "# تقرير مرحلة DISCOVER", "",
        "## الملخص", "",
        f"- تواريخ مجلدات مميزة: {metrics['folder_dates']}",
        f"- تواريخ مغطاة بعد الاسترداد: {metrics['covered_dates']}",
        f"- ملفات محتفظ بها: {len(records)}",
        f"- مجلدات يوم: {sum(1 for folder in folders if folder['kind'] == 'day-folder')}",
        f"- تواريخ مستردة من مجلد Copy: {', '.join(metrics['recovered_dates']) or 'لا يوجد'}",
        f"- التواريخ المفقودة: {', '.join(metrics['missing_dates']) or 'لا يوجد'}",
        "", "## المختار حسب السنة والدور", "",
        "| السنة | الدور | العدد |", "|---|---|---:|",
    ]
    for year in sorted(by_year_role):
        for role, count in sorted(by_year_role[year].items()):
            lines.append(f"| {year} | {role} | {count} |")
    lines.extend(["", "## أيام بلا وثيقة أساسية", ""])
    if missing_core:
        lines.extend(f"- {day}: {role}" for day, role in missing_core)
    else:
        lines.append("لا يوجد.")
    lines.extend(["", "## المجلدات المكررة أو غير المعتادة", ""])
    for date, paths in sorted(duplicates.items()):
        lines.append(f"- {date}: {' | '.join(paths)}")
    for folder in odd:
        lines.append(f"- {folder['path']}: {folder['kind']}")
    if not duplicates and not odd:
        lines.append("لا يوجد.")
    lines.extend(["", "## ملفات أخرى غير مصنفة إلى دور استيراد", ""])
    if unexplained:
        for record in unexplained:
            lines.append(f"- `{record['path']}` — {record['classification_reason']}")
    else:
        lines.append("لا يوجد.")
    return "\n".join(lines) + "\n"


def run_discover(archive: Path, ledger: Ledger, start: dt.date, end: dt.date,
                 state: dict[str, Any]) -> dict[str, Any]:
    ledger.mark_stage(state, "discover", "running")
    records, folders = scan_archive(archive)
    rows, metrics = select_documents(records, folders, start, end)
    # سجلات المجلدات مطلوبة لتدقيق العناصر المرجعية والمجلدات المتداخلة.
    staging = [{**folder, "record_type": "folder"} for folder in folders] + records
    staging.sort(key=lambda record: (record.get("path", ""), record["record_type"]))
    atomic_write_jsonl(ledger.staging_path("discover"), staging)
    atomic_write_text(ledger.report_path("manifest.csv"), _manifest_csv(rows))
    atomic_write_text(ledger.report_path("discover.md"), _discover_report(records, folders, rows, metrics))
    checkpoint = {**metrics, "files": len(records), "folders": len(folders)}
    ledger.mark_stage(state, "discover", "complete", checkpoint)
    return checkpoint
