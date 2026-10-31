#!/usr/bin/env python3
"""حل البنود اللي سابتها 022/023 نصًا أو فاضية — dry-run افتراضيًا.

    python3 migrations/025_resolve_unresolved.py
    python3 migrations/025_resolve_unresolved.py --report docs/import-preview-resolve.md
    python3 migrations/025_resolve_unresolved.py --write
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import AlreadyDone, run  # noqa: E402
from importer import archive_gaps, campaign  # noqa: E402
from importer.person_match import resolve_person  # noqa: E402
from importer.normalize import name_compatible, normalize_rank  # noqa: E402
from importer.textnorm import norm_name  # noqa: E402
from backend.people import effective  # noqa: E402
from backend.repo import PeopleRepo  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BATCH = "resolve-025"


def _options():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--archive-root", type=Path, default=ROOT.parent.parent / "2026")
    parser.add_argument("--from", dest="start", default="2026-08-01")
    parser.add_argument("--to", dest="end", default=None)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--write", action="store_true")
    return parser.parse_known_args(sys.argv[1:])[0]


_INHERITED_KEYS = ("lorries", "daily", "posts", "plates")


def _seed_day(data: dict[str, Any], day: str) -> bool:
    """يوم مالوش سجل حملة بيورث سجل آخر يوم قبله. لو هنكتب فيه لازم نبدأ بنسخة من
    الموروث، وإلا السجل الجديد الناقص يقطع التوريث عن الأيام اللي بعده (المركبات تختفي)."""
    days = data.setdefault("day_campaign", {})
    if day in days:
        return False
    previous = max((d for d in days if d < day), default=None)
    seed: dict[str, Any] = {}
    for key in _INHERITED_KEYS:
        value = (days.get(previous) or {}).get(key) if previous else None
        if value is None:
            continue
        value = deepcopy(value)
        if key != "plates":
            # attached مش بيتورث في build_campaign، فمانسخهوش.
            for entry in value.values():
                if isinstance(entry, dict):
                    entry.pop("attached", None)
        seed[key] = value
    days[day] = seed
    return True


def _current(data: dict[str, Any], day: str, path: tuple[str, ...]) -> Any:
    raw = (data.get("day_campaign") or {}).get(day) or {}
    return campaign._legacy_view(raw, path)


def _allowed(current: Any, op: campaign.Op, data: dict[str, Any], day: str) -> tuple[bool, str]:
    field = op.path[-1]
    if field == "driver":
        new_link = isinstance(op.value, dict) and op.value.get("kind") in {"personnel", "conscript"} and op.value.get("id")
        old_text = isinstance(current, dict) and current.get("kind") == "text"
        return bool(new_link and (current in (None, "", {}) or old_text)), "person"
    if field == "attached":
        old_text = isinstance(current, list) and current and all(not x.get("assignment_id") for x in current if isinstance(x, dict))
        new_links = isinstance(op.value, list) and op.value and all(x.get("assignment_id") for x in op.value if isinstance(x, dict))
        return bool(new_links and (current in (None, "", []) or old_text)), "service"
    if field == "basic_entry_id":
        basics = {row["id"] for row in __import__("backend.dated", fromlist=["afraad_basic_on"]).afraad_basic_on(data, day)}
        dead = bool(current and current not in basics)
        return bool(current in (None, "") or dead), "basic_entry"
    if field in {"vehicle_id", "vehicles"}:
        return current in (None, "", [], {}), "vehicle"
    # 025 مش إعادة استيراد: مانملاش plate_text/type_text/سجل اللوحات هنا.
    return False, "other"


def _campaign_pass(data: dict[str, Any], root: Path, start: str, end: str | None) -> dict[str, Any]:
    files = campaign.discover_files(root, start, end)
    fleet = campaign.FleetIndex(data)
    counts = Counter()
    medium: list[dict[str, str]] = []
    unresolved: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    diverged: list[dict[str, Any]] = []
    for day, source in sorted(files.items()):
        sheet = campaign.extract_file(source)
        if sheet.get("error"):
            unresolved.append({"day": day, "kind": "file", "row": source.name, "reason": sheet["error"]})
            continue
        seeded = _seed_day(data, day)
        before_changes = len(changes)
        plan = campaign.build_plan(data, day, sheet, fleet, best_effort_plates=True)
        strict = campaign.build_plan(data, day, sheet, fleet, best_effort_plates=False)
        strict_vehicle_paths = {op.path for op in strict.ops if op.path[-1] in {"vehicle_id", "vehicles"}}
        # تصنيف التعارضات بمنطق 022، للعرض فقط.
        campaign.merge_plan(data, plan, apply=False)
        for conflict in plan.conflicts:
            # اختلاف تخمين جديد مع سائق مربوط مش تعارض استيراد؛ القيمة المربوطة هي المرجع.
            if conflict.path[-1] == "driver":
                diverged.append({"day": day, "row": conflict.row, "path": "/".join(conflict.path),
                                 "current": conflict.current, "archive": conflict.archive})
                continue
            conflicts.append({"day": day, "row": conflict.row, "path": "/".join(conflict.path),
                              "current": conflict.current, "archive": conflict.archive})
        for op in plan.ops:
            current = _current(data, day, op.path)
            allowed, category = _allowed(current, op, data, day)
            if category == "vehicle" and op.path in strict_vehicle_paths:
                allowed = False
            if not allowed:
                # سائق مربوط بنفس الشخص من غير اسم الأرشيف -> نحفظ اسم الأرشيف للطباعة بس.
                if (category == "person" and isinstance(current, dict) and isinstance(op.value, dict)
                        and current.get("kind") == op.value.get("kind") and current.get("id")
                        and current.get("id") == op.value.get("id") and not current.get("display")
                        and str(op.archive or "").strip()):
                    campaign._set(data.setdefault("day_campaign", {}).setdefault(day, {}), op.path,
                                  {**current, "display": str(op.archive).strip()})
                    counts["display_kept"] += 1
                    changes.append({"day": day, "path": "/".join(op.path), "category": "display"})
                continue
            if category == "person":
                match = resolve_person(data, op.archive, day, role="conscript-driver", service=op.row)
                # لو المحلل المحافظ مش مؤكد نفس الهوية يبقى فيه شك -> مايتربطش.
                if match.person_id != op.value.get("id"):
                    continue
                counts["linked_high"] += 1
                medium.append({"day": day, "archive": op.archive, "chosen": match.name,
                               "reason": match.reason, "row": op.row})
            else:
                counts[f"linked_{category}"] += 1
            value = op.value
            if category == "person" and str(op.archive or "").strip():
                # الربط بالشخص، والطباعة باسم الأرشيف زي الأصل.
                value = {**op.value, "display": str(op.archive).strip()}
            campaign._set(data.setdefault("day_campaign", {}).setdefault(day, {}), op.path, value)
            changes.append({"day": day, "path": "/".join(op.path), "category": category})
        if seeded and len(changes) == before_changes:
            # مفيش تعديل فعلي؛ نرجّع اليوم يورث زي ما كان.
            data["day_campaign"].pop(day, None)
        unresolved.extend(plan.unresolved)
    return {"counts": counts, "medium": medium, "unresolved": unresolved,
            "conflicts": conflicts, "changes": changes, "diverged": diverged}


class _LegacyOfficerIndex:
    """نسخة مطابقة 023؛ بنقارن خطتها بالمحلل الجديد عشان مانملاش توريث عادي."""
    def __init__(self, data: dict[str, Any], day: str) -> None:
        self.items = []
        for raw in PeopleRepo(data).raw_on_force(day, "officers"):
            eff = {**raw, **effective(raw, day)}
            self.items.append({"id": raw["id"], "name": raw.get("name", ""),
                               "short": norm_name(raw.get("short_name") or "").split(),
                               "full": norm_name(raw.get("name") or "").split(),
                               "rank": normalize_rank(eff.get("role", ""))["value"],
                               "label": f"{eff.get('role', '')} / {raw.get('short_name') or raw.get('name', '')}"})

    def resolve(self, name: str, rank: str = "", only: set[str] | None = None) -> dict[str, Any]:
        tokens = norm_name(name).split()
        if len(tokens) < 2:
            return {"status": "none"}
        hits = []
        for item in self.items:
            if only is not None and item["id"] not in only:
                continue
            if item["short"] and item["short"] == tokens:
                hits.append(item)
            elif item["full"][:len(tokens)] == tokens or name_compatible(" ".join(tokens), " ".join(item["full"])):
                hits.append(item)
        if len(hits) > 1 and rank:
            wanted = normalize_rank(rank)["value"]
            hits = [item for item in hits if item["rank"] == wanted] or hits
        if len(hits) > 1:
            hits = [item for item in hits if item["short"] == tokens] or hits
        if not hits:
            return {"status": "none"}
        if len(hits) > 1:
            return {"status": "ambiguous", "candidates": [item["id"] for item in hits]}
        return {"status": "ok", "id": hits[0]["id"], "label": hits[0]["label"]}

    def label(self, officer_id: str) -> str:
        return next((item["label"] for item in self.items if item["id"] == officer_id), officer_id)


def _copy_gap_value(target: dict[str, Any], source: dict[str, Any], day: str, op: archive_gaps.Op) -> None:
    if op.category == "regularity":
        dst = target.setdefault("regularity_inputs", {}).setdefault(day, {})
        src = source["regularity_inputs"][day]
        kind, _, key = op.key.partition(":")
        if kind == "officer_extra":
            dst.setdefault("officer_extra", {})[key] = deepcopy(src["officer_extra"][key])
        elif kind == "big_column":
            dst.setdefault("big_column_supervisors", {})[key] = deepcopy(src["big_column_supervisors"][key])
        else:
            dst["notes"] = deepcopy(src["notes"])
    elif op.category == "admin_work":
        target.setdefault("day_officers", {}).setdefault(day, {})[op.key] = deepcopy(
            source["day_officers"][day][op.key])
    elif op.category == "split_target":
        wanted = next(row for row in source["day_assignments"][day] if row.get("id") == op.key)
        current = next(row for row in target["day_assignments"][day] if row.get("id") == op.key)
        current["officer_ids"] = deepcopy(wanted.get("officer_ids") or [])
        current["periods"] = deepcopy(wanted.get("periods") or [])


def _gaps_pass(data: dict[str, Any], root: Path, start: str, end: str | None) -> dict[str, Any]:
    before = deepcopy(data)
    original_index = archive_gaps.OfficerIndex
    try:
        archive_gaps.OfficerIndex = _LegacyOfficerIndex
        legacy = archive_gaps.run_all(before, root, start, end, apply=False, batch=BATCH, import_days=False)
    finally:
        archive_gaps.OfficerIndex = original_index
    working = deepcopy(data)
    report = archive_gaps.run_all(working, root, start, end, apply=True, batch=BATCH,
                                  import_days=False)
    legacy_keys = {(day, op.category, op.key) for day, gaps in legacy["days"].items() for op in gaps.ops}
    changes: list[dict[str, str]] = []
    confidence = Counter()
    medium: list[dict[str, str]] = []
    unresolved: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for day, gaps in report["days"].items():
        for op in gaps.ops:
            newly_resolved = (day, op.category, op.key) not in legacy_keys
            if op.status == "add" and newly_resolved:
                _copy_gap_value(data, working, day, op)
                changes.append({"day": day, "path": f"{op.category}/{op.key}", "category": "archive_gap"})
                raw = op.label or op.archive
                match = resolve_person(data, raw, day, role="officer")
                if match.person_id:
                    confidence["linked_high"] += 1
                    medium.append({"day": day, "archive": raw, "chosen": match.name,
                                   "reason": match.reason, "row": op.label})
            elif op.status == "conflict" and newly_resolved:
                conflicts.append({"day": day, "row": op.label, "path": f"{op.category}/{op.key}",
                                  "current": op.current, "archive": op.archive})
        unresolved.extend(gaps.unresolved)
    return {"counts": confidence, "medium": medium, "unresolved": unresolved,
            "conflicts": conflicts, "changes": changes, "before": before}


def _cell(value: Any) -> str:
    return str(value).replace("|", "/").replace("\n", " ")


def _preview(result: dict[str, Any], mode: str) -> str:
    counts = result["counts"]
    unresolved = result["unresolved"]
    conflicts = result["conflicts"]
    diverged = result.get("diverged") or []
    other = counts["linked_service"] + counts["linked_vehicle"] + counts["linked_basic_entry"]
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for item in result["medium"]:
        entry = grouped.setdefault((item["archive"], item["chosen"]), {**item, "days": 0})
        entry["days"] += 1
    risky = sorted(grouped.values(), key=lambda item: (-item["days"], item["archive"]))
    lines = ["# معاينة حل بنود الاستيراد 025", "",
             f"- الوضع: **{mode}** — الدفعة `resolve-025`.",
             f"- روابط الأشخاص: **{counts['linked_high']}** على {len(grouped)} اسم مختلف؛ "
             "الربط محافظ (تليفون / اسم مؤكد يدويًا / كل الكلمات كاملة وبنفس الترتيب والاسم الأول مطابق ومرشح وحيد) "
             "وأي شك بيفضل فاضي، ومفيش ثقة متوسطة.",
             f"- ربط خدمات: **{counts['linked_service']}**، لوحات: **{counts['linked_vehicle']}**، "
             f"روابط الارتكاز/القايمة: **{counts['linked_basic_entry']}**.",
             f"- اتسابت فاضية/غير محلولة: **{len(unresolved)}**.",
             f"- تعارضات ماتلمستش: **{len(conflicts)}**؛ وتخمينات جديدة اختلفت عن سائق مربوط (ماتلمستش): **{len(diverged)}**.",
             f"- إجمالي التعديلات: **{len(result['changes'])}** (هويات {counts['linked_high']} + غيرها {other}).",
             "", "## تفاصيل غير المحلول حسب السبب", ""]
    reasons = Counter(str(item.get("reason") or item.get("kind") or "غير محدد") for item in unresolved)
    lines += ["| السبب | العدد |", "|---|---|"]
    lines += [f"| {_cell(reason)} | {count} |" for reason, count in reasons.most_common(15)]
    lines += ["", "## التعارضات اللي ماتلمستش", "",
              "| اليوم | الصف | الحقل | الموجود | الأرشيف |", "|---|---|---|---|---|"]
    for item in conflicts:
        lines.append(f"| {item['day']} | {_cell(item['row'])} | {_cell(item['path'])} | "
                     f"{_cell(item['current'])} | {_cell(item['archive'])} |")
    if not conflicts:
        lines.append("| — | — | — | — | — |")
    if diverged:
        lines += ["", "## سائق مربوط والتخمين الجديد مختلف (فضل زي ما هو)", "",
                  "| اليوم | الصف | الموجود | الأرشيف |", "|---|---|---|---|"]
        for item in diverged:
            lines.append(f"| {item['day']} | {_cell(item['row'])} | {_cell(item['current'])} | {_cell(item['archive'])} |")
    lines += ["", "## كل روابط الأشخاص للمراجعة", "",
              "كل اسم مختلف في صف؛ العمود الأخير عدد الأيام/الصفوف اللي اتربط فيها نفس الاسم.", "",
              "| أول يوم | النص في الأرشيف | الشخص المختار | القاعدة | أيام |", "|---|---|---|---|---|"]
    for item in risky:
        lines.append(f"| {item['day']} | {_cell(item['archive'])} | {_cell(item['chosen'])} | "
                     f"{_cell(item['reason'])} | {item['days']} |")
    if not risky:
        lines.append("| — | — | — | مفيش تخمينات متوسطة | — |")
    lines += ["", "## ملاحظات", "",
              "- مفيش قيمة مربوطة موجودة اتغيرت؛ الترقية فقط من نص/فاضي لهوية.",
              "- التعادل الحقيقي بعد الرتبة والاستمرارية بيفضل فاضي.", ""]
    return "\n".join(lines)


def migrate(data, options=None):
    options = options or _options()
    root = options.archive_root.resolve()
    campaign_result = _campaign_pass(data, root, options.start, options.end)
    # الاستمرارية (نفس السائق في يوم مجاور) بتتأثر بالربط الجديد، فنكرر لحد الاستقرار
    # عشان التشغيل التاني يطلع صفر تعديلات.
    for _ in range(5):
        again = _campaign_pass(data, root, options.start, options.end)
        if not again["changes"]:
            break
        for key in ("changes", "medium"):
            campaign_result[key] += again[key]
        campaign_result["counts"] += again["counts"]
        campaign_result["unresolved"] = again["unresolved"]
        campaign_result["conflicts"] = again["conflicts"]
        campaign_result["diverged"] = again["diverged"]
    gaps_result = _gaps_pass(data, root, options.start, options.end)
    counts = campaign_result["counts"] + gaps_result["counts"]
    result = {"counts": counts, "medium": campaign_result["medium"] + gaps_result["medium"],
              "unresolved": campaign_result["unresolved"] + gaps_result["unresolved"],
              "conflicts": campaign_result["conflicts"] + gaps_result["conflicts"],
              "diverged": campaign_result.get("diverged", []),
              "changes": campaign_result["changes"] + gaps_result["changes"]}
    if options.report:
        options.report.parent.mkdir(parents=True, exist_ok=True)
        options.report.write_text(_preview(result, "write" if options.write else "dry-run"), encoding="utf-8")
    if not result["changes"]:
        raise AlreadyDone(f"مفيش بنود نصية/فاضية جديدة تتحل (التعارضات المتسابة: {len(result['conflicts'])}).")
    from backend import changes
    changes.record(data, "import", BATCH, "batch",
                   after={"linked_high": counts["linked_high"],
                          "other_links": counts["linked_service"] + counts["linked_vehicle"] + counts["linked_basic_entry"],
                          "left_empty": len(result["unresolved"]), "conflicts_untouched": len(result["conflicts"])},
                   text=f"حل بنود الاستيراد ({BATCH}): {len(result['changes'])} تعديل، "
                        f"{len(result['conflicts'])} تعارض اتسابوا")
    return [f"هويات اتربطت (محافظ): {counts['linked_high']}.",
            f"خدمات/لوحات/روابط: {counts['linked_service'] + counts['linked_vehicle'] + counts['linked_basic_entry']}.",
            f"اللي فضل غير محلول: {len(result['unresolved'])}. تعارضات اتسابت: {len(result['conflicts'])}.",
            f"إجمالي التعديلات: {len(result['changes'])}."]


if __name__ == "__main__":
    run(from_schema=6, to_schema=6, migrate=migrate, title="حل بنود 022/023 غير المحلولة")
