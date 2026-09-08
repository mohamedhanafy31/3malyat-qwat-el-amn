"""تخزين البيانات — ملف JSON واحد، بقفل خيط وكتابة ذرية (tmp file replace)."""
import json
import threading
from pathlib import Path

from .constants import DEFAULT_DATA

DATA_FILE = Path(__file__).resolve().parent.parent / "data.json"
LOCK = threading.Lock()


def load_data():
    with LOCK:
        if not DATA_FILE.exists():
            save_data(DEFAULT_DATA)
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return json.loads(json.dumps(DEFAULT_DATA))
    for cat in ("officers", "personnel"):
        data.setdefault(cat, {"active": [], "archive": []})
        data[cat].setdefault("active", [])
        data[cat].setdefault("archive", [])
    data.setdefault("leaves", [])
    data.setdefault("services", [])
    data.setdefault("duties", {})
    data.setdefault("day_services", {})
    data.setdefault("board_categories", list(DEFAULT_DATA["board_categories"]))
    data.setdefault("service_tags", [])
    return data


def save_data(data):
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DATA_FILE)


def next_id(items, prefix, width=3):
    nums = [int(x["id"].split("-")[-1]) for x in items
            if str(x.get("id", "")).startswith(prefix + "-") and x["id"].split("-")[-1].isdigit()]
    return f"{prefix}-{(max(nums) + 1) if nums else 1:0{width}d}"
