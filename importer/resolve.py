"""حل الهويات بمراسٍ ثابتة، من دون الدمج عبر الأسماء القصيرة."""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from backend.constants import RANK_ORDER

from .ledger import Ledger, atomic_write_bytes, atomic_write_json, atomic_write_jsonl
from .normalize import normalize_phones, normalize_seniority
from .textnorm import clean_text, norm_name


VERSION = "4"
_ANCHOR_ROLE = "snapshot"
_OFFICER_PRESENCE_ROLES = {"roster", "ref_officers"}
_PERSONNEL_PRESENCE_ROLES = {"afraad", "ref_personnel", "duty_list", "board"}
_HEADING_WORDS = {
    "الحراسات المشدده", "الخوارج", "القوه", "الخدمات", "الخدمات الاساسيه",
    "الخدمات الطاريه", "الاهداف", "وحده", "مشرف", "الاسم", "الرتبه", "الدرجه",
}
_HEADING_PREFIXES = ("الخدمات ", "خدمات ", "الحراسات ", "فتره ")
_TRAILING_FRAGMENT_RE = re.compile(
    r"\s*(?:[\(\[\{\"«]|\b(?:عوده|ليل|صبح|مشرف|لحين|عقب|حتي|حتى|من\s+الساعه|بعد)\b).*$",
    re.I,
)
_NON_NAME_TOKENS = {
    "تقصيره", "وحده", "بعدد", "عدد", "ضروره", "متابعه", "اعمال", "بالزي", "الميري",
    "للاشتراك", "بالمبادره", "لرئاسه", "برئاسه", "رئاسه", "لرئاسة", "برئاسة", "رئاسة", "لرياسه", "برياسه", "رياسه", "الخدمات", "فتره", "صباحيه", "ليليه", "عمل", "راحه",
    "شارع",
}
_TOKEN_VARIANTS = {
    "السيد": "سيد", "سيد": "سيد",
    "رافت": "رافت", "رفعت": "رافت",
    "سعد": "سعد", "سعيد": "سعد",
}


class UnionFind:
    def __init__(self, size: int):
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> int:
        a, b = self.find(left), self.find(right)
        if a == b:
            return a
        keep, drop = min(a, b), max(a, b)
        self.parent[drop] = keep
        return keep


@dataclass(frozen=True)
class Observation:
    key: str
    kind: str
    date: str
    role: str
    name: str
    name_key: str
    code: str = ""
    rank_grade: str = ""
    phone: str = ""
    post: str = ""
    section: str = ""
    authoritative: bool = True
    anchor_id: str = ""
    source_text: str = ""
    document: str = ""


@dataclass
class Resolution:
    groups: list[list[Observation]]
    mapping: dict[str, str]
    unresolved: list[dict[str, Any]]
    conflicts: dict[int, set[str]]
    merges: list[dict[str, Any]]
    remaining_candidates: list[dict[str, Any]]


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _clean_name(raw: str) -> tuple[str, str]:
    display = clean_text(raw)
    display = clean_text(_TRAILING_FRAGMENT_RE.sub("", display)).strip(" /\\-:;,.\"'«»")
    kept: list[str] = []
    raw_tokens = display.split()
    for index, token in enumerate(raw_tokens):
        token_key = norm_name(token.strip(" /\\-:;,.\"'«»…"))
        next_key = norm_name(raw_tokens[index + 1]) if index + 1 < len(raw_tokens) else ""
        if token_key in _NON_NAME_TOKENS or (token_key == "علي" and next_key == "مدار"):
            break
        kept.append(token)
        if len(kept) == 5:
            break
    display = clean_text(" ".join(kept)).strip(" /\\-:;,.\"'«»")
    key = norm_name(display)
    tokens = key.split()
    if len(tokens) < 2 or any(char.isdigit() for char in key):
        return "", ""
    if key in _HEADING_WORDS or key.startswith(_HEADING_PREFIXES):
        return "", ""
    if tokens[0] in {"وحده", "وحدة", "مشرف", "قايم", "خدمه", "الخدمه"}:
        return "", ""
    return display, key


def _source_text(record: dict[str, Any]) -> str:
    return clean_text(record.get("raw_text") or " | ".join(record.get("raw_cells", [])))


def _identity_code(value: str) -> str:
    code = normalize_seniority(value)["value"]
    if re.fullmatch(r"(?:19|20)\d{6}", code):
        return f"{int(code[4:])}/{code[:4]}"
    short_year = re.fullmatch(r"(\d+)/(\d{2})", code)
    if short_year:
        return f"{int(short_year.group(1))}/20{short_year.group(2)}"
    return code


def _quarantined(validate_path: Path) -> set[tuple[str, str, str]]:
    if not validate_path.exists():
        return set()
    return {(record["date"], record["role"], record["path"])
            for record in _load_jsonl(validate_path) if record.get("verdict") == "quarantine"}


def collect_observations(records: list[dict[str, Any]], quarantined: set[tuple[str, str, str]] | None = None
                         ) -> tuple[list[Observation], list[Observation]]:
    quarantined = quarantined or set()
    officers: list[Observation] = []
    personnel: list[Observation] = []
    for record_index, record in enumerate(records):
        normalized = record.get("normalized", {})
        authority = (record["date"], record["role"], record["path"]) not in quarantined
        base_key = f"{record_index}:{record['date']}:{record['role']}:{record.get('table_index')}:{record.get('row_index')}"
        officer = normalized.get("officer")
        if officer:
            name, name_key = _clean_name(officer.get("name", {}).get("value", ""))
            if name:
                phones = officer.get("phones", {}).get("value", []) or [""]
                officers.append(Observation(
                    base_key, "officer", record["date"], record["role"], name, name_key,
                    _identity_code(officer.get("seniority", {}).get("value", "")), officer.get("rank", {}).get("value", ""),
                    phones[0], officer.get("post", {}).get("value", ""), record.get("section", ""), authority,
                    source_text=_source_text(record), document=record.get("path", ""),
                ))
        for person_index, person in enumerate(normalized.get("people", [])):
            name, name_key = _clean_name(person.get("name", {}).get("value", ""))
            if not name:
                continue
            phones = person.get("phones", {}).get("value", []) or [""]
            target = officers if person["kind"] == "officer" else personnel
            rank_grade = person.get("rank", person.get("grade", {})).get("value", "")
            for phone_index, phone in enumerate(phones):
                target.append(Observation(
                    f"{base_key}:{person_index}:{phone_index}", person["kind"], record["date"], record["role"],
                    name, name_key, rank_grade=rank_grade, phone=phone, authoritative=authority,
                    source_text=_source_text(record), document=record.get("path", ""),
                ))
    return officers, personnel


def _anchor_observations(core: dict[str, Any], kind: str) -> list[Observation]:
    result: list[Observation] = []
    key = "officers" if kind == "officer" else "personnel"
    for person in sorted(core.get(key, []), key=lambda item: item.get("id", "")):
        name, name_key = _clean_name(person.get("name", ""))
        if not name:
            continue
        phones = normalize_phones(" ".join(
            [str(person.get("phone", "")), *map(str, person.get("other_phones") or [])]
        ))["value"] or [""]
        code = _identity_code(person.get("code", "")) if kind == "officer" else ""
        for phone_index, phone in enumerate(phones):
            result.append(Observation(
                f"anchor:{person['id']}:{phone_index}", kind, "", _ANCHOR_ROLE, name, name_key,
                code=code, rank_grade=person.get("role", ""), phone=phone, post=person.get("post", ""),
                section=person.get("section", ""), anchor_id=person["id"], source_text="snapshot",
            ))
        if kind == "officer":
            for history_index, history in enumerate(person.get("history") or []):
                result.append(Observation(
                    f"anchor:{person['id']}:history:{history_index}", kind, history.get("from", ""),
                    _ANCHOR_ROLE, name, name_key, code=code, rank_grade=history.get("role", ""),
                    post=history.get("post", ""), section=history.get("section", ""),
                    anchor_id=person["id"], source_text="snapshot-history",
                ))
    return result


def _tokens(value: str) -> list[str]:
    return value.split()


def _full_name(value: str) -> bool:
    return len(_tokens(value)) >= 3


def _ordered_subsequence(short: list[str], long: list[str]) -> bool:
    index = 0
    for token in long:
        if index < len(short) and token == short[index]:
            index += 1
    return index == len(short)


def _strong_name_compatible(left: str, right: str) -> bool:
    a, b = _tokens(left), _tokens(right)
    if len(a) < 3 or len(b) < 3 or a[:2] != b[:2]:
        return False
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return _ordered_subsequence(short, long)


def _strong_seniority_code(value: str) -> bool:
    """السنة وحدها في اللقطة ليست مفتاح هوية كافيًا."""
    return bool(re.fullmatch(r"\d+/\d{4}", value))


def _seniority_codes_compatible(codes: Iterable[str]) -> bool:
    """يقبل سنة اللقطة كجزء ناقص من الكود، لا ككود ثانٍ."""
    values = {value for value in codes if value}
    full = {value for value in values if _strong_seniority_code(value)}
    partial_years = {value for value in values if re.fullmatch(r"\d{4}", value)}
    other = values - full - partial_years
    if len(values) <= 1:
        return True
    if len(full) > 1 or len(partial_years) > 1 or other:
        return False
    if full and partial_years:
        return {next(iter(full)).rsplit("/", 1)[1]} == partial_years
    return True


def _edit_distance(left: str, right: str) -> int:
    if len(left) > len(right):
        left, right = right, left
    previous = list(range(len(left) + 1))
    for row, right_char in enumerate(right, 1):
        current = [row]
        for column, left_char in enumerate(left, 1):
            current.append(min(current[-1] + 1, previous[column] + 1,
                               previous[column - 1] + (left_char != right_char)))
        previous = current
    return previous[-1]


def _canonical_token(value: str) -> str:
    value = norm_name(value).replace("ة", "ه").replace("ى", "ي")
    return _TOKEN_VARIANTS.get(value, value)


def _expanded_tokens(value: str) -> list[str]:
    result: list[str] = []
    for raw in _tokens(value):
        token = _canonical_token(raw)
        if token.startswith("عبدال") and len(token) > 6:
            result.extend(["عبد", token[3:]])
        else:
            result.append(token)
    return result


def _fuzzy_token_distance(left: str, right: str) -> int | None:
    left, right = _canonical_token(left), _canonical_token(right)
    if left == right:
        return 0
    if min(len(left), len(right)) >= 4:
        distance = _edit_distance(left, right)
        if distance <= 1:
            return distance
    return None


def _fuzzy_name_score(left: str, right: str) -> tuple[int, int] | None:
    """مطابقة رتيبة للأسماء مع السماح باختلاف هجائي محدود."""
    original_left, original_right = _tokens(left), _tokens(right)
    if not original_left or not original_right:
        return None
    first_distance = _fuzzy_token_distance(original_left[0], original_right[0])
    if first_distance is None:
        return None
    a, b = _expanded_tokens(left), _expanded_tokens(right)
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    index = 0
    edits = 0
    for token in long:
        if index >= len(short):
            break
        distance = _fuzzy_token_distance(short[index], token)
        if distance is not None:
            edits += distance
            index += 1
    if index != len(short):
        return None
    return edits, len(long) - len(short)


def _canonical_prefix(value: str) -> str:
    tokens = _tokens(value)[:2]
    return " ".join(_canonical_token(token) for token in tokens)


def _cooccurrence_units(values: Iterable[Observation], kind: str) -> set[str]:
    units: set[str] = set()
    for item in values:
        if not item.date or item.role == _ANCHOR_ROLE:
            continue
        if kind == "officer" and item.role in _OFFICER_PRESENCE_ROLES:
            units.add(item.date)
        elif kind == "personnel" and item.role in _PERSONNEL_PRESENCE_ROLES:
            units.add(f"{item.date}|{item.document or item.role}")
    return units


def _rank_demotion(values: Iterable[Observation]) -> bool:
    dated = sorted(
        (item.date, RANK_ORDER.index(item.rank_grade))
        for item in values if item.date and item.rank_grade in RANK_ORDER
    )
    best = len(RANK_ORDER)
    for _date, rank_index in dated:
        if best < len(RANK_ORDER) and rank_index > best:
            return True
        best = min(best, rank_index)
    return False


def _rank_score(weak: Observation, group: list[Observation]) -> int | None:
    if not weak.rank_grade or weak.rank_grade not in RANK_ORDER:
        return 1
    ranks = {item.rank_grade for item in group if item.rank_grade in RANK_ORDER}
    if not ranks:
        return 1
    if weak.rank_grade in ranks:
        return 0
    distance = min(abs(RANK_ORDER.index(weak.rank_grade) - RANK_ORDER.index(rank)) for rank in ranks)
    return 1 if distance <= 1 else None


def _strip_article(token: str) -> str:
    # «الجاويش» و«جاويش» نفس اللقب — أداة التعريف مش جزء من هوية الاسم
    return token[2:] if token.startswith("ال") and len(token) > 4 else token


def _weak_name_score(weak_key: str, strong_key: str) -> int | None:
    weak = [_strip_article(token) for token in _tokens(weak_key)]
    strong = [_strip_article(token) for token in _tokens(strong_key)]
    if not weak or not strong or _edit_distance(weak[0], strong[0]) > 1:
        return None
    index = 0
    edits = 0
    for token in strong:
        if index >= len(weak):
            break
        distance = _edit_distance(weak[index], token)
        if distance <= 1:
            edits += distance
            index += 1
    if index == len(weak):
        return edits
    last = min((_edit_distance(weak[-1], token) for token in strong[1:]), default=99)
    return edits + last if last <= 1 else None


def _group_metadata(nodes: list[Observation], indexes: Iterable[int], kind: str) -> dict[str, set[str]]:
    values = [nodes[index] for index in indexes]
    names = {item.name_key for item in values if _full_name(item.name_key)}
    return {
        "anchors": {item.anchor_id for item in values if item.anchor_id},
        "codes": {item.code for item in values if kind == "officer" and
                  (_strong_seniority_code(item.code) or re.fullmatch(r"\d{4}", item.code))},
        "prefixes": {" ".join(_tokens(name)[:2]) for name in names},
        "names": names,
    }


def _metadata_compatible(left: dict[str, set[str]], right: dict[str, set[str]],
                         *, require_name_compatibility: bool = True) -> bool:
    if len(left["anchors"] | right["anchors"]) > 1:
        return False
    if not _seniority_codes_compatible(left["codes"] | right["codes"]):
        return False
    if len(left["prefixes"] | right["prefixes"]) > 1:
        return False
    if not require_name_compatibility:
        return True
    names = sorted(left["names"] | right["names"])
    return all(_strong_name_compatible(a, b) for pos, a in enumerate(names) for b in names[pos + 1:])


def _groups_rank_plausible(left: list[Observation], right: list[Observation]) -> bool:
    a = {item.rank_grade for item in left if item.rank_grade in RANK_ORDER}
    b = {item.rank_grade for item in right if item.rank_grade in RANK_ORDER}
    return not a or not b or any(abs(RANK_ORDER.index(x) - RANK_ORDER.index(y)) <= 1 for x in a for y in b)


def _resolve_strong(observations: list[Observation], anchors: list[Observation], kind: str) -> Resolution:
    archive = [item for item in observations if item.authoritative]
    strong = [item for item in archive if _full_name(item.name_key) or
              (_strong_seniority_code(item.code) if kind == "officer" else item.phone)]
    strong_keys = {item.key for item in strong}
    weak = [item for item in archive if item.key not in strong_keys]
    nodes = [*anchors, *strong]
    uf = UnionFind(len(nodes))
    members: dict[int, set[int]] = {index: {index} for index in range(len(nodes))}
    strong_events: list[dict[str, Any]] = []

    def group_label(indexes: set[int]) -> str:
        values = [nodes[index] for index in indexes]
        anchors_seen = sorted({item.anchor_id for item in values if item.anchor_id})
        if anchors_seen:
            return " ; ".join(anchors_seen)
        names_seen = sorted({item.name for item in values}, key=lambda value: (-len(norm_name(value)), value))
        return names_seen[0] if names_seen else ""

    def safe_union(left: int, right: int, *, via_key: bool = False, rule: str = "strong_name",
                   evidence_key: str = "") -> bool:
        a, b = uf.find(left), uf.find(right)
        if a == b:
            return True
        left_indexes, right_indexes = members[a], members[b]
        left_meta = _group_metadata(nodes, left_indexes, kind)
        right_meta = _group_metadata(nodes, right_indexes, kind)
        if not _metadata_compatible(left_meta, right_meta,
                                    require_name_compatibility=not via_key):
            return False
        if right_meta["anchors"] or (not left_meta["anchors"] and not right_meta["anchors"] and
                                     len(right_indexes) > len(left_indexes)):
            target_indexes, source_indexes = right_indexes, left_indexes
        else:
            target_indexes, source_indexes = left_indexes, right_indexes
        root = uf.union(a, b)
        dropped = b if root == a else a
        combined_indexes = left_indexes | right_indexes
        members[root] = combined_indexes
        members.pop(dropped, None)
        anchor_transition = bool(left_meta["anchors"]) != bool(right_meta["anchors"])
        if anchor_transition or left_meta["names"] != right_meta["names"]:
            strong_events.append({
                "node": min(combined_indexes), "merged_into": group_label(target_indexes),
                "merged_from": group_label(source_indexes), "rule": rule,
                "evidence": (
                    f"names={' ; '.join(sorted(left_meta['names'] | right_meta['names']))}; "
                    f"codes={' ; '.join(sorted(left_meta['codes'] | right_meta['codes'])) or 'none'}; "
                    f"key={evidence_key or 'none'}"
                ),
            })
        return True

    by_name: dict[str, list[int]] = defaultdict(list)
    by_key: dict[str, list[int]] = defaultdict(list)
    rejected_name_nodes: set[int] = set()
    rejected_rank_nodes: set[int] = set()
    for index, item in enumerate(nodes):
        if _full_name(item.name_key):
            by_name[item.name_key].append(index)
        key = item.code if kind == "officer" and _strong_seniority_code(item.code) else (
            item.phone if kind == "personnel" else ""
        )
        if key:
            by_key[key].append(index)
    for indexes in by_name.values():
        for index in indexes[1:]:
            left, right = uf.find(indexes[0]), uf.find(index)
            rejected = set(members[left]) | set(members[right])
            if not safe_union(left, right, rule="exact_full_name"):
                rejected_name_nodes.update(rejected)
    rejected_keys: set[str] = set()
    for key, indexes in by_key.items():
        roots = sorted({uf.find(index) for index in indexes})
        for pos, root in enumerate(roots):
            for other in roots[pos + 1:]:
                key_rule = "seniority_code" if kind == "officer" else "phone"
                if not safe_union(root, other, via_key=True, rule=key_rule, evidence_key=key):
                    rejected_keys.add(key)

    prefix_roots: dict[str, set[int]] = defaultdict(set)
    for root, indexes in members.items():
        for prefix in _group_metadata(nodes, indexes, kind)["prefixes"]:
            prefix_roots[prefix].add(root)
    for roots_set in prefix_roots.values():
        roots = sorted(roots_set)
        for pos, original_root in enumerate(roots):
            for original_other in roots[pos + 1:]:
                root, other = uf.find(original_root), uf.find(original_other)
                if root == other or root not in members or other not in members:
                    continue
                left = _group_metadata(nodes, members[root], kind)
                right = _group_metadata(nodes, members[other], kind)
                if not any(_strong_name_compatible(a, b) for a in left["names"] for b in right["names"]):
                    continue
                if kind == "officer" and not _groups_rank_plausible(
                    [nodes[index] for index in members[root]], [nodes[index] for index in members[other]]
                ):
                    rejected_rank_nodes.update(members[root] | members[other])
                    continue
                if _metadata_compatible(left, right):
                    safe_union(root, other, rule="ordered_subsequence_full_name")
                else:
                    rejected_name_nodes.update(members[root] | members[other])

    # مرحلة مستقلة: التشابه لا يكفي إذا ثبت التزامن في المصدر.
    fuzzy_edges: list[tuple[tuple[Any, ...], int, int, tuple[int, int], str, str]] = []
    initial_roots = sorted(members)
    for position, root in enumerate(initial_roots):
        left_group = [nodes[index] for index in members[root]]
        left_names = sorted({item.name_key for item in left_group if _full_name(item.name_key)})
        for other in initial_roots[position + 1:]:
            right_group = [nodes[index] for index in members[other]]
            right_names = sorted({item.name_key for item in right_group if _full_name(item.name_key)})
            matches = [
                (score, left_name, right_name)
                for left_name in left_names for right_name in right_names
                if (score := _fuzzy_name_score(left_name, right_name)) is not None
            ]
            if not matches:
                continue
            score, left_name, right_name = min(matches)
            left_anchor = any(item.anchor_id for item in left_group)
            right_anchor = any(item.anchor_id for item in right_group)
            anchor_priority = 0 if left_anchor != right_anchor else (1 if not left_anchor else 2)
            archive_size = sum(item.role != _ANCHOR_ROLE for item in left_group + right_group)
            fuzzy_edges.append(((anchor_priority, *score, -archive_size, root, other),
                                root, other, score, left_name, right_name))
    fuzzy_edges.sort(key=lambda value: value[0])

    consolidation_events: list[dict[str, Any]] = []
    fuzzy_rank_nodes: set[int] = set()

    for _priority, original_root, original_other, score, matched_left, matched_right in fuzzy_edges:
        root, other = uf.find(original_root), uf.find(original_other)
        if root == other or root not in members or other not in members:
            continue
        left_indexes, right_indexes = members[root], members[other]
        left_values = [nodes[index] for index in left_indexes]
        right_values = [nodes[index] for index in right_indexes]
        left_meta = _group_metadata(nodes, left_indexes, kind)
        right_meta = _group_metadata(nodes, right_indexes, kind)
        if left_meta["anchors"] and right_meta["anchors"]:
            continue
        if not _seniority_codes_compatible(left_meta["codes"] | right_meta["codes"]):
            continue
        first_tokens = {_canonical_token(_tokens(name)[0]) for name in left_meta["names"] | right_meta["names"]}
        if len(first_tokens) > 1:
            continue
        shared_units = _cooccurrence_units(left_values, kind) & _cooccurrence_units(right_values, kind)
        if shared_units:
            continue
        left_is_anchor = bool(left_meta["anchors"])
        right_is_anchor = bool(right_meta["anchors"])
        if right_is_anchor or (not left_is_anchor and not right_is_anchor and
                               sum(item.role != _ANCHOR_ROLE for item in right_values) >
                               sum(item.role != _ANCHOR_ROLE for item in left_values)):
            target_indexes, source_indexes = right_indexes, left_indexes
        else:
            target_indexes, source_indexes = left_indexes, right_indexes
        combined = left_values + right_values
        has_demotion = kind == "officer" and _rank_demotion(combined)
        root_after = uf.union(root, other)
        dropped = other if root_after == root else root
        combined_indexes = left_indexes | right_indexes
        members[root_after] = combined_indexes
        members.pop(dropped, None)
        if has_demotion:
            fuzzy_rank_nodes.update(combined_indexes)
        consolidation_events.append({
            "node": min(combined_indexes), "merged_into": group_label(target_indexes),
            "merged_from": group_label(source_indexes), "rule": "fuzzy_no_cooccurrence",
            "evidence": (
                f"name={matched_left} ~ {matched_right}; edits={score[0]}; gaps={score[1]}; "
                f"cooccurrence=none; codes=compatible; "
                f"rank={'demotion_flagged' if has_demotion else 'plausible'}"
            ),
        })

    root_groups = {root: [nodes[index] for index in sorted(indexes)] for root, indexes in members.items()}
    root_conflicts: dict[int, set[str]] = defaultdict(set)
    for key in rejected_keys:
        for index in by_key[key]:
            root_conflicts[uf.find(index)].add("shared_code" if kind == "officer" else "shared_phone")
    for index in rejected_name_nodes:
        root_conflicts[uf.find(index)].add("conflicting_strong_name")
    for index in rejected_rank_nodes:
        root_conflicts[uf.find(index)].add("rank_conflict")
    for index in fuzzy_rank_nodes:
        root_conflicts[uf.find(index)].add("rank_demotion")

    presence: dict[str, set[int]] = defaultdict(set)
    group_names: dict[int, list[str]] = {}
    group_ranks: dict[int, set[str]] = {}
    for root, group in root_groups.items():
        group_names[root] = sorted({value.name_key for value in group if _full_name(value.name_key)})
        group_ranks[root] = {value.rank_grade for value in group if value.rank_grade in RANK_ORDER}
        for value in group:
            if not value.date:
                continue
            if kind == "officer" and value.role in _OFFICER_PRESENCE_ROLES:
                presence[value.date].add(root)
            elif kind == "personnel" and value.role in _PERSONNEL_PRESENCE_ROLES:
                day = dt.date.fromisoformat(value.date)
                for offset in range(-3, 4):
                    presence[(day + dt.timedelta(days=offset)).isoformat()].add(root)

    weak_assignment: dict[str, int] = {}
    unresolved: list[dict[str, Any]] = []
    weak_cache: dict[tuple[str, str, str], tuple[int | None, str, list[int]]] = {}
    for item in sorted(weak, key=lambda value: (value.date, value.key)):
        cache_key = (item.date, item.name_key, item.rank_grade)
        cached = weak_cache.get(cache_key)
        if cached is None:
            candidates: list[tuple[tuple[int, int], int]] = []
            for root in sorted(presence.get(item.date, set())):
                ranks = group_ranks[root]
                if not item.rank_grade or item.rank_grade not in RANK_ORDER or not ranks:
                    rank_score = 1
                elif item.rank_grade in ranks:
                    rank_score = 0
                elif min(abs(RANK_ORDER.index(item.rank_grade) - RANK_ORDER.index(rank)) for rank in ranks) <= 1:
                    rank_score = 1
                else:
                    continue
                scores = [score for name in group_names[root]
                          if (score := _weak_name_score(item.name_key, name)) is not None]
                if scores:
                    candidates.append(((min(scores), rank_score), root))
            candidates.sort(key=lambda value: (value[0], value[1]))
            best = candidates[0][0] if candidates else None
            hits = [root for score, root in candidates if score == best]
            chosen = hits[0] if best is not None and len(hits) == 1 else None
            reason = "" if chosen is not None else ("ambiguous_weak_name" if candidates else "no_candidate_for_weak_name")
            cached = (chosen, reason, hits)
            weak_cache[cache_key] = cached
        chosen, reason, hits = cached
        if chosen is not None:
            weak_assignment[item.key] = chosen
            root_groups[chosen].append(item)
        else:
            unresolved.append({
                "identity_type": kind, "observation_key": item.key, "date": item.date,
                "name": item.name, "source_text": item.source_text,
                "reason": reason,
                "candidate_roots": hits,
            })

    # يومية الضباط هي المرجع الأساسي لوجود الضابط: اسم مختصر في صف يومية
    # مالوش أي مرشح (زي «هشام عيسي» مدير الإدارة 2023) يبقى شخص قائم بذاته —
    # بالمطابقة الحرفية للاسم بس، من غير أي ربط بتجمع تاني
    roster_only: dict[str, int] = {}
    still_unresolved: list[dict[str, Any]] = []
    weak_by_key = {item.key: item for item in weak}
    pending = [weak_by_key.get(entry["observation_key"]) for entry in unresolved]
    roster_dates: dict[str, set[str]] = defaultdict(set)
    for item in pending:
        if kind == "officer" and item is not None and item.role == "roster" and item.name_key:
            roster_dates[item.name_key].add(item.date)
    # التزامن المانع هنا = نفس يومية الضباط بس؛ ظهور الاسم في كشف قديم مكرر
    # لنفس اليوم مش دليل على شخصين مختلفين
    root_dates = {root: {value.date for value in group if value.role == "roster"}
                  for root, group in root_groups.items()}

    def attach_target(name_key: str) -> int:
        # تجمع واحد متوافق في الاسم وما بيظهرش أبدًا في نفس يوم الاسم ده
        # (زي «هشام عيسي» ← «هشام احمد عيسي» بعدين)؛ غير كده شخص مستقل
        hits = [root for root in sorted(group_names)
                if any(_weak_name_score(name_key, name) is not None for name in group_names[root])
                and not (root_dates.get(root, set()) & roster_dates[name_key])]
        if len(hits) == 1:
            return hits[0]
        return roster_only.setdefault(name_key, -(len(roster_only) + 1))

    targets: dict[str, int] = {}
    for entry, item in zip(unresolved, pending):
        if (kind == "officer" and item is not None and item.role == "roster" and item.name_key
                and entry["reason"] == "no_candidate_for_weak_name"):
            root = targets.setdefault(item.name_key, attach_target(item.name_key))
            root_groups.setdefault(root, []).append(item)
            weak_assignment[item.key] = root
        else:
            still_unresolved.append(entry)
    unresolved = still_unresolved

    ordered_roots = sorted(root_groups, key=lambda root: (
        min((item.date for item in root_groups[root] if item.date and item.role != _ANCHOR_ROLE),
            default="9999-12-31"),
        min(item.anchor_id or item.name_key for item in root_groups[root]),
    ))
    groups = [root_groups[root] for root in ordered_roots]
    root_to_cluster = {root: index for index, root in enumerate(ordered_roots)}
    merges: list[dict[str, Any]] = []
    seen_merge_events: set[tuple[Any, ...]] = set()
    for event in [*strong_events, *consolidation_events]:
        root = uf.find(event.pop("node"))
        converted = {"cluster": root_to_cluster[root], **event}
        signature = (converted["cluster"], converted["merged_from"], converted["rule"])
        if signature not in seen_merge_events:
            merges.append(converted)
            seen_merge_events.add(signature)

    remaining_candidates: list[dict[str, Any]] = []
    final_roots = sorted(root for root in root_groups if root in members)
    for position, root in enumerate(final_roots):
        left = root_groups[root]
        left_meta = _group_metadata(nodes, members[root], kind)
        for other in final_roots[position + 1:]:
            right = root_groups[other]
            if _cooccurrence_units(left, kind) & _cooccurrence_units(right, kind):
                continue
            right_meta = _group_metadata(nodes, members[other], kind)
            matches = [
                (score, a, b) for a in left_meta["names"] for b in right_meta["names"]
                if (score := _fuzzy_name_score(a, b)) is not None
            ]
            if not matches:
                continue
            score, matched_left, matched_right = min(matches)
            reasons: list[str] = []
            if left_meta["anchors"] and right_meta["anchors"]:
                reasons.append("two_anchors")
            if not _seniority_codes_compatible(left_meta["codes"] | right_meta["codes"]):
                reasons.append("conflicting_seniority_codes")
            first_tokens = {
                _canonical_token(_tokens(name)[0]) for name in left_meta["names"] | right_meta["names"]
            }
            if len(first_tokens) > 1:
                reasons.append("incompatible_first_name_chain")
            remaining_candidates.append({
                "left_cluster": root_to_cluster[root], "right_cluster": root_to_cluster[other],
                "left": group_label(members[root]), "right": group_label(members[other]),
                "names": f"{matched_left} ~ {matched_right}",
                "score": {"edits": score[0], "gaps": score[1]},
                "reason": " ; ".join(reasons or ["blocked_by_prior_merge"]),
            })
    mapping: dict[str, str] = {}
    for node_index, item in enumerate(nodes):
        if item.role != _ANCHOR_ROLE:
            mapping[item.key] = str(root_to_cluster[uf.find(node_index)])
    for key, root in weak_assignment.items():
        mapping[key] = str(root_to_cluster[root])
    conflicts = {root_to_cluster[root]: values for root, values in root_conflicts.items() if root in root_to_cluster}
    return Resolution(groups, mapping, unresolved, conflicts, merges, remaining_candidates)


def cluster_officers(observations: list[Observation], anchors: list[Observation] | None = None
                     ) -> tuple[list[list[Observation]], dict[str, str]]:
    result = _resolve_strong(observations, anchors or [], "officer")
    return result.groups, result.mapping


def cluster_personnel(observations: list[Observation], anchors: list[Observation] | None = None
                      ) -> tuple[list[list[Observation]], dict[str, str]]:
    result = _resolve_strong(observations, anchors or [], "personnel")
    return result.groups, result.mapping


def _cluster_details(group: list[Observation], kind: str, sequence: int, conflicts: set[str],
                     decision: dict[str, str] | None = None,
                     merge_events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    merge_events = merge_events or []
    archive = [item for item in group if item.role != _ANCHOR_ROLE]
    anchor_ids = sorted({item.anchor_id for item in group if item.anchor_id})
    names = sorted({item.name for item in group},
                   key=lambda value: (-len(norm_name(value).split()), norm_name(value), value))
    codes = sorted({item.code for item in group if item.code})
    phones = sorted({item.phone for item in group if item.phone})
    prefix = "OFF" if kind == "officer" else "IND"
    proposed = anchor_ids[0] if len(anchor_ids) == 1 else f"NEW-{prefix}-{sequence:03d}"
    evidence = "anchor" if anchor_ids else "strong_name_or_key"
    if merge_events:
        evidence += f"+identity_merges({len(merge_events)})"
    status = "مراجعة" if conflicts else "مقترح"
    confidence = "low" if conflicts else ("high" if anchor_ids else "medium")
    dates = sorted({item.date for item in archive if item.date})
    cluster_key = f"{kind}:{anchor_ids[0] if anchor_ids else norm_name(names[0])}:{dates[0] if dates else 'snapshot'}"
    if decision:
        if decision.get("chosen_id"):
            proposed = decision["chosen_id"]
        if decision.get("status"):
            status = decision["status"]
        evidence += "+reviewer_decision"
    rank_dates: dict[str, str] = {}
    for item in sorted(archive, key=lambda value: (value.date, value.key)):
        if item.rank_grade and item.rank_grade not in rank_dates:
            rank_dates[item.rank_grade] = item.date
    return {
        "cluster_key": cluster_key, "proposed_id": proposed,
        "existing_id": " ; ".join(anchor_ids), "names_seen": " ; ".join(names),
        "codes": " ; ".join(codes), "phones": " ; ".join(phones),
        "ranks_grades": " ; ".join(f"{value} ({day})" for value, day in rank_dates.items()),
        "posts": " ; ".join(sorted({item.post for item in archive if item.post})),
        "sections": " ; ".join(sorted({item.section for item in archive if item.section})),
        "first_date": dates[0] if dates else "", "last_date": dates[-1] if dates else "",
        "days_seen": len(dates), "observations": len(archive),
        "confidence": confidence, "evidence_rule": evidence,
        "status": status, "conflicts": " ; ".join(sorted(conflicts)),
        "merged_from": " ; ".join(event["merged_from"] for event in merge_events),
        "merge_rules": " || ".join(event["rule"] for event in merge_events),
        "merge_evidence": " || ".join(event["evidence"] for event in merge_events),
    }


_REVIEW_FIELDS = [
    "cluster_key", "proposed_id", "existing_id", "names_seen", "codes", "phones", "ranks_grades",
    "posts", "sections", "first_date", "last_date", "days_seen", "observations", "confidence",
    "evidence_rule", "status", "conflicts", "merged_from", "merge_rules", "merge_evidence",
]
_DECISION_FIELDS = ["cluster_key", "chosen_id", "status", "note"]


def _write_csv(path: Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    atomic_write_bytes(path, b"\xef\xbb\xbf" + stream.getvalue().encode("utf-8"))


def _read_decisions(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return {
            row["cluster_key"]: row for row in csv.DictReader(stream)
            if row.get("cluster_key") and any(row.get(field) for field in ("chosen_id", "status", "note"))
        }


def _write_current_decisions(path: Path, details: list[dict[str, Any]],
                             prior: dict[str, dict[str, str]]) -> None:
    rows = []
    for detail in details:
        old = prior.get(detail["cluster_key"], {})
        rows.append({"cluster_key": detail["cluster_key"], "chosen_id": old.get("chosen_id", ""),
                     "status": old.get("status", ""), "note": old.get("note", "")})
    _write_csv(path, _DECISION_FIELDS, rows)


def _expected_ids(day: dict[str, Any], kind: str) -> set[str]:
    if kind == "officer":
        result = set(day.get("officer_states", {}))
        result.update(identifier for row in day.get("assignments", []) for identifier in row.get("officer_ids", []))
        return result
    result = {identifier for row in day.get("assignments", []) for identifier in row.get("personnel_ids", [])}
    for row in day.get("afraad_basic", []):
        result.update(value for key, value in row.items() if key.endswith("_person_id") and value)
    return result


def _reference_report(data_dir: Path, dates: list[str], kind: str, observations: list[Observation],
                      mapping: dict[str, str], details: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    core = json.loads((data_dir / "core.json").read_text(encoding="utf-8"))
    people = {person["id"]: person for person in core.get("officers" if kind == "officer" else "personnel", [])}
    result: dict[str, list[dict[str, Any]]] = {}
    for date in dates:
        path = data_dir / "days" / date[:4] / date[5:7] / f"{date}.json"
        if not path.exists():
            result[date] = [{"type": "reference_day_missing", "source_text": ""}]
            continue
        expected = _expected_ids(json.loads(path.read_text(encoding="utf-8")), kind)
        resolved: set[str] = set()
        mismatches: list[dict[str, Any]] = []
        for item in observations:
            if item.date != date or item.key not in mapping:
                continue
            identifier = details[int(mapping[item.key])]["proposed_id"]
            if identifier in expected:
                resolved.add(identifier)
            levels: list[set[str]] = [set(), set(), set()]
            for expected_id in expected:
                person = people.get(expected_id, {})
                person_key = norm_name(person.get("name", ""))
                if kind == "officer":
                    code = normalize_seniority(person.get("code", ""))["value"]
                    if item.code and code and item.code == code:
                        levels[0].add(expected_id)
                else:
                    phones = set(normalize_phones(" ".join(
                        [str(person.get("phone", "")), *map(str, person.get("other_phones") or [])]
                    ))["value"])
                    if item.phone and item.phone in phones:
                        levels[0].add(expected_id)
                if item.name_key == person_key or (_full_name(item.name_key) and
                                                    _strong_name_compatible(item.name_key, person_key)):
                    levels[1].add(expected_id)
                elif not _full_name(item.name_key) and _weak_name_score(item.name_key, person_key) is not None:
                    levels[2].add(expected_id)
            candidates = next((values for values in levels if values), set())
            if len(candidates) == 1:
                expected_id = next(iter(candidates))
                if identifier != expected_id:
                    mismatches.append({"type": "wrong_id", "expected_id": expected_id,
                                       "resolved_id": identifier, "source_text": item.source_text,
                                       "name": item.name, "observation_key": item.key})
            elif kind == "officer" and identifier.startswith("OFF-") and identifier not in expected:
                mismatches.append({"type": "unexpected_officer_id", "expected_id": "",
                                   "resolved_id": identifier, "source_text": item.source_text,
                                   "name": item.name, "observation_key": item.key})
        missing = [
            {"type": "missing_expected_id", "expected_id": identifier,
             "source_text": "لم تُشتق مشاهدة مطابقة من مصادر اليوم"}
            for identifier in sorted(expected - resolved)
        ]
        unique = {json.dumps(row, ensure_ascii=False, sort_keys=True): row for row in [*mismatches, *missing]}
        result[date] = [unique[key] for key in sorted(unique)]
    return result


def _self_check(groups: list[list[Observation]], kind: str) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for index, group in enumerate(groups):
        anchors = sorted({item.anchor_id for item in group if item.anchor_id})
        codes = sorted({item.code for item in group if kind == "officer" and
                        (_strong_seniority_code(item.code) or re.fullmatch(r"\d{4}", item.code))})
        names = sorted({item.name_key for item in group if _full_name(item.name_key)})
        first_tokens = sorted({_canonical_token(_tokens(name)[0]) for name in names})
        reasons = []
        if len(anchors) > 1:
            reasons.append("multiple_anchors")
        if not _seniority_codes_compatible(codes):
            reasons.append("multiple_seniority_codes")
        if len(first_tokens) > 1:
            reasons.append("different_first_name_tokens")
        if reasons:
            errors.append({"cluster": index, "reasons": reasons, "anchors": anchors,
                           "codes": codes, "names": names})
    return errors


def _largest(details: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    return sorted(details, key=lambda row: (-int(row["observations"]), row["cluster_key"]))[:limit]


def run_resolve(ledger: Ledger, state: dict[str, Any], start: dt.date | None = None,
                end: dt.date | None = None, *, resume: bool = False) -> dict[str, Any]:
    output = ledger.staging_path("resolve")
    prior = state.get("stages", {}).get("resolve", {})
    if resume and prior.get("status") == "complete" and output.exists():
        return prior.get("checkpoint", {})
    source = ledger.staging_path("normalize")
    if not source.exists():
        raise FileNotFoundError("يجب تشغيل normalize للدفعة أولًا")
    core_path = ledger.data_dir / "core.json"
    if not core_path.exists():
        raise FileNotFoundError("ملف core.json غير موجود في مجلد البيانات")
    ledger.mark_stage(state, "resolve", "running")
    records = _load_jsonl(source)
    if start:
        records = [record for record in records if record["date"] >= start.isoformat()]
    if end:
        records = [record for record in records if record["date"] <= end.isoformat()]
    core = json.loads(core_path.read_text(encoding="utf-8"))
    officers, personnel = collect_observations(records, _quarantined(ledger.staging_path("validate")))
    officer_result = _resolve_strong(officers, _anchor_observations(core, "officer"), "officer")
    personnel_result = _resolve_strong(personnel, _anchor_observations(core, "personnel"), "personnel")
    review_dir = ledger.root / "review"
    decisions_dir = ledger.root / "decisions"
    review_dir.mkdir(parents=True, exist_ok=True)
    decisions_dir.mkdir(parents=True, exist_ok=True)
    officer_decisions = _read_decisions(decisions_dir / "officers.csv")
    personnel_decisions = _read_decisions(decisions_dir / "personnel.csv")

    def details_for(result: Resolution, kind: str, decisions: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
        events = defaultdict(list)
        for event in result.merges:
            events[event["cluster"]].append(event)
        preliminary = [_cluster_details(group, kind, index + 1, result.conflicts.get(index, set()),
                                        merge_events=events[index])
                       for index, group in enumerate(result.groups)]
        return [_cluster_details(group, kind, index + 1, result.conflicts.get(index, set()),
                                 decisions.get(preliminary[index]["cluster_key"]), events[index])
                for index, group in enumerate(result.groups)]

    officer_details = details_for(officer_result, "officer", officer_decisions)
    personnel_details = details_for(personnel_result, "personnel", personnel_decisions)
    ignored_officers = {index for index, row in enumerate(officer_details) if row["status"] == "تجاهل"}
    ignored_personnel = {index for index, row in enumerate(personnel_details) if row["status"] == "تجاهل"}

    def drop_ignored(result: Resolution, ignored: set[int], kind: str) -> None:
        for index in ignored:
            for item in result.groups[index]:
                if item.role == _ANCHOR_ROLE:
                    continue
                result.mapping.pop(item.key, None)
                result.unresolved.append({
                    "identity_type": kind, "observation_key": item.key, "date": item.date,
                    "name": item.name, "source_text": item.source_text,
                    "reason": "ignored_by_reviewer", "candidate_roots": [],
                })

    drop_ignored(officer_result, ignored_officers, "officer")
    drop_ignored(personnel_result, ignored_personnel, "personnel")
    active_officers = [row for index, row in enumerate(officer_details) if index not in ignored_officers]
    active_personnel = [row for index, row in enumerate(personnel_details) if index not in ignored_personnel]
    _write_csv(review_dir / "officers.csv", _REVIEW_FIELDS, active_officers)
    _write_csv(review_dir / "personnel.csv", _REVIEW_FIELDS, active_personnel)
    _write_current_decisions(decisions_dir / "officers.csv", officer_details, officer_decisions)
    _write_current_decisions(decisions_dir / "personnel.csv", personnel_details, personnel_decisions)
    atomic_write_jsonl(output, ([{"identity_type": "officer", **row} for row in active_officers] +
                                [{"identity_type": "personnel", **row} for row in active_personnel]))
    atomic_write_jsonl(ledger.staging_path("resolve-unresolved"),
                       [*officer_result.unresolved, *personnel_result.unresolved])
    proposed = {
        "batch": ledger.batch,
        "officers": {item.key: officer_details[int(cluster)]["proposed_id"] for item in officers
                     if (cluster := officer_result.mapping.get(item.key)) is not None},
        "personnel": {item.key: personnel_details[int(cluster)]["proposed_id"] for item in personnel
                      if (cluster := personnel_result.mapping.get(item.key)) is not None},
    }
    atomic_write_json(ledger.staging_path("id_map.proposed").with_suffix(".json"), proposed)
    reference = {"officers": _reference_report(
        ledger.data_dir, ["2026-09-01", "2026-09-02"], "officer", officers,
        officer_result.mapping, officer_details,
    ), "personnel": _reference_report(
        ledger.data_dir, ["2026-09-01", "2026-09-02"], "personnel", personnel,
        personnel_result.mapping, personnel_details,
    )}
    atomic_write_json(ledger.report_path("resolve-reference-mismatches.json"), reference)
    self_check = {"officers": _self_check(officer_result.groups, "officer"),
                  "personnel": _self_check(personnel_result.groups, "personnel")}
    atomic_write_json(ledger.report_path("resolve-self-check.json"), self_check)
    atomic_write_json(ledger.report_path("resolve-largest-clusters.json"), {
        "officers": _largest(officer_details), "personnel": _largest(personnel_details),
    })
    merge_report = {
        "officers": [{"id": officer_details[event["cluster"]]["proposed_id"], **event}
                     for event in officer_result.merges],
        "personnel": [{"id": personnel_details[event["cluster"]]["proposed_id"], **event}
                      for event in personnel_result.merges],
    }
    candidate_report = {
        "officers": [{
            **row,
            "left_id": officer_details[row["left_cluster"]]["proposed_id"],
            "right_id": officer_details[row["right_cluster"]]["proposed_id"],
        } for row in officer_result.remaining_candidates],
        "personnel": [{
            **row,
            "left_id": personnel_details[row["left_cluster"]]["proposed_id"],
            "right_id": personnel_details[row["right_cluster"]]["proposed_id"],
        } for row in personnel_result.remaining_candidates],
    }
    atomic_write_json(ledger.report_path("resolve-consolidation-merges.json"), merge_report)
    atomic_write_json(ledger.report_path("resolve-consolidation-candidates.json"), candidate_report)

    def junk_clusters(groups: list[list[Observation]]) -> list[int]:
        result = []
        for index, group in enumerate(groups):
            names = [item.name_key for item in group if item.role != _ANCHOR_ROLE]
            if names and all(any(token in _NON_NAME_TOKENS for token in _tokens(name)) for name in names):
                result.append(index)
        return result
    junk = {"officers": junk_clusters(officer_result.groups),
            "personnel": junk_clusters(personnel_result.groups)}
    atomic_write_json(ledger.report_path("resolve-junk-clusters.json"), junk)

    def metrics(rows: list[dict[str, Any]], unresolved: list[dict[str, Any]]) -> dict[str, int]:
        return {"clusters": len(rows),
                "matched_existing": sum(bool(row["existing_id"]) and int(row["observations"]) > 0 for row in rows),
                "new": sum(row["proposed_id"].startswith("NEW-") for row in rows),
                "review": sum(row["status"] == "مراجعة" for row in rows),
                "unresolved_observations": len(unresolved)}
    reference_counts = {kind: sum(len(rows) for rows in values.values()) for kind, values in reference.items()}
    checkpoint = {
        "officers": metrics(active_officers, officer_result.unresolved),
        "personnel": metrics(active_personnel, personnel_result.unresolved),
        "reference_mismatches": reference_counts,
        "self_check_errors": sum(len(values) for values in self_check.values()),
        "fuzzy_merges": {kind: sum(row["rule"] == "fuzzy_no_cooccurrence" for row in rows)
                         for kind, rows in merge_report.items()},
        "reported_merges": {kind: len(rows) for kind, rows in merge_report.items()},
        "remaining_candidates": {kind: len(rows) for kind, rows in candidate_report.items()},
        "junk_clusters": sum(len(values) for values in junk.values()), "version": VERSION,
    }
    ledger.mark_stage(state, "resolve", "complete", checkpoint)
    return checkpoint


__all__ = ["VERSION", "Observation", "cluster_officers", "cluster_personnel",
           "collect_observations", "run_resolve"]
