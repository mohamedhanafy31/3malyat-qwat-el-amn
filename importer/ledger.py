"""بنية سجل الاستيراد وعمليات الكتابة الذرية."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable


LEDGER_DIRS = ("batches", "provenance", "quarantine", "reports", "preimage", "staging")


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        with tmp.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, value: Any) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write_text(path, text)


def atomic_write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    lines = (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for record in records)
    atomic_write_text(path, "".join(line + "\n" for line in lines))


class Ledger:
    def __init__(self, data_dir: Path, batch: str):
        self.data_dir = Path(data_dir)
        self.root = self.data_dir / "import"
        self.batch = batch

    @property
    def batch_file(self) -> Path:
        return self.root / "batches" / f"{self.batch}.json"

    def initialise(self, params: dict[str, Any], extractor_versions: dict[str, str]) -> dict[str, Any]:
        for name in LEDGER_DIRS:
            (self.root / name).mkdir(parents=True, exist_ok=True)
        (self.root / "preimage" / self.batch).mkdir(parents=True, exist_ok=True)
        (self.root / "staging" / self.batch).mkdir(parents=True, exist_ok=True)
        id_map = self.root / "id_map.json"
        if not id_map.exists():
            atomic_write_json(id_map, {})
        state = {
            "batch": self.batch,
            "params": params,
            "extractor_versions": extractor_versions,
            "stages": {},
        }
        if self.batch_file.exists():
            try:
                previous = json.loads(self.batch_file.read_text(encoding="utf-8"))
                if previous.get("params") == params:
                    state["stages"] = previous.get("stages", {})
            except (OSError, json.JSONDecodeError):
                pass
        atomic_write_json(self.batch_file, state)
        return state

    def mark_stage(self, state: dict[str, Any], stage: str, status: str,
                   checkpoint: dict[str, Any] | None = None) -> None:
        state["stages"][stage] = {"status": status, "checkpoint": checkpoint or {}}
        atomic_write_json(self.batch_file, state)

    def staging_path(self, stage: str) -> Path:
        return self.root / "staging" / self.batch / f"{stage}.jsonl"

    def report_path(self, suffix: str) -> Path:
        return self.root / "reports" / f"{self.batch}-{suffix}"

